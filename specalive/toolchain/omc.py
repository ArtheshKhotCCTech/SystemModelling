# Purpose: runs OpenModelica `omc`. Phase 1: the toolchain probe (`omc --version`, then a .mos
# script that loads the pinned MSL and simulates an MSL example). Phase 6: compile — a
# compile.mos that loads the pinned MSL and one model file, runs checkModel and buildModel, and a
# parser for omc's `[file:line:col] Error: ...` messages. omc reports most failures through
# getErrorString() rather than its exit code, so every result is printed behind a SPECALIVE_*
# marker and any "Error:" text is failure. Results carry the exact command that reproduces them.
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
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


# --- compile (phase 6) ---------------------------------------------------------------------

COMPILE_SCRIPT = "compile.mos"
OK, FAILED, NOT_RUN = "ok", "failed", "NOT RUN"
_COMPILE_MARKERS = ("MSL", "FILE", "CHECK", "EXE", "MSLERR", "LOADERR", "CHECKERR", "BUILDERR",
                    "END")
_ERROR_KEYS = ("MSLERR", "LOADERR", "CHECKERR", "BUILDERR")
_MESSAGE_RE = re.compile(
    r"^(?:\[(?P<file>.+?):(?P<line>\d+):(?P<col>\d+)-\d+:\d+:\w+\]\s*)?"
    r"(?P<severity>Error|Warning|Notification): (?P<message>.*)$")


@dataclass(frozen=True)
class OmcMessage:
    severity: str
    message: str
    file: str | None
    line: int | None
    column: int | None
    text: str  # verbatim, as omc wrote it


@dataclass(frozen=True)
class CompileResult:
    status: str  # OK | FAILED | NOT_RUN
    model_name: str
    messages: tuple[OmcMessage, ...]
    detail: str
    command: str | None  # what a judge runs to reproduce this compile; None if omc did not run
    run: ToolResult | None = None

    @property
    def ok(self) -> bool:
        return self.status == OK

    @property
    def errors(self) -> list[OmcMessage]:
        return [m for m in self.messages if m.severity == "Error"]


def compile_script(model_file: str, model_name: str, msl_version: str) -> str:
    """Load the pinned MSL and `model_file`, check and build `model_name`, and print every
    step's result and error text behind markers (FR-06 requirement 10)."""
    prints = [("MSL", "String(mslLoaded)"), ("FILE", "String(fileLoaded)"), ("CHECK", "check"),
              ("EXE", "exe"), ("MSLERR", "mslErr"), ("LOADERR", "loadErr"),
              ("CHECKERR", "checkErr"), ("BUILDERR", "buildErr")]
    return "\n".join([
        "echo(false);",
        f'mslLoaded := loadModel(Modelica, {{"{msl_version}"}});',
        "mslErr := getErrorString();",
        f'fileLoaded := loadFile("{model_file}");',
        "loadErr := getErrorString();",
        f"check := checkModel({model_name});",
        "checkErr := getErrorString();",
        f"build := buildModel({model_name});",
        "buildErr := getErrorString();",
        "exe := build[1];",
        "echo(true);",
        *(f'print("SPECALIVE_{marker}=" + {value} + "\\n");' for marker, value in prints),
        'print("SPECALIVE_END\\n");',
        "",
    ])


def parse_messages(text: str) -> list[OmcMessage]:
    """omc error text as messages; a line that starts no message continues the previous one."""
    found: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        m = _MESSAGE_RE.match(line)
        if m:
            found.append({"severity": m["severity"], "message": m["message"].strip(),
                          "file": m["file"], "line": int(m["line"]) if m["line"] else None,
                          "column": int(m["col"]) if m["col"] else None, "text": line})
        elif found and line:
            found[-1]["message"] += "\n" + line
            found[-1]["text"] += "\n" + line
    return [OmcMessage(**f) for f in found]


def _compile_fields(stdout: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for name, nxt in zip(_COMPILE_MARKERS, _COMPILE_MARKERS[1:]):
        m = re.search(rf"SPECALIVE_{name}=(.*?)\n?SPECALIVE_{nxt}\b", stdout, re.DOTALL)
        if m is None:
            return None
        values[name] = m.group(1).strip()
    return values


def interpret_compile(stdout: str) -> tuple[str, str, list[OmcMessage]]:
    """(status, one-line detail, every omc message) from a compile script's output."""
    f = _compile_fields(stdout)
    if f is None:
        tail = stdout.strip()[-300:] or "(no output)"
        return FAILED, f"unexpected omc output: {tail}", parse_messages(stdout)
    messages = [m for key in _ERROR_KEYS for m in parse_messages(f[key])]
    first_error = next((m.message for m in messages if m.severity == "Error"), None)
    if f["MSL"] != "true":
        return (NOT_RUN, "the Modelica Standard Library (MSL) did not load: "
                f"{first_error or 'no message'}", messages)
    if f["FILE"] != "true":
        return FAILED, f"the model file did not load: {first_error or 'no message'}", messages
    if first_error is not None:
        return FAILED, first_error.splitlines()[0], messages
    if "completed successfully" not in f["CHECK"]:
        return FAILED, f"checkModel did not complete: {f['CHECK'] or 'no message'}", messages
    if not f["EXE"]:
        return FAILED, "buildModel produced no executable", messages
    return OK, f["CHECK"].splitlines()[0], messages


def compile_command(settings: Settings, work_dir: Path) -> str:
    """The one line that reproduces a compile: change to the build folder and run the script."""
    omc_cmd = subprocess.list2cmdline([settings.omc_path, COMPILE_SCRIPT])
    return f'cd "{Path(work_dir).resolve()}" && {omc_cmd}'


def compile_model(settings: Settings, mo_path: Path, model_name: str,
                  work_dir: Path) -> CompileResult:
    """Check and build `model_name` from `mo_path` in `work_dir`, which receives compile.mos and
    omc's build files. A missing or failing omc is a result, never an exception."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    rel = Path(os.path.relpath(Path(mo_path).resolve(), work_dir.resolve())).as_posix()
    script = compile_script(rel, model_name, settings.msl_version)
    (work_dir / COMPILE_SCRIPT).write_text(script, encoding="utf-8", newline="\n")
    run = run_tool([settings.omc_path, COMPILE_SCRIPT], timeout=settings.omc_timeout_s,
                   cwd=work_dir)
    if run.returncode is None:
        return CompileResult(NOT_RUN, model_name, (), f"omc did not run: {run.stderr.strip()}",
                             None, run)
    status, detail, messages = interpret_compile(run.stdout)
    if status == OK and not run.ok:
        status, detail = FAILED, f"omc exited with {run.returncode}: {run.stderr.strip()}"
    return CompileResult(status, model_name, tuple(messages), detail,
                         compile_command(settings, work_dir), run)
