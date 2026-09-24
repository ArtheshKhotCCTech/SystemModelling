# Purpose: pins the phase 1 CLI contract — `--help` lists every subcommand (FR-01 acceptance 1),
# pipeline stages are honest stubs that exit non-zero, `cache clear` empties the response
# cache, and `doctor` prints one OK/FAIL line per check, exits non-zero on any FAIL and never
# prints the API key.
import subprocess
import sys

import pytest

from specalive import cli
from specalive.llm.cache import ResponseCache

SUBCOMMANDS = ["ingest", "extract", "generate", "compile", "verify", "report", "run", "cache",
               "doctor"]
STUBS = ["ingest", "extract", "generate", "compile", "verify", "report", "run"]


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
