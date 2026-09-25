# Purpose: pins the CLI contract — `--help` lists every subcommand (FR-01 acceptance 1), stages
# not yet delivered are honest stubs that exit non-zero, `ingest` writes evidence.json and exits
# 2 on a missing input (phase 3), `cache clear` empties the response cache, and `doctor` prints
# one OK/FAIL line per check, exits non-zero on any FAIL and never prints the API key. `extract`
# (phase 4) is covered by test_extract_stage.py. Phase 5: `generate --only sysml` writes
# model.sysml and `compile --only sysml` writes sysml_validation.json, with FR-09 exit codes.
# Phase 6: `generate` writes model.mo, and `compile` runs the Modelica compile-and-repair loop.
# Phase 7: `verify` writes sim/result.csv, verification.json and coverage.json, with its exit codes.
import json
import subprocess
import sys
from pathlib import Path

import pytest

from specalive import cli
from specalive.llm.cache import ResponseCache
from specalive.toolchain import sysml_validate
from specalive.toolchain.process import ToolResult

SUBCOMMANDS = ["ingest", "extract", "generate", "compile", "verify", "report", "run", "cache",
               "doctor"]
STUBS = ["report", "run"]
GOLDEN = Path(__file__).parent / "goldens" / "L1_tank.ir.json"


def test_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in SUBCOMMANDS:
        assert name in out


def test_console_entry_point_runs_as_module():
    r = subprocess.run([sys.executable, "-m", "specalive.cli", "--help"],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and "doctor" in r.stdout


@pytest.mark.parametrize("name", STUBS)
def test_stubs_say_not_implemented_and_exit_nonzero(name, capsys):
    code = cli.main([name])
    assert code != 0
    assert "not implemented in this phase" in capsys.readouterr().err


def test_generate_sysml_writes_model_file(tmp_path, capsys):
    assert cli.main(["generate", "--ir", str(GOLDEN), "-o", str(tmp_path), "--only", "sysml"]) == 0
    model = tmp_path / "model.sysml"
    assert model.is_file() and "state def plc_101_sequence" in model.read_text(encoding="utf-8")
    assert "wrote" in capsys.readouterr().out


def test_generate_reads_ir_json_from_the_out_folder_by_default(tmp_path):
    (tmp_path / "ir.json").write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["generate", "-o", str(tmp_path), "--only", "sysml"]) == 0
    assert (tmp_path / "model.sysml").is_file()


def test_generate_modelica_writes_model_mo(tmp_path, capsys):
    assert cli.main(["generate", "--ir", str(GOLDEN), "-o", str(tmp_path),
                     "--only", "modelica"]) == cli.EXIT_OK
    model = tmp_path / "model.mo"
    assert model.is_file() and "model System" in model.read_text(encoding="utf-8")
    assert not (tmp_path / "model.sysml").exists()
    out = capsys.readouterr().out
    assert "wrote" in out and "generator default" in out  # the declared Interval default


def test_generate_without_only_writes_both_models(tmp_path):
    assert cli.main(["generate", "--ir", str(GOLDEN), "-o", str(tmp_path)]) == cli.EXIT_OK
    assert (tmp_path / "model.sysml").is_file() and (tmp_path / "model.mo").is_file()


def test_generate_modelica_error_is_an_input_problem(tmp_path, capsys):
    ir = json.loads(GOLDEN.read_text(encoding="utf-8"))
    ir["parameters"] = [p for p in ir["parameters"] if p["id"] != "tk_101_area"]
    for r in ir["requirements"]:
        r["satisfied_by"] = [e for e in r["satisfied_by"] if e != "tk_101_area"]
    bad = tmp_path / "ir.json"
    bad.write_text(json.dumps(ir), encoding="utf-8")
    assert cli.main(["generate", "--ir", str(bad), "-o", str(tmp_path),
                     "--only", "modelica"]) == cli.EXIT_INPUT
    assert "area" in capsys.readouterr().err
    assert not (tmp_path / "model.mo").exists()


