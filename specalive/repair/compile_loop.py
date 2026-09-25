# Purpose: the compile-and-repair loop (FR-06 requirements 11-14). Compile; if omc reports errors,
# apply the deterministic fixes the error text calls for (missing import, keyword used as a name,
# unit spelling), then at most `repair_attempts` LLM repairs. Every candidate must keep the
# topology — the multiset of (class, IR id) instances and the set of connect() pairs, both read
# by IR id so a rename does not count — or it is rejected (R-MO-4). Every attempt is kept on disk
# and logged with its diff (R-MO-5); a loop that gives up reports FAILED, never a compile it lacks.
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, Field

from specalive.config import Settings
from specalive.core.catalogue import Catalogue
from specalive.core.ir import SystemModel
from specalive.generate.modelica import SYSTEM_CLASS
from specalive.generate.modelica_text import KEYWORDS
from specalive.llm.client import LLMError
from specalive.toolchain import omc
from specalive.toolchain.omc import CompileResult, OmcMessage

__all__ = ["OmcMessage", "run_compile_loop", "topology", "LoopResult", "Attempt"]

REPAIR_LOG = "repair_log.json"
COMPILE_LOG = "compile.log"
REPAIRED_FILE = "model.repaired.mo"
ATTEMPTS_DIR = "attempts"
BUILD_DIR = "build"
OK, REPAIRED, FAILED, NOT_RUN = "ok", "repaired", "FAILED", "NOT RUN"

# Import aliases a deterministic fix may add; anything else is left to the LLM or the user.
KNOWN_IMPORTS = {"SI": "Modelica.Units.SI", "NonSI": "Modelica.Units.NonSI",
                 "Constants": "Modelica.Constants"}
_PARSER_ERRORS = ("No viable alternative", "Parser error", "Missing token", "Unexpected token",
                  "mismatched input")
_PREFIXES = r"(?:(?:parameter|constant|discrete|input|output|flow|inner|outer)\s+)*"
_DECLARATION = re.compile(rf"^\s*{_PREFIXES}([A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)\s*[(\"]")
_INSTANCE = re.compile(r'^\s*([A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)\b.*"[^"]*\[IR ([a-z_][a-z0-9_]*)\]"'
                       r"\s*;\s*$")
_CONNECT = re.compile(r"connect\(\s*([A-Za-z_]\w*)\.([A-Za-z_][\w\[\]]*)\s*,"
                      r"\s*([A-Za-z_]\w*)\.([A-Za-z_][\w\[\]]*)\s*\)")
_NOT_INSTANCES = {"parameter", "constant", "connect", "import", "extends", "type"}

REPAIR_PROMPT = """You repair a Modelica model that fails to compile under OpenModelica with the
Modelica Standard Library 4.0.0 loaded. Fix only what the compiler errors point at: syntax,
missing imports, misspelled names or unit strings, connector names in connect() equations.
Never add, remove or change the class of a component instance, never add or remove a connect()
equation, and keep every description string that ends in [IR <id>]: a repair that changes the
model's components or connections is rejected and wasted. Do not invent Modelica Standard
Library classes; use only classes already in the file or ones you are certain exist in MSL 4.0.0.
Return the complete revised file in `modelica` and one or two sentences in `explanation`."""


class RepairReply(BaseModel):
    modelica: str = Field(description="the complete revised model.mo text")
    explanation: str = Field(description="what was changed and why, in one or two sentences")


M = TypeVar("M", bound=BaseModel)


class CompletionClient(Protocol):
    def complete(self, *, prompt: str, input_text: str, schema: type[M]) -> M: ...


Compiler = Callable[[Path, str, Path], CompileResult]


# --- topology ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Topology:
    instances: tuple[tuple[str, str], ...]  # sorted multiset of (class, IR id)
    connections: frozenset[frozenset[tuple[str, str]]]  # {(IR id, connector), (IR id, connector)}


def _system_lines(text: str) -> list[str]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if re.match(rf"^\s*model\s+{SYSTEM_CLASS}\b", line)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines))
                if re.match(rf"^\s*end\s+{SYSTEM_CLASS}\s*;", lines[i])), len(lines))
    return lines[start + 1:end]


