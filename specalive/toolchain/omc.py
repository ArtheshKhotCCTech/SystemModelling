# Purpose: runs OpenModelica `omc`. Phase 1 delivers the toolchain probe only: `omc --version`,
# then a .mos script that loads the pinned MSL and simulates an MSL example model. omc reports
# most failures through getErrorString() rather than its exit code, so the script prints each
# result behind a SPECALIVE_* marker and the parser treats any "Error:" text as failure.
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from specalive.config import Settings
from specalive.toolchain.process import ProbeResult, ToolResult, run_tool

PROBE_MODEL = "Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks"
_MARKERS = ("LOADED", "RESULTFILE", "LOADERR", "SIMERR", "MESSAGES", "END")
_ERROR_RE = re.compile(r"(^|\]\s*)Error:", re.MULTILINE)


def version(settings: Settings) -> ToolResult:
    return run_tool([settings.omc_path, "--version"], timeout=60)


def probe_script(msl_version: str) -> str:
    return "\n".join([
        "echo(false);",
        f'loaded := loadModel(Modelica, {{"{msl_version}"}});',
        "loadErr := getErrorString();",
        f"res := simulate({PROBE_MODEL});",
        "simErr := getErrorString();",
        # omc 1.27 rejects `res.resultFile` inside a string expression; copy fields out first.
        "resultFile := res.resultFile;",
        "simMessages := res.messages;",
        "echo(true);",
        'print("SPECALIVE_LOADED=" + String(loaded) + "\\n");',
        'print("SPECALIVE_RESULTFILE=" + resultFile + "\\n");',
        'print("SPECALIVE_LOADERR=" + loadErr + "\\n");',
        'print("SPECALIVE_SIMERR=" + simErr + "\\n");',
        'print("SPECALIVE_MESSAGES=" + simMessages + "\\n");',
        'print("SPECALIVE_END\\n");',
        "",
    ])


def _fields(stdout: str) -> dict[str, str] | None:
    """Split the marker-delimited output; values may span lines (omc error text does)."""
    values: dict[str, str] = {}
    for name, nxt in zip(_MARKERS, _MARKERS[1:]):
        m = re.search(rf"SPECALIVE_{name}=(.*?)\n?SPECALIVE_{nxt}\b", stdout, re.DOTALL)
        if m is None:
            return None
        values[name] = m.group(1).strip()
    return values


def parse_probe_output(stdout: str) -> tuple[bool, str]:
    ok, detail, _ = _interpret(stdout)
    return ok, detail


def _interpret(stdout: str) -> tuple[bool, str, str]:
    """(ok, one-line detail, result file path as omc reported it)."""
    f = _fields(stdout)
    if f is None:
        tail = stdout.strip()[-300:] or "(no output)"
        return False, f"unexpected omc output: {tail}", ""
    if f["LOADED"] != "true":
        return False, f"MSL did not load: {f['LOADERR'] or 'no message'}", ""
    errors = "\n".join(t for t in (f["LOADERR"], f["SIMERR"]) if _ERROR_RE.search(t))
    if errors:
        return False, f"{PROBE_MODEL} failed: {errors}", f["RESULTFILE"]
    if not f["RESULTFILE"]:
        reason = f["SIMERR"] or f["MESSAGES"] or "no message"
        return False, f"{PROBE_MODEL} produced no result file: {reason}", ""
    notes = " ".join(t for t in (f["LOADERR"], f["SIMERR"]) if t)
    detail = f"simulated {PROBE_MODEL} -> {Path(f['RESULTFILE']).name}"
    return True, (f"{detail} ({notes})" if notes else detail), f["RESULTFILE"]


def probe(settings: Settings) -> ProbeResult:
    ver = version(settings)
    if not ver.ok:
        return ProbeResult(False, f"omc --version failed: {ver.stderr.strip() or ver.stdout.strip()}",
                           (ver,))
    omc_version = ver.stdout.strip().splitlines()[0] if ver.stdout.strip() else "unknown version"
    with tempfile.TemporaryDirectory(prefix="specalive-omc-") as work:
        script = Path(work) / "probe.mos"
        script.write_text(probe_script(settings.msl_version), encoding="utf-8")
        run = run_tool([settings.omc_path, script.name], timeout=settings.omc_timeout_s,
                       cwd=Path(work))
        ok, detail, result_file = _interpret(run.stdout)
        if ok and not (Path(work) / result_file).exists():
            ok, detail = False, f"omc reported a result file that does not exist: {result_file}"
    if ok and not run.ok:
        ok, detail = False, f"omc exited with {run.returncode}: {run.stderr.strip()}"
    return ProbeResult(ok, f"{omc_version}; {detail}", (ver, run))