def test_generate_missing_or_broken_ir_is_an_input_problem(tmp_path, capsys):
    assert cli.main(["generate", "--ir", str(tmp_path / "nope.json"), "-o", str(tmp_path),
                     "--only", "sysml"]) == cli.EXIT_INPUT
    ir = json.loads(GOLDEN.read_text(encoding="utf-8"))
    ir["connections"][0]["to_port"] = "no_such_port"
    broken = tmp_path / "ir.json"
    broken.write_text(json.dumps(ir), encoding="utf-8")
    assert cli.main(["generate", "--ir", str(broken), "-o", str(tmp_path),
                     "--only", "sysml"]) == cli.EXIT_INPUT
    assert "no_such_port" in capsys.readouterr().err
    assert not (tmp_path / "model.sysml").exists()


def _fake_validation(status, stdout=""):
    run = ToolResult(True, ("java", "-cp", "pilot.jar", "Main"), stdout, "", 1.0, 0)
    if status == sysml_validate.NOT_RUN:
        return lambda settings, path: sysml_validate.Validation(status, "Pilot not found")
    return lambda settings, path: sysml_validate.interpret(run)


@pytest.mark.parametrize("status,stdout,code", [
    (sysml_validate.OK, "1> Package P (0e0e3b6a-7c65)\n", cli.EXIT_OK),
    (sysml_validate.FAILED, "1> ERROR:bad (1.sysml line : 3 column : 4)\n", cli.EXIT_FAILED),
    (sysml_validate.NOT_RUN, "", cli.EXIT_TOOLCHAIN),
])
def test_compile_sysml_writes_the_validation_report(tmp_path, monkeypatch, capsys, status,
                                                    stdout, code):
    (tmp_path / "model.sysml").write_text("package P {}\n", encoding="utf-8")
    monkeypatch.setattr(cli.sysml_validate, "validate_file", _fake_validation(status, stdout))
    assert cli.main(["compile", "-o", str(tmp_path), "--only", "sysml"]) == code
    report = json.loads((tmp_path / "sysml_validation.json").read_text(encoding="utf-8"))
    assert report["status"] == status
    out = capsys.readouterr().out
    assert status in out
    if status != sysml_validate.NOT_RUN:
        assert report["command"] and report["command"] in out


def test_compile_without_model_is_an_input_problem(tmp_path, capsys):
    assert cli.main(["compile", "-o", str(tmp_path), "--only", "sysml"]) == cli.EXIT_INPUT
    assert "model.sysml" in capsys.readouterr().err


def _fake_loop(status, calls=None):
    def fake(mo_path, out_dir, *, settings, llm, ir_summary):
        if calls is not None:
            calls.append((mo_path, ir_summary))
        delivered = mo_path if status in ("ok", "repaired") else None
        return cli.compile_loop.LoopResult(
            status=status, model_name="P.System", delivered=delivered,
            command=None if status == "NOT RUN" else "cd out/build && omc compile.mos",
            detail="scripted", errors=["Error: bad"] if status == "FAILED" else [])
    return fake


@pytest.mark.parametrize("status,code", [
    ("ok", cli.EXIT_OK), ("repaired", cli.EXIT_OK), ("FAILED", cli.EXIT_FAILED),
    ("NOT RUN", cli.EXIT_TOOLCHAIN)])
def test_compile_modelica_runs_the_repair_loop(tmp_path, monkeypatch, capsys, status, code):
    (tmp_path / "model.mo").write_text("package P end P;\n", encoding="utf-8")
    (tmp_path / "ir.json").write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli.compile_loop, "run_compile_loop", _fake_loop(status, calls))
    assert cli.main(["compile", "-o", str(tmp_path), "--only", "modelica"]) == code
    out = capsys.readouterr().out
    assert f"Modelica compile: {status}" in out
    if status != "NOT RUN":
        assert "omc compile.mos" in out
    assert calls and "tk_101" in calls[0][1]  # the IR summary reaches the loop


def test_compile_modelica_without_model_is_an_input_problem(tmp_path, capsys):
    assert cli.main(["compile", "-o", str(tmp_path), "--only", "modelica"]) == cli.EXIT_INPUT
    assert "model.mo" in capsys.readouterr().err


