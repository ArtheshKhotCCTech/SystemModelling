# Purpose: pins the CLI contract — `--help` lists every subcommand (FR-01 acceptance 1), stages
# not yet delivered are honest stubs that exit non-zero, `ingest` writes evidence.json and exits
# 2 on a missing input (phase 3), `cache clear` empties the response cache, and `doctor` prints
# one OK/FAIL line per check, exits non-zero on any FAIL and never prints the API key. `extract`
# (phase 4) is covered by test_extract_stage.py. Phase 5: `generate --only sysml` writes
# model.sysml and `compile --only sysml` writes sysml_validation.json, with FR-09 exit codes.
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
STUBS = ["verify", "report", "run"]
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


def test_generate_modelica_is_not_implemented_in_this_phase(tmp_path, capsys):
    assert cli.main(["generate", "--ir", str(GOLDEN), "-o", str(tmp_path),
                     "--only", "modelica"]) == cli.EXIT_FAILED
    assert "not implemented in this phase" in capsys.readouterr().err
    assert not (tmp_path / "model.sysml").exists()


def test_generate_without_only_writes_sysml_and_says_modelica_did_not_run(tmp_path, capsys):
    assert cli.main(["generate", "--ir", str(GOLDEN), "-o", str(tmp_path)]) == cli.EXIT_FAILED
    assert (tmp_path / "model.sysml").is_file()
    assert "modelica" in capsys.readouterr().err


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


def test_compile_modelica_is_not_implemented_in_this_phase(tmp_path, capsys):
    assert cli.main(["compile", "-o", str(tmp_path), "--only", "modelica"]) == cli.EXIT_FAILED
    assert "not implemented in this phase" in capsys.readouterr().err


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
