# Purpose: validates SysML v2 text with the OMG SysML v2 Pilot Implementation, the validator
# chosen in phase 1. The Pilot has no batch CLI, so its interactive shell is driven over stdin:
# the model goes in a `%` ... `%` block, then `%exit`. The shell exits 0 even when the model is
# wrong, so the verdict comes from parsing its `ERROR:` / `WARNING:` lines, not the exit code.
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from specalive.config import Settings
from specalive.toolchain.process import ProbeResult, ToolResult, run_tool

MAIN_CLASS = "org.omg.sysml.interactive.SysMLInteractive"
_ISSUE_RE = re.compile(
    r"(?P<sev>ERROR|WARNING):(?P<msg>.*?) \(\d+\.sysml line : (?P<line>\d+) column : (?P<col>\d+)\)")
# The shell echoes each parsed root element, e.g. "1> Package SpecAliveProbe (uuid)".
_ROOT_RE = re.compile(r"^\d+> \w+ \S+ \([0-9a-f-]+\)", re.MULTILINE)


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    message: str
    line: int
    column: int


@dataclass(frozen=True)
class Validation:
    ok: bool
    detail: str
    issues: tuple[Issue, ...] = ()
    run: ToolResult | None = None
    errors: tuple[Issue, ...] = field(init=False)
    warnings: tuple[Issue, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(i for i in self.issues if i.severity == "error"))
        object.__setattr__(self, "warnings",
                           tuple(i for i in self.issues if i.severity == "warning"))


def parse_issues(stdout: str) -> list[Issue]:
    return [Issue(m["sev"].lower(), m["msg"].strip(), int(m["line"]), int(m["col"]))
            for m in _ISSUE_RE.finditer(stdout)]


def repl_input(text: str) -> str:
    return f"%\n{text.rstrip()}\n%\n%exit\n"


def interpret(run: ToolResult) -> Validation:
    issues = tuple(parse_issues(run.stdout))
    errors = [i for i in issues if i.severity == "error"]
    if not run.ok:
        return Validation(False, f"validator did not run: {run.stderr.strip()}", issues, run)
    if "Exception in thread" in run.stderr or "Exception in thread" in run.stdout:
        first = next(line for line in (run.stderr + run.stdout).splitlines()
                     if "Exception in thread" in line)
        return Validation(False, f"validator crashed: {first.strip()}", issues, run)
    if errors:
        e = errors[0]
        return Validation(False, f"{len(errors)} error(s); first at line {e.line}:{e.column}: "
                                 f"{e.message}", issues, run)
    if not _ROOT_RE.search(run.stdout):
        return Validation(False, "validator parsed no model element", issues, run)
    warnings = len(issues) - len(errors)
    return Validation(True, f"parsed with 0 errors, {warnings} warning(s)", issues, run)


def find_jar(settings: Settings) -> Path | None:
    home = settings.sysml_validator_home
    jars = sorted(home.glob("*-all.jar")) if home.is_dir() else []
    return jars[-1] if jars else None


def validate_text(settings: Settings, text: str) -> Validation:
    home = settings.sysml_validator_home
    jar = find_jar(settings)
    library = home / "sysml.library"
    if jar is None or not library.is_dir():
        return Validation(False, f"SysML v2 Pilot Implementation not found in {home} "
                                 "(set SPECALIVE_SYSML_VALIDATOR)")
    # The Pilot mis-resolves a relative library path containing spaces; always pass it absolute.
    command = [settings.java_path, "-cp", str(jar.resolve()), MAIN_CLASS, str(library.resolve())]
    run = run_tool(command, timeout=settings.validator_timeout_s, stdin_text=repl_input(text))
    return interpret(run)


def validate_file(settings: Settings, path: Path) -> Validation:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return Validation(False, f"cannot read {path}: {exc}")
    return validate_text(settings, text)


def probe(settings: Settings, fixture: Path) -> ProbeResult:
    v = validate_file(settings, fixture)
    detail = f"{fixture.name}: {v.detail}"
    return ProbeResult(v.ok, detail, (v.run,) if v.run else ())