def test_compile_without_only_runs_both(tmp_path, monkeypatch, capsys):
    (tmp_path / "model.sysml").write_text("package P {}\n", encoding="utf-8")
    (tmp_path / "model.mo").write_text("package P end P;\n", encoding="utf-8")
    monkeypatch.setattr(cli.sysml_validate, "validate_file",
                        _fake_validation(sysml_validate.OK, "1> Package P (0e0e3b6a-7c65)\n"))
    monkeypatch.setattr(cli.compile_loop, "run_compile_loop", _fake_loop("FAILED"))
    assert cli.main(["compile", "-o", str(tmp_path)]) == cli.EXIT_FAILED
    out = capsys.readouterr().out
    assert "SysML validation: ok" in out and "Modelica compile: FAILED" in out


def test_ingest_writes_evidence_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: cli.Settings(cache_dir=tmp_path / "c"))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "notes.txt").write_text("Pump ran fine.\n", encoding="utf-8")
    (bundle / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    out = tmp_path / "out"
    assert cli.main(["ingest", str(bundle), "-o", str(out)]) == 0
    assert (out / "evidence.json").is_file()
    printed = capsys.readouterr().out
    assert "2 source(s)" in printed
    assert "unread" in printed and "diagram.png" in printed  # never silently skipped


def test_ingest_missing_input_is_an_input_problem(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: cli.Settings(cache_dir=tmp_path / "c"))
    assert cli.main(["ingest", str(tmp_path / "nope"), "-o", str(tmp_path / "o")]) == 2
    assert "not found" in capsys.readouterr().err
    assert cli.main(["ingest"]) == 2


def test_ingest_with_nothing_readable_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: cli.Settings(cache_dir=tmp_path / "c"))
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / "blob.bin").write_bytes(b"\x00\x01\xff")
    assert cli.main(["ingest", str(bundle), "-o", str(tmp_path / "o")]) == 2
    assert (tmp_path / "o" / "evidence.json").is_file()


def test_cache_clear_empties_the_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SPECALIVE_CACHE_DIR", str(tmp_path))
    cache = ResponseCache(tmp_path)
    cache.put(ResponseCache.key("m", "p", {}, "a"), {"x": 1})
    cache.put(ResponseCache.key("m", "p", {}, "b"), {"x": 2})
    assert cli.main(["cache", "clear"]) == 0
    assert "2" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.json"))


def _fake_checks(results):
    return lambda settings: [cli.Check(name, ok, detail) for name, ok, detail in results]


def test_doctor_all_ok_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "doctor_checks", _fake_checks(
        [("Python", True, "3.12.4"), ("omc", True, "1.26.3"),
         ("SysML v2 validator", True, "parsed"), ("OpenAI", True, "call succeeded")]))
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert out.count("OK") >= 4 and "FAIL" not in out


def test_doctor_any_fail_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "doctor_checks", _fake_checks(
        [("Python", True, "3.12.4"), ("omc", False, "omc not found")]))
    assert cli.main(["doctor"]) != 0
    out = capsys.readouterr().out
    assert "FAIL" in out and "omc not found" in out


def test_python_check_requires_312():
    assert cli.check_python((3, 12, 1)).ok
    assert not cli.check_python((3, 11, 9)).ok


def test_openai_check_without_key_fails_and_prints_no_secret(monkeypatch):
    from specalive.config import load_settings
    check = cli.check_openai(load_settings({}))
    assert not check.ok and "OPENAI_API_KEY" in check.detail


def test_openai_check_never_shows_the_key(monkeypatch, tmp_path):
    from specalive.config import load_settings
    from specalive.llm.client import LLMError

    def boom(self, **kwargs):
        raise LLMError("401 unauthorized", request_id="req_x")

    monkeypatch.setattr("specalive.llm.client.LLMClient.complete", boom)
    s = load_settings({"OPENAI_API_KEY": "sk-dont-print", "SPECALIVE_CACHE_DIR": str(tmp_path)})
    check = cli.check_openai(s)
    assert not check.ok and "sk-dont-print" not in check.detail and "req_x" in check.detail