def topology(text: str) -> Topology:
    """What a repair may not change, read from the System model by IR id."""
    lines = _system_lines(text)
    instances, ir_of = [], {}
    for line in lines:
        m = _INSTANCE.match(line)
        if m and m.group(1) not in _NOT_INSTANCES and "connect(" not in line:
            instances.append((m.group(1), m.group(3)))
            ir_of[m.group(2)] = m.group(3)
    connections = set()
    for m in _CONNECT.finditer("\n".join(lines)):
        a = (ir_of.get(m.group(1), f"?{m.group(1)}"), m.group(2))
        b = (ir_of.get(m.group(3), f"?{m.group(3)}"), m.group(4))
        connections.add(frozenset({a, b}))
    return Topology(tuple(sorted(instances)), frozenset(connections))


def topology_diff(before: Topology, after: Topology) -> list[str]:
    changes = []
    old, new = Counter(before.instances), Counter(after.instances)
    changes += [f"component removed: {cls} [IR {ir}]" for cls, ir in sorted(old - new)]
    changes += [f"component added: {cls} [IR {ir}]" for cls, ir in sorted(new - old)]

    def show(pair):
        return " <-> ".join(f"{ir}.{c}" for ir, c in sorted(pair))

    changes += [f"connection removed: {show(p)}" for p in sorted(before.connections
                                                                  - after.connections, key=show)]
    changes += [f"connection added: {show(p)}" for p in sorted(after.connections
                                                                - before.connections, key=show)]
    return changes


def model_name_of(text: str) -> str:
    m = re.search(r"^package\s+([A-Za-z_]\w*)", text, re.MULTILINE)
    if m is None:
        raise ValueError("the file declares no top-level package")
    return f"{m.group(1)}.{SYSTEM_CLASS}"


# --- deterministic fixes ----------------------------------------------------------------------

def fix_missing_import(text: str, messages: list[OmcMessage]) -> str | None:
    """`Class SI.X not found in scope C`: add `import SI = Modelica.Units.SI;` to class C."""
    lines, changed = text.split("\n"), False
    for msg in messages:
        m = re.search(r"Class ([A-Za-z_]\w*)\.[\w.]+ not found in scope ([\w.]*\w)", msg.message)
        if msg.severity != "Error" or m is None or m.group(1) not in KNOWN_IMPORTS:
            continue
        alias, scope = m.group(1), m.group(2).split(".")[-1]
        header = re.compile(r"^(\s*)(?:(?:partial|encapsulated)\s+)*"
                            rf"(?:model|block|class|package|connector|record)\s+{scope}\b")
        for i, line in enumerate(lines):
            h = header.match(line)
            if h is None:
                continue
            statement = f"{h.group(1)}  import {alias} = {KNOWN_IMPORTS[alias]};"
            if i + 1 < len(lines) and lines[i + 1] == statement:
                break
            lines.insert(i + 1, statement)
            changed = True
            break
    return "\n".join(lines) if changed else None


def fix_reserved_name(text: str, messages: list[OmcMessage]) -> str | None:
    """A parser error with a component named by a keyword: rename it `<keyword>_`."""
    if not any(m.severity == "Error" and m.message.startswith(_PARSER_ERRORS) for m in messages):
        return None
    names = set()
    for line in text.split("\n"):
        m = _DECLARATION.match(line)
        if m and m.group(1) not in KEYWORDS and m.group(2) in KEYWORDS:
            names.add((m.group(1), m.group(2)))
    if not names:
        return None
    for cls, name in sorted(names):
        text = re.sub(rf"^(\s*{_PREFIXES}{re.escape(cls)}\s+){name}(?=\s*[(\"])", rf"\g<1>{name}_",
                      text, flags=re.MULTILINE)
        text = re.sub(rf"(?<![\w.\"]){name}\.(?=[A-Za-z_])", f"{name}_.", text)
    return text


def fix_unit_spelling(text: str, messages: list[OmcMessage]) -> str | None:
    """`Invalid unit expression 'm^2'`: write the unit the way Modelica spells it (m2)."""
    new = text
    for msg in messages:
        m = re.search(r"Invalid unit expression '([^']+)'", msg.message)
        if m is None:
            continue
        bad = m.group(1)
        good = (bad.replace("^", "").replace("**", "").replace("²", "2").replace("³", "3")
                .replace(" ", ""))
        if good != bad:
            new = new.replace(f'unit = "{bad}"', f'unit = "{good}"')
    return new if new != text else None


DETERMINISTIC_FIXES: tuple[tuple[str, Callable[[str, list[OmcMessage]], str | None]], ...] = (
    ("missing_import", fix_missing_import),
    ("reserved_name", fix_reserved_name),
    ("unit_spelling", fix_unit_spelling),
)


