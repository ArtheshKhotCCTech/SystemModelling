# Purpose: runs OpenModelica `omc`: the toolchain probe (1); compile, checkModel and buildModel on
# one file with omc's `[file:line:col] Error:` messages parsed (6); simulate, a model file or MSL
# class to CSV, an assert that stops the run read as data with its time and message (7). omc
# reports most failures through getErrorString(), not its exit code, so results are printed behind
# SPECALIVE_* markers and any "Error:" text is failure. Each result carries its reproducing command.
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


# --- simulate (phase 7) --------------------------------------------------------------------

SIMULATE_SCRIPT = "simulate.mos"
_SIMULATE_MARKERS = ("MSL", "FILE", "MSLERR", "LOADERR", "SIMERR", "MESSAGES", "END")
_SIMULATE_ERROR_KEYS = ("MSLERR", "LOADERR", "SIMERR")
# The runtime prints a violated assert as "...violated at time 13.000000" and then, on its own
# line, `((condition)) --> "message"`. The last one is the assert that stopped the run; it may be
# reported first at the event where it became false, then again at the step where the run threw.
_ASSERT_RE = re.compile(r"violated at time\s+(?P<time>[-+0-9.eE]+)\s*\n.*?-->\s*\"(?P<msg>.*)\"")


@dataclass(frozen=True)
class AssertionStop:
    time: float  # when the stopping assert was first reported violated
    message: str  # the assert's message string, as the model wrote it
    stopped_at: float | None = None  # when the run threw, if later


@dataclass(frozen=True)
class SimulateResult:
    status: str  # OK | FAILED | NOT_RUN
    model_name: str
    result_file: Path | None  # omc's CSV, also when an assert stopped the run part way
    messages: tuple[OmcMessage, ...]
    log: str  # the simulation runtime's messages, verbatim
    detail: str
    command: str | None  # what reproduces this simulation; None if omc did not run
    assertion: AssertionStop | None = None
    run: ToolResult | None = None

    @property
    def ok(self) -> bool:
        return self.status == OK


def simulate_script(model_file: str | None, model_name: str, msl_version: str) -> str:
    """Load the pinned MSL (and `model_file`, if any) and simulate `model_name` to CSV. Stop time
    and interval are left to the model's experiment annotation (FR-07 requirement 1)."""
    load = ([f'fileLoaded := loadFile("{model_file}");', "loadErr := getErrorString();"]
            if model_file is not None else ["fileLoaded := true;", 'loadErr := "";'])
    prints = [("MSL", "String(mslLoaded)"), ("FILE", "String(fileLoaded)"), ("MSLERR", "mslErr"),
              ("LOADERR", "loadErr"), ("SIMERR", "simErr"), ("MESSAGES", "simMessages")]
    return "\n".join([
        "echo(false);",
        f'mslLoaded := loadModel(Modelica, {{"{msl_version}"}});',
        "mslErr := getErrorString();",
        *load,
        f'res := simulate({model_name}, outputFormat="csv");',
        "simErr := getErrorString();",
        "simMessages := res.messages;",
        "echo(true);",
        *(f'print("SPECALIVE_{marker}=" + {value} + "\n");' for marker, value in prints),
        'print("SPECALIVE_END\n");',
        "",
    ])


def parse_assertion(log: str) -> AssertionStop | None:
    """The assert that stopped a run, from the runtime's messages; None if none did."""
    found = list(_ASSERT_RE.finditer(log))
    if not found:
        return None
    last = found[-1]
    first = next(m for m in found if m["msg"] == last["msg"])
    return AssertionStop(float(first["time"]), last["msg"], float(last["time"]))


def _simulate_fields(stdout: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for name, nxt in zip(_SIMULATE_MARKERS, _SIMULATE_MARKERS[1:]):
        m = re.search(rf"SPECALIVE_{name}=(.*?)\n?SPECALIVE_{nxt}\b", stdout, re.DOTALL)
        if m is None:
            return None
        values[name] = m.group(1).strip()
    return values


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no message"


def interpret_simulate(stdout: str) -> tuple[str, str, list[OmcMessage], str,
                                             AssertionStop | None]:
    """(status, one-line detail, omc messages, runtime log, the assert that stopped the run)."""
    f = _simulate_fields(stdout)
    if f is None:
        tail = stdout.strip()[-300:] or "(no output)"
        return FAILED, f"unexpected omc output: {tail}", parse_messages(stdout), "", None
    messages = [m for key in _SIMULATE_ERROR_KEYS for m in parse_messages(f[key])]
    first_error = next((m.message for m in messages if m.severity == "Error"), None)
    log = f["MESSAGES"]
    if f["MSL"] != "true":
        return (NOT_RUN, "the Modelica Standard Library (MSL) did not load: "
                f"{first_error or 'no message'}", messages, log, None)
    if f["FILE"] != "true":
        return (FAILED, f"the model file did not load: {first_error or 'no message'}", messages,
                log, None)
    assertion = parse_assertion(log)
    if assertion is not None:
        return (FAILED, f"stopped by an assertion violated at time {assertion.time:g} s: "
                f"{assertion.message}", messages, log, assertion)
    if first_error is not None:
        return FAILED, first_error.splitlines()[0], messages, log, None
    if "finished successfully" not in log:
        return FAILED, f"the simulation did not finish: {_last_line(log)}", messages, log, None
    return OK, _last_line(log), messages, log, None


def simulate_command(settings: Settings, work_dir: Path) -> str:
    omc_cmd = subprocess.list2cmdline([settings.omc_path, SIMULATE_SCRIPT])
    return f'cd "{Path(work_dir).resolve()}" && {omc_cmd}'


def simulate(settings: Settings, model_name: str, work_dir: Path,
             mo_path: Path | None = None) -> SimulateResult:
    """Simulate `model_name` (from `mo_path`, or an MSL class when None) in `work_dir`, which
    receives simulate.mos, the build files and `<model>_res.csv`. A missing omc is NOT RUN; a
    failure, a timeout or an assert stop is FAILED; none of them raises."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    rel = (Path(os.path.relpath(Path(mo_path).resolve(), work_dir.resolve())).as_posix()
           if mo_path is not None else None)
    (work_dir / SIMULATE_SCRIPT).write_text(simulate_script(rel, model_name, settings.msl_version),
                                            encoding="utf-8", newline="\n")
    result_file = work_dir / f"{model_name}_res.csv"
    result_file.unlink(missing_ok=True)
    run = run_tool([settings.omc_path, SIMULATE_SCRIPT], timeout=settings.omc_timeout_s,
                   cwd=work_dir)
    command = simulate_command(settings, work_dir)
    if run.returncode is None:
        reason = run.stderr.strip()
        if reason.startswith("timed out"):
            return SimulateResult(FAILED, model_name, None, (), "", f"simulation {reason}",
                                  command, None, run)
        return SimulateResult(NOT_RUN, model_name, None, (), "", f"omc did not run: {reason}",
                              None, None, run)
    status, detail, messages, log, assertion = interpret_simulate(run.stdout)
    if status == OK and not run.ok:
        status, detail = FAILED, f"omc exited with {run.returncode}: {run.stderr.strip()}"
    if status == OK and not result_file.is_file():
        status, detail = FAILED, f"omc reported success but wrote no {result_file.name}"
    return SimulateResult(status, model_name, result_file if result_file.is_file() else None,
                          tuple(messages), log, detail, command, assertion, run)