# --- verify (phase 7) ------------------------------------------------------------------------

L1_BUNDLE = next((p for p in (Path(__file__).parent.parent / "Testcases").glob("tank*/tank*")
                  if p.is_dir()), None)


def _verify_run(tmp_path, ir_path=GOLDEN):
    """A run folder as generate and a successful compile leave it."""
    from specalive.core.catalogue import load_catalogue
    from specalive.core.ir import SystemModel
    from specalive.generate import modelica

    ir_text = Path(ir_path).read_text(encoding="utf-8")
    (tmp_path / "ir.json").write_text(ir_text, encoding="utf-8")
    generated = modelica.render_modelica(SystemModel.model_validate_json(ir_text),
                                         load_catalogue())
    (tmp_path / "model.mo").write_text(generated.text, encoding="utf-8")
    log = {"status": "ok", "model": generated.model_name, "delivered": "model.mo",
           "command": "cd build && omc compile.mos", "detail": "", "errors": [], "attempts": []}
    (tmp_path / "repair_log.json").write_text(json.dumps(log), encoding="utf-8")
    return generated.model_name


def _fake_simulation(status, values=None, times=(0.0, 900.0), assertion=None):
    from specalive.toolchain import omc
    from specalive.verify import simulate

    def fake(settings, choice, run_dir):
        trace, csv = None, None
        if values is not None:
            trace = simulate.Trace(list(times), {k: list(v) for k, v in values.items()})
            csv = Path(run_dir) / "sim" / "result.csv"
            csv.parent.mkdir(parents=True, exist_ok=True)
            csv.write_text("time\n0\n", encoding="utf-8")
        command = None if status == omc.NOT_RUN else "cd sim && omc simulate.mos"
        result = omc.SimulateResult(status, choice.name, csv, (), "", f"scripted {status}",
                                    command, assertion)
        return simulate.Simulation(result, choice, trace, csv)
    return fake


def test_verify_without_ir_is_an_input_problem(tmp_path, capsys):
    assert cli.main(["verify", "-o", str(tmp_path)]) == cli.EXIT_INPUT
    assert "ir.json" in capsys.readouterr().err


def test_verify_without_a_compiled_model_is_an_input_problem_and_still_reports(tmp_path, capsys):
    (tmp_path / "ir.json").write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["verify", "-o", str(tmp_path)]) == cli.EXIT_INPUT
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert report["simulation"]["status"] == "NOT RUN"
    assert all(c["status"] == "NOT CHECKED" for c in report["criteria"])
    assert "specalive compile" in capsys.readouterr().err


def test_verify_with_omc_missing_exits_three(tmp_path, monkeypatch, capsys):
    _verify_run(tmp_path)
    monkeypatch.setattr(cli.simulate, "run_simulation", _fake_simulation("NOT RUN"))
    assert cli.main(["verify", "-o", str(tmp_path)]) == cli.EXIT_TOOLCHAIN
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert report["simulation"]["status"] == "NOT RUN"
    assert report["status"] == "NOT RUN"


def test_verify_writes_every_artefact_and_fails_on_a_failed_criterion(tmp_path, monkeypatch,
                                                                       capsys):
    _verify_run(tmp_path)
    flat = {"plc_101.state": [1.0, 1.0], "plc_101.valve1": [0.0, 0.0],
            "plc_101.valve2": [0.0, 0.0], "plc_101.valve3": [0.0, 0.0]}
    monkeypatch.setattr(cli.simulate, "run_simulation", _fake_simulation("ok", flat))
    assert cli.main(["verify", "-o", str(tmp_path)]) == cli.EXIT_FAILED
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    criteria = {c["id"]: c for c in report["criteria"]}
    assert criteria["ac_03"]["status"] == "FAIL"  # never reaches TRANSFER_T1_T2 at 280 s
    assert criteria["ac_02"]["status"] == "PASS"
    assert criteria["ac_01"]["status"] == "NOT CHECKED" and criteria["ac_01"]["detail"]
    assert report["status"] == "FAIL"
    assert report["reference"]["status"] == "NOT RUN"  # no evidence.json, no --reference
    assert {t["name"] for t in report["tolerances"]} == {"event_time", "continuous_fraction"}
    assert (tmp_path / "sim" / "result.csv").is_file()
    cov = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert cov["status"] == "NOT RUN" and "--golden" in cov["reason"]
    out = capsys.readouterr().out
    assert "verification.json" in out and "ac_03" in out