def apply_deterministic(text: str, messages: list[OmcMessage]) -> tuple[str, list[str]]:
    applied = []
    for name, fix in DETERMINISTIC_FIXES:
        fixed = fix(text, messages)
        if fixed is not None and fixed != text:
            text, applied = fixed, applied + [name]
    return text, applied


# --- the loop ---------------------------------------------------------------------------------

@dataclass
class Attempt:
    number: int
    kind: str  # generated | deterministic | llm
    file: str  # relative to the run folder; empty when no candidate was produced
    errors_in: list[str]
    change: str  # unified diff from the text the attempt started from
    fixes: list[str]  # deterministic fixes applied
    explanation: str
    topology_held: bool
    topology_changes: list[str]
    result: str  # ok | failed | rejected | error | NOT RUN
    errors_out: list[str]


@dataclass(frozen=True)
class LoopResult:
    status: str  # OK | REPAIRED | FAILED | NOT_RUN
    model_name: str
    delivered: Path | None
    command: str | None
    detail: str
    errors: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)


def ir_summary(model: SystemModel, catalogue: Catalogue) -> str:
    """What the repair LLM is told about the design it must not change."""
    lines = [f"system: {model.name}", "parts (IR id, kind, Modelica class):"]
    for part in sorted(model.parts, key=lambda p: p.id):
        cls = (catalogue.entry(part.kind).modelica.class_ if part.kind in catalogue else None)
        lines.append(f"  {part.id} ({part.kind}) -> {cls or 'generated controller'}")
    lines.append("connections (IR id: from port -> to port):")
    lines += [f"  {c.id}: {c.from_port} -> {c.to_port}"
              for c in sorted(model.connections, key=lambda c: c.id)]
    return "\n".join(lines)


def _errors(result: CompileResult) -> list[str]:
    texts = [m.text for m in result.errors]
    return texts or ([result.detail] if not result.ok else [])


def _label(result: CompileResult) -> str:
    return {omc.OK: "ok", omc.NOT_RUN: NOT_RUN}.get(result.status, "failed")


def _diff(before: str, after: str, name: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True),
                                        after.splitlines(keepends=True),
                                        fromfile="before", tofile=name))


