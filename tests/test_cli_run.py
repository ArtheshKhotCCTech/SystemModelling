# Purpose: pins `specalive run` (FR-09) with the LLM, the SysML validator, the omc compile loop
# and the simulation scripted, so it runs offline: every stage prints start, result and duration
# (R-CLI-1); a failed stage degrades the run and reports are still written (R-CLI-2); exit codes
# keep input and infrastructure problems apart (R-CLI-3, acceptance 4); run.json records inputs,
# versions, per-stage status and timing, token use and the compile command; --no-llm-cache,
# --interactive, --reference and --golden. The real L1 run (acceptance 1-2) is marked slow.
import json
import time
from pathlib import Path

import pytest

from _extract_support import FakeLLM, connection, empty_reply, param, part
from specalive import cli
from specalive.toolchain import omc, sysml_validate
from specalive.toolchain.process import ToolResult
from specalive.verify import simulate

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "goldens" / "L1_tank.ir.json"
L1_BUNDLE = next((p for p in (HERE.parent / "Testcases").glob("tank*/tank*") if p.is_dir()), None)

SPEC = ("SRC-1 supplies valve XV-1, which fills tank TK-1. Tank area (m2): 2. "
        "Valve nominal flow (m3/s): 0.01.\n")
CHUNK = "src_spec_txt#0"


def _reply(text, chunk=CHUNK):
    """The structure reply for SPEC, quoting chunk `chunk`."""
    return empty_reply(
        system_name="Fill demo",
        parts=[part(chunk, "SRC-1 supplies valve XV-1", "SRC-1", "fluid_source"),
               part(chunk, "valve XV-1", "XV-1", "on_off_valve"),
               part(chunk, "fills tank TK-1", "TK-1", "tank")],
        connections=[connection(chunk, "SRC-1 supplies valve XV-1", "SRC-1", "XV-1"),
                     connection(chunk, "XV-1, which fills tank TK-1", "XV-1", "TK-1")],
        parameters=[param(chunk, "Tank area (m2): 2", "TK-1", "area", "2", "m2"),
                    param(chunk, "Valve nominal flow (m3/s): 0.01", "XV-1", "nominal_flow",
                          "0.01", "m3/s")])


class _Usage:
    def __init__(self, cached):
        self.model, self.input_tokens, self.output_tokens = "gpt-test", 100, 20
        self.cost_usd, self.cached = 0.001, cached


class CountingLLM(FakeLLM):
    """FakeLLM that also records usage the way LLMClient does."""

    def __init__(self):
        super().__init__({"FragmentReply": _reply})
        self.usage = []

    def complete(self, **kwargs):
        self.usage.append(_Usage(cached=False))
        return super().complete(**kwargs)


def _validation_ok(settings, path):
    run = ToolResult(True, ("java", "Main"), "1> Package P (0e0e3b6a-7c65)\n", "", 0.1, 0)
    return sysml_validate.interpret(run)


def _loop(status):
    def fake(mo_path, out_dir, *, settings, llm, ir_summary):
        delivered = mo_path if status in ("ok", "repaired") else None
        command = None if status == "NOT RUN" else "cd build && omc compile.mos"
        log = {"status": status, "model": "Fill_demo.System",
               "delivered": delivered.name if delivered else None, "command": command,
               "detail": "scripted", "errors": [], "attempts": []}
        (Path(out_dir) / "repair_log.json").write_text(json.dumps(log), encoding="utf-8")
        (Path(out_dir) / "compile.log").write_text("scripted\n", encoding="utf-8")
        return cli.compile_loop.LoopResult(status=status, model_name="Fill_demo.System",
                                           delivered=delivered, command=command,
                                           detail="scripted")
    return fake