def test_verify_passes_when_every_check_passes(tmp_path, monkeypatch, capsys):
    ir = json.loads(GOLDEN.read_text(encoding="utf-8"))
    ir["acceptance_criteria"] = [c for c in ir["acceptance_criteria"] if c["id"] == "ac_02"]
    ir_path = tmp_path / "in.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    _verify_run(tmp_path, ir_path)
    zeros = {"plc_101.valve1": [0.0, 0.0], "plc_101.valve2": [0.0, 0.0],
             "plc_101.valve3": [0.0, 0.0]}
    monkeypatch.setattr(cli.simulate, "run_simulation", _fake_simulation("ok", zeros))
    assert cli.main(["verify", "-o", str(tmp_path)]) == cli.EXIT_OK
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"


def test_verify_with_golden_writes_coverage(tmp_path, monkeypatch):
    _verify_run(tmp_path)
    monkeypatch.setattr(cli.simulate, "run_simulation", _fake_simulation("NOT RUN"))
    cli.main(["verify", "-o", str(tmp_path), "--golden", str(GOLDEN)])
    cov = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert cov["status"] == "ok" and cov["parts"]["percent"] == 100.0


def test_verify_with_a_missing_reference_is_an_input_problem(tmp_path, monkeypatch, capsys):
    _verify_run(tmp_path)
    monkeypatch.setattr(cli.simulate, "run_simulation", _fake_simulation("NOT RUN"))
    code = cli.main(["verify", "-o", str(tmp_path), "--reference", str(tmp_path / "none.csv")])
    assert code == cli.EXIT_INPUT and "none.csv" in capsys.readouterr().err


def test_verify_report_is_deterministic(tmp_path, monkeypatch):
    _verify_run(tmp_path)
    flat = {"plc_101.state": [1.0, 1.0], "plc_101.valve1": [0.0, 0.0]}
    monkeypatch.setattr(cli.simulate, "run_simulation", _fake_simulation("ok", flat))
    cli.main(["verify", "-o", str(tmp_path)])
    first = (tmp_path / "verification.json").read_bytes()
    cli.main(["verify", "-o", str(tmp_path)])
    assert (tmp_path / "verification.json").read_bytes() == first


@pytest.mark.skipif(L1_BUNDLE is None, reason="Testcases/ L1 bundle not present")
def test_acceptance_2_l1_golden_model_against_tp17_and_the_reference_trace(tmp_path):
    from specalive.config import load_settings
    from specalive.toolchain import omc

    if not omc.version(load_settings()).ok:
        pytest.skip("omc not installed or not on PATH/SPECALIVE_OMC")
    _verify_run(tmp_path)
    reference = L1_BUNDLE / "09_datasets" / "10_demo_run_900s.csv"
    code = cli.main(["verify", "-o", str(tmp_path), "--reference", str(reference)])
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert report["simulation"]["status"] == "ok"
    # FR-07 acceptance 2: every TP-17 criterion PASS, or NOT CHECKED with a reason
    for c in report["criteria"]:
        assert c["status"] == "PASS" or (c["status"] == "NOT CHECKED" and c["detail"]), c
    signals = {s["column"]: s for s in report["signals"]}
    state = signals["controller_state"]
    assert state["status"] == "PASS", state
    assert state["numbers"]["max_time_error"] <= 2.0
    assert signals["wait_remaining_s"]["status"] == "NOT COMPARED"
    assert code == cli.EXIT_OK