class _Loop:
    def __init__(self, mo_path: Path, out_dir: Path, settings: Settings,
                 llm: CompletionClient | None, summary: str, compiler: Compiler) -> None:
        self.mo_path, self.out = Path(mo_path), Path(out_dir)
        self.settings, self.llm, self.summary, self.compile = settings, llm, summary, compiler
        self.attempts: list[Attempt] = []
        self.attempts_dir = self.out / ATTEMPTS_DIR
        self.build = self.out / BUILD_DIR

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.out.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _clear_previous(self) -> None:
        for stale in sorted(self.attempts_dir.glob("*.mo")):
            stale.unlink()
        (self.out / REPAIRED_FILE).unlink(missing_ok=True)

    def _candidate(self, kind: str, text: str) -> Path:
        self.attempts_dir.mkdir(parents=True, exist_ok=True)
        path = self.attempts_dir / f"attempt_{len(self.attempts)}_{kind}.mo"
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def _input(self, text: str, result: CompileResult, feedback: str) -> str:
        errors = "\n".join(_errors(result))
        return (f"IR summary (the design; do not change it):\n{self.summary or '(not available)'}"
                f"\n\nCompiler errors:\n{errors}\n\n{feedback}Current model.mo:\n{text}")

    def run(self) -> LoopResult:
        self._clear_previous()
        original = self.mo_path.read_text(encoding="utf-8")
        name = model_name_of(original)
        baseline = topology(original)
        result = self.compile(self.mo_path, name, self.build)
        self.attempts.append(Attempt(0, "generated", self.rel(self.mo_path), [], "", [], "", True,
                                     [], _label(result), _errors(result)))
        if result.status == omc.NOT_RUN:
            return self._finish(NOT_RUN, name, None, result, result.detail)
        if result.ok:
            return self._finish(OK, name, self.mo_path, result, result.detail)
        text = original

        fixed, applied = apply_deterministic(text, list(result.messages))
        if applied:
            outcome = self._try(fixed, text, result, "deterministic", baseline, fixes=applied)
            if outcome is not None:
                text, result = outcome
                if result.status == omc.NOT_RUN:
                    return self._finish(NOT_RUN, name, None, result, result.detail)
                if result.ok:
                    return self._deliver(name, text)

        detail = "no LLM is available for repair; only deterministic fixes were tried"
        feedback = ""
        for _ in range(self.settings.repair_attempts if self.llm is not None else 0):
            try:
                reply = self.llm.complete(prompt=REPAIR_PROMPT,
                                          input_text=self._input(text, result, feedback),
                                          schema=RepairReply)
            except LLMError as exc:
                self.attempts.append(Attempt(len(self.attempts), "llm", "", _errors(result), "",
                                             [], str(exc), True, [], "error", []))
                detail = f"the LLM repair call failed: {exc}"
                break
            candidate = reply.modelica if reply.modelica.endswith("\n") else reply.modelica + "\n"
            outcome = self._try(candidate, text, result, "llm", baseline,
                                explanation=reply.explanation)
            if outcome is None:
                changes = self.attempts[-1].topology_changes
                feedback = ("Your previous candidate was rejected because it changed the "
                            f"model's components or connections ({'; '.join(changes)}). Keep "
                            "every component and every connect().\n\n")
                detail = "every LLM repair was rejected or failed"
                continue
            text, result = outcome
            feedback = ""
            if result.status == omc.NOT_RUN:
                return self._finish(NOT_RUN, name, None, result, result.detail)
            if result.ok:
                return self._deliver(name, text)
            detail = f"no clean compile after {self.settings.repair_attempts} LLM repair(s)"
        return self._finish(FAILED, name, None, result, detail)

    def _try(self, candidate: str, before: str, result: CompileResult, kind: str,
             baseline: Topology, fixes: list[str] | None = None,
             explanation: str = "") -> tuple[str, CompileResult] | None:
        """Write, topology-check and compile one candidate; None when it is rejected."""
        path = self._candidate(kind, candidate)
        changes = topology_diff(baseline, topology(candidate))
        attempt = Attempt(len(self.attempts), kind, self.rel(path), _errors(result),
                          _diff(before, candidate, self.rel(path)), fixes or [], explanation,
                          not changes, changes, "rejected", [])
        self.attempts.append(attempt)
        if changes:
            return None
        compiled = self.compile(path, model_name_of(candidate), self.build)
        attempt.result, attempt.errors_out = _label(compiled), _errors(compiled)
        return candidate, compiled

    def _deliver(self, name: str, text: str) -> LoopResult:
        """Write model.repaired.mo and compile it once more, so the printed command reproduces
        the delivered file itself, not an attempt copy."""
        target = self.out / REPAIRED_FILE
        target.write_text(text, encoding="utf-8", newline="\n")
        final = self.compile(target, name, self.build)
        if final.ok:
            return self._finish(REPAIRED, name, target, final, final.detail)
        return self._finish(FAILED, name, None, final,
                            f"the repaired file did not compile again: {final.detail}")

    def _finish(self, status: str, name: str, delivered: Path | None, last: CompileResult,
                detail: str) -> LoopResult:
        result = LoopResult(status, name, delivered, last.command, detail,
                            [] if status in (OK, REPAIRED) else _errors(last), self.attempts)
        self._write_logs(result, last)
        return result

    def _write_logs(self, result: LoopResult, last: CompileResult) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        delivered = self.rel(result.delivered) if result.delivered else None
        log = {"status": result.status, "model": result.model_name, "delivered": delivered,
               "command": result.command, "detail": result.detail, "errors": result.errors,
               "attempts": [asdict(a) for a in result.attempts]}
        (self.out / REPAIR_LOG).write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
        lines = [f"Modelica compile: {result.status}", f"model: {result.model_name}",
                 f"delivered: {delivered or 'none'}",
                 f"command: {result.command or 'none (omc did not run)'}",
                 f"detail: {result.detail}", "", "attempts:"]
        for a in result.attempts:
            held = "" if a.topology_held else " (topology changed)"
            lines.append(f"  {a.number} {a.kind} {a.file or '-'}: {a.result}{held}")
        lines += ["", "omc messages from the last compile:"]
        lines += [f"  {m.text}" for m in last.messages] or ["  (none)"]
        (self.out / COMPILE_LOG).write_text("\n".join(lines) + "\n", encoding="utf-8",
                                            newline="\n")


def run_compile_loop(mo_path: Path, out_dir: Path, *, settings: Settings,
                     llm: CompletionClient | None = None, ir_summary: str = "",
                     compiler: Compiler | None = None) -> LoopResult:
    """Compile `mo_path`, repairing it if needed; writes compile.log, repair_log.json, every
    attempt under attempts/, and model.repaired.mo when a repair succeeded."""
    compile_ = compiler or (lambda path, name, work: omc.compile_model(settings, path, name, work))
    return _Loop(mo_path, out_dir, settings, llm, ir_summary, compile_).run()