def _simulation(settings, choice, run_dir):
    csv = Path(run_dir) / simulate.SIM_DIR / simulate.RESULT_FILE
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text("time,tk_1.level\n0,0\n10,0.05\n", encoding="utf-8")
    trace = simulate.Trace([0.0, 10.0], {"tk_1.level": [0.0, 0.05]})
    result = omc.SimulateResult(omc.OK, choice.name, csv, (), "", "scripted ok",
                                "cd sim && omc simulate.mos", None)
    return simulate.Simulation(result, choice, trace, csv)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Settings with a scratch cache, a scripted LLM and toolchain, and a spec file."""
    monkeypatch.setattr(cli, "load_settings", lambda: cli.Settings(cache_dir=tmp_path / "c"))
    llm = CountingLLM()
    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: llm)
    monkeypatch.setattr(cli.sysml_validate, "validate_file", _validation_ok)
    monkeypatch.setattr(cli.compile_loop, "run_compile_loop", _loop("ok"))
    monkeypatch.setattr(cli.simulate, "run_simulation", _simulation)
    monkeypatch.setattr(cli.omc, "version",
                        lambda s: ToolResult(True, ("omc", "--version"), "OMC 1.26.0\n", "", 0.1, 0))
    spec = tmp_path / "spec.txt"
    spec.write_text(SPEC, encoding="utf-8")
    return {"spec": spec, "out": tmp_path / "run", "llm": llm, "tmp": tmp_path}


def _run_json(out):
    return json.loads((out / "run.json").read_text(encoding="utf-8"))


def _stages(out):
    return {s["name"]: s for s in _run_json(out)["stages"]}


def test_run_on_a_text_spec_produces_every_artefact(env, capsys):
    out = env["out"]
    assert cli.main(["run", str(env["spec"]), "-o", str(out)]) == cli.EXIT_OK
    for name in ("evidence.json", "ir.json", "extract_report.json", "model.sysml", "model.mo",
                 "sysml_validation.json", "repair_log.json", "verification.json",
                 "coverage.json", "run.json", "run.log", "report/summary.md",
                 "report/traceability.md", "report/assumptions.md", "report/correspondence.md"):
        assert (out / name).exists(), name
    stages = _stages(out)
    assert list(stages) == list(cli.RUN_STAGES)
    assert all(s["status"] == "ok" for s in stages.values()), stages


def test_every_stage_prints_start_result_and_duration(env, capsys):
    cli.main(["run", str(env["spec"]), "-o", str(env["out"])])
    printed = capsys.readouterr().out
    for name in cli.RUN_STAGES:
        assert f"==> {name}" in printed, name
        assert any(line.startswith(f"<== {name}: ") and line.rstrip().endswith(" s)")
                   for line in printed.splitlines()), name
    assert "source 1 of 1" in printed  # the LLM stage says what it is working on
    assert "outcome" in printed.lower()
    for name in cli.RUN_STAGES:  # the closing one-screen table names every stage
        assert printed.lower().rfind(name) > printed.lower().find("outcome")


def test_run_json_records_inputs_versions_stages_tokens_and_command(env):
    out = env["out"]
    cli.main(["run", str(env["spec"]), "-o", str(out), "--golden", str(GOLDEN)])
    data = _run_json(out)
    assert data["input"]["path"] == str(env["spec"]) and data["input"]["kind"] == "text_file"
    assert data["input"]["golden"] == str(GOLDEN)
    assert data["tools"]["omc"] == "OMC 1.26.0" and data["tools"]["msl"]
    assert data["tools"]["specalive"] and data["tools"]["python"].startswith("3.")
    assert data["llm"]["model"] and data["llm"]["calls"] == len(env["llm"].calls) >= 1
    assert data["llm"]["input_tokens"] == 100 * data["llm"]["calls"]
    assert data["llm"]["cost_usd"] == pytest.approx(0.001 * data["llm"]["calls"])
    assert data["compile_command"] == "cd build && omc compile.mos"
    assert data["exit_code"] == cli.EXIT_OK
    assert data["started"] and data["finished"] and data["first_draft_s"] is not None
    for s in data["stages"]:
        assert set(s) >= {"name", "status", "exit_code", "duration_s", "detail"}
    cov = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert cov["status"] == "ok"  # --golden reached verify


def test_timestamps_stay_out_of_the_models(env):
    out = env["out"]
    cli.main(["run", str(env["spec"]), "-o", str(out)])
    first = {n: (out / n).read_bytes() for n in ("ir.json", "model.sysml", "model.mo")}
    time.sleep(1.1)
    cli.main(["run", str(env["spec"]), "-o", str(out)])
    assert {n: (out / n).read_bytes() for n in first} == first


def test_text_option_runs_without_an_input_path(env):
    out = env["out"]
    # pasted text is named "text", so its chunk id differs from the file's
    env["llm"].replies["FragmentReply"] = lambda t: _reply(t, "src_text#0")
    assert cli.main(["run", "--text", SPEC.strip(), "-o", str(out)]) == cli.EXIT_OK
    assert _run_json(out)["input"]["kind"] == "text"
    assert (out / "evidence.json").is_file() and (out / "ir.json").is_file()


def test_empty_directory_exits_two_and_still_reports(env, capsys):
    empty = env["tmp"] / "empty"
    empty.mkdir()
    out = env["out"]
    assert cli.main(["run", str(empty), "-o", str(out)]) == cli.EXIT_INPUT
    err = capsys.readouterr().err
    assert "input problem" in err and "nothing" in err
    stages = _stages(out)
    assert stages["ingest"]["status"] == "input problem"
    for name in ("extract", "generate", "compile", "verify"):
        assert stages[name]["status"] == "NOT RUN" and stages[name]["detail"], name
    assert stages["report"]["status"] == "ok"
    assert (out / "report" / "summary.md").is_file()
    assert _run_json(out)["exit_code"] == cli.EXIT_INPUT


def test_missing_input_path_exits_two(env, capsys):
    assert cli.main(["run", str(env["tmp"] / "nope"), "-o", str(env["out"])]) == cli.EXIT_INPUT
    assert "not found" in capsys.readouterr().err
    assert cli.main(["run", "-o", str(env["out"])]) == cli.EXIT_INPUT


def test_omc_missing_exits_three_and_keeps_ir_sysml_and_reports(env, monkeypatch, capsys):
    monkeypatch.setattr(cli.compile_loop, "run_compile_loop", _loop("NOT RUN"))
    monkeypatch.setattr(cli.omc, "version",
                        lambda s: ToolResult(False, ("omc", "--version"), "", "not found", 0.0, -1))
    out = env["out"]
    assert cli.main(["run", str(env["spec"]), "-o", str(out)]) == cli.EXIT_TOOLCHAIN
    for name in ("ir.json", "model.sysml", "report/summary.md"):
        assert (out / name).is_file(), name
    stages = _stages(out)
    assert stages["compile"]["status"] == "infrastructure problem"
    assert stages["verify"]["status"] == "NOT RUN"
    assert _run_json(out)["tools"]["omc"].startswith("NOT FOUND")
    assert "infrastructure problem" in capsys.readouterr().err


def test_llm_unreachable_is_an_infrastructure_problem(env, monkeypatch, capsys):
    class Down:
        usage = []

        def complete(self, **kwargs):
            raise cli.LLMError("connection refused", request_id=None)

    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: Down())
    out = env["out"]
    assert cli.main(["run", str(env["spec"]), "-o", str(out)]) == cli.EXIT_TOOLCHAIN
    stages = _stages(out)
    assert stages["extract"]["status"] == "infrastructure problem"
    assert all(stages[n]["status"] == "NOT RUN" for n in ("generate", "compile", "verify"))
    assert (out / "report" / "summary.md").is_file()


def test_generation_error_degrades_and_exits_one(env, monkeypatch):
    def boom(model, catalogue, out):
        raise cli.modelica.ModelicaGenerationError("scripted generation failure")

    monkeypatch.setattr(cli.modelica, "write_modelica", boom)
    out = env["out"]
    assert cli.main(["run", str(env["spec"]), "-o", str(out)]) == cli.EXIT_FAILED
    stages = _stages(out)
    assert stages["generate"]["status"] == "failed"
    assert "scripted generation failure" in stages["generate"]["detail"]
    assert stages["verify"]["status"] == "NOT RUN"
    assert (out / "model.sysml").is_file()  # the SysML half still made it
    assert json.loads((out / "sysml_validation.json").read_text(encoding="utf-8"))["ok"]
    assert (out / "report" / "summary.md").is_file()


def test_compile_failure_exits_one(env, monkeypatch):
    monkeypatch.setattr(cli.compile_loop, "run_compile_loop", _loop("FAILED"))
    out = env["out"]
    assert cli.main(["run", str(env["spec"]), "-o", str(out)]) == cli.EXIT_FAILED
    assert _stages(out)["compile"]["status"] == "failed"
    assert _stages(out)["verify"]["status"] == "NOT RUN"


def test_stale_artefacts_from_an_earlier_run_are_removed(env, monkeypatch):
    out = env["out"]
    out.mkdir(parents=True)
    (out / "verification.json").write_text('{"status": "PASS"}', encoding="utf-8")
    (out / "notes.txt").write_text("mine", encoding="utf-8")
    monkeypatch.setattr(cli.compile_loop, "run_compile_loop", _loop("FAILED"))
    cli.main(["run", str(env["spec"]), "-o", str(out)])
    assert not (out / "verification.json").exists()  # never a pass the run did not earn
    assert (out / "notes.txt").read_text(encoding="utf-8") == "mine"  # not ours, kept


@pytest.mark.parametrize("codes,expected", [
    ({"ingest": 0, "extract": 0, "generate": 0, "compile": 0, "verify": 0}, 0),
    ({"ingest": 2}, 2),
    ({"ingest": 0, "extract": 2}, 2),
    ({"ingest": 0, "extract": 3}, 3),
    ({"ingest": 0, "extract": 0, "generate": 0, "compile": 3, "verify": None}, 3),
    ({"ingest": 0, "extract": 0, "generate": 0, "compile": 1, "verify": None}, 1),
    ({"ingest": 0, "extract": 0, "generate": 0, "compile": 3, "verify": 2}, 3),
    ({"ingest": 0, "extract": 0, "generate": 0, "compile": 0, "verify": 2}, 2),
    ({"ingest": 0, "extract": 0, "generate": 1, "compile": 1, "verify": None}, 1),
])
def test_exit_code_order(codes, expected):
    assert cli.run_exit_code(codes) == expected


def test_interactive_is_accepted_and_reported_not_delivered(env, capsys):
    out = env["out"]
    assert cli.main(["run", str(env["spec"]), "-o", str(out), "--interactive"]) == cli.EXIT_OK
    assert "not delivered" in capsys.readouterr().out
    assert "not delivered" in _run_json(out)["input"]["interactive"]


def test_no_llm_cache_gives_the_client_a_write_only_cache(env, monkeypatch):
    seen = {}

    def client(settings, cache=None):
        seen["cache"] = cache
        return env["llm"]

    monkeypatch.setattr(cli, "LLMClient", client)
    cli.main(["run", str(env["spec"]), "-o", str(env["out"]), "--no-llm-cache"])
    assert isinstance(seen["cache"], cli.WriteOnlyCache)
    assert _run_json(env["out"])["input"]["no_llm_cache"] is True
    cli.main(["run", str(env["spec"]), "-o", str(env["out"])])
    assert seen["cache"] is None


def test_reference_reaches_verify(env):
    ref = env["tmp"] / "ref.csv"
    ref.write_text("time_s,tank_level_m\n0,0\n10,0.05\n", encoding="utf-8")
    out = env["out"]
    cli.main(["run", str(env["spec"]), "-o", str(out), "--reference", str(ref)])
    report = json.loads((out / "verification.json").read_text(encoding="utf-8"))
    assert report["reference"]["path"] == str(ref)


def test_run_log_goes_to_the_file_not_the_terminal(env, capsys):
    import logging

    out = env["out"]
    cli.main(["run", str(env["spec"]), "-o", str(out)])
    logging.getLogger("specalive.test").info("after the run")
    text = (out / "run.log").read_text(encoding="utf-8")
    assert "run" in text and "after the run" not in text  # the handler is removed afterwards
    assert "INFO" not in capsys.readouterr().out


# --- the real L1 run (FR-09 acceptance 1-2) ----------------------------------------------------

@pytest.mark.slow
@pytest.mark.skipif(L1_BUNDLE is None, reason="Testcases/ L1 bundle not present")
def test_acceptance_1_2_l1_bundle_end_to_end(tmp_path, monkeypatch):
    from specalive.config import load_settings

    monkeypatch.setenv("SPECALIVE_CACHE_DIR", str(HERE / "fixtures" / "extract_cache"))
    monkeypatch.setenv("OPENAI_API_KEY", "")  # offline: recorded responses only, never .env's key
    if not omc.version(load_settings()).ok:
        pytest.skip("omc not installed or not on PATH/SPECALIVE_OMC")
    out = tmp_path / "tank"
    start = time.monotonic()
    code = cli.main(["run", str(L1_BUNDLE), "-o", str(out), "--golden", str(GOLDEN)])
    assert time.monotonic() - start < 600
    data = _run_json(out)
    assert data["first_draft_s"] < 120
    stages = {s["name"]: s for s in data["stages"]}
    assert stages["extract"]["status"] == "ok"
    assert stages["compile"]["status"] == "ok", stages["compile"]["detail"]
    report = json.loads((out / "verification.json").read_text(encoding="utf-8"))
    assert report["simulation"]["status"] == "ok"
    for c in report["criteria"]:
        assert c["status"] == "PASS" or (c["status"] == "NOT CHECKED" and c["detail"]), c
    # FR-07 acceptance 2 in full: what the golden IR can check must be checked and pass (a
    # criterion lost to NOT CHECKED is not a pass), and state changes match within +-2 s
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    checkable = {a["id"] for a in golden["acceptance_criteria"] if a.get("check")}
    status = {c["id"]: c["status"] for c in report["criteria"]}
    assert {i: status.get(i) for i in checkable} == {i: "PASS" for i in checkable}
    timed = [s for s in report["signals"] if s["kind"] in ("discrete", "state")]
    assert timed and all(s["status"] == "PASS" for s in timed), [
        (s["column"], s["detail"]) for s in timed if s["status"] != "PASS"]
    cov = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    for category in ("parts", "ports", "connections"):
        assert cov[category]["percent"] >= 80.0, (category, cov[category])
    assert code in (cli.EXIT_OK, cli.EXIT_FAILED)
