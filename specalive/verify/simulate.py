# Purpose: runs the compiled model and says which result variable stands for which IR element. The
# model is the one the compile stage delivered (repair_log.json), simulated by omc to
# sim/result.csv and loaded as a Trace. The IR id -> variable map is read from the `[IR id]`
# description strings the generator writes on every instance and controller connector, plus the
# catalogue's connector names, so verify never imports generate/ and never guesses a name.
from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from specalive.config import Settings
from specalive.core.catalogue import Catalogue, UnknownKind
from specalive.core.ir import SystemModel
from specalive.toolchain import omc

SIM_DIR = "sim"
RESULT_FILE = "result.csv"
REPAIR_LOG = "repair_log.json"
COMPILED = ("ok", "repaired")  # repair_log statuses that deliver a model


class VerifyInputError(ValueError):
    """Something verify reads is missing or unusable: an input problem, not a failed check."""


@dataclass(frozen=True)
class ModelChoice:
    path: Path | None  # None: an MSL class, loaded with the library
    name: str


@dataclass(frozen=True)
class Trace:
    """A simulation result or any time table: rows in time order, event instants appear twice
    (the value before and after the event)."""

    times: list[float]
    values: dict[str, list[float]]

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.values)


@dataclass(frozen=True)
class Simulation:
    result: omc.SimulateResult
    model: ModelChoice
    trace: Trace | None
    result_csv: Path | None

    @property
    def status(self) -> str:
        return self.result.status


@dataclass(frozen=True)
class StateVariable:
    machine: str
    variable: str
    states: tuple[str, ...]  # enumeration value n is states[n - 1]


@dataclass
class VariableMap:
    ports: dict[str, str] = field(default_factory=dict)  # IR port id -> result variable
    states: dict[str, StateVariable] = field(default_factory=dict)  # machine id -> its state
    notes: list[str] = field(default_factory=list)  # what could not be mapped, and why


def choose_model(run_dir: Path) -> ModelChoice:
    """The model the compile stage delivered in `run_dir`, with the name omc compiled."""
    log_path = Path(run_dir) / REPAIR_LOG
    if not log_path.is_file():
        raise VerifyInputError(f"{log_path} not found; run specalive compile first")
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerifyInputError(f"{log_path} is unreadable: {exc}") from None
    if log.get("status") not in COMPILED:
        raise VerifyInputError(f"the model did not compile (compile status {log.get('status')}); "
                               "fix the compile before verifying")
    path = Path(run_dir) / str(log.get("delivered"))
    if not log.get("delivered") or not path.is_file():
        raise VerifyInputError(f"the delivered model {path} is missing")
    return ModelChoice(path, str(log["model"]))


def load_result(path: Path) -> Trace:
    """A CSV whose first column is time and whose other columns are numbers."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
    except OSError as exc:
        raise VerifyInputError(f"cannot read {path}: {exc.strerror or exc}") from None
    if len(rows) < 2 or len(rows[0]) < 1:
        raise VerifyInputError(f"{path} holds no result rows")
    header = [h.strip() for h in rows[0]]
    try:
        body = [[float(cell) for cell in row] for row in rows[1:] if row]
    except ValueError as exc:
        raise VerifyInputError(f"{path} has a non-numeric value: {exc}") from None
    return Trace([row[0] for row in body],
                 {name: [row[i] for row in body] for i, name in enumerate(header) if i > 0})


def run_simulation(settings: Settings, model: ModelChoice, run_dir: Path) -> Simulation:
    """Simulate in `run_dir`/sim and copy omc's result to sim/result.csv, also when an assert
    stopped the run part way (the partial trace is what shows when it stopped)."""
    work = Path(run_dir) / SIM_DIR
    result = omc.simulate(settings, model.name, work, model.path)
    target = work / RESULT_FILE
    target.unlink(missing_ok=True)
    if result.result_file is None:
        return Simulation(result, model, None, None)
    shutil.copyfile(result.result_file, target)
    try:
        trace = load_result(target)
    except VerifyInputError:
        return Simulation(result, model, None, target)
    return Simulation(result, model, trace, target)


# --- IR id -> result variable --------------------------------------------------------------

_CLASS_START = re.compile(r"^\s*(?:partial\s+)?(?:model|block)\s+(\w+)\b(?:\s*\"(.*)\")?")
_CLASS_END = re.compile(r"^\s*end\s+(\w+)\s*;")
_DECL = re.compile(r"^\s*([A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)(?:\[[^\]]*\])?(?:\(.*\))?\s*"
                   r"(?:\"((?:[^\"\\]|\\.)*)\")?\s*;\s*$")
_IR_TAG = re.compile(r"\[IR (\w+)\]\s*$")
# a generated declaration may end with its diagram placement: graphics, stripped before reading
_TRAILING_ANNOTATION = re.compile(r"\s+annotation\s*\(.*\)\s*;\s*$")
_ENUM = re.compile(r"type\s+(\w+)\s*=\s*enumeration\((.*?)\)\s*;", re.DOTALL)
_LITERAL = re.compile(r"(\w+)\s*(?:\"(?:[^\"\\]|\\.)*\")?\s*(?:,|$)")


@dataclass
class _Class:
    name: str
    description: str
    lines: list[str] = field(default_factory=list)

    def declarations(self) -> list[tuple[str, str, str | None]]:
        """(type, name, IR id or None) for every one-line declaration."""
        found = []
        for line in self.lines:
            m = _DECL.match(_TRAILING_ANNOTATION.sub(";", line))
            if m is None or m[1] in ("parameter", "constant", "connect", "end", "type"):
                continue
            tag = _IR_TAG.search(m[3] or "")
            found.append((m[1], m[2], tag[1] if tag else None))
        return found


def _classes(text: str) -> dict[str, _Class]:
    """Every model/block with the lines directly inside it (nested classes kept apart)."""
    classes: dict[str, _Class] = {}
    stack: list[_Class] = []
    for line in text.splitlines():
        start = _CLASS_START.match(line)
        if start:
            cls = _Class(start[1], start[2] or "")
            classes[cls.name] = cls
            stack.append(cls)
            continue
        end = _CLASS_END.match(line)
        if end and stack and stack[-1].name == end[1]:
            stack.pop()
            continue
        if stack:
            stack[-1].lines.append(line)
    return classes


def _states(cls: _Class, machine_states: list[str]) -> tuple[str, tuple[str, ...]] | str:
    """(state variable, state ids in enumeration order), or why they could not be read."""
    body = "\n".join(cls.lines)
    enum = _ENUM.search(body)
    if enum is None:
        return f"class {cls.name} declares no state enumeration"
    literals = [m[1] for m in _LITERAL.finditer(enum[2].strip())]
    if len(literals) != len(machine_states) or any(
            lit not in (sid, f"{sid}_") for lit, sid in zip(literals, machine_states)):
        return f"class {cls.name}: enumeration {literals} does not follow the IR states"
    variable = next((name for typ, name, _ in cls.declarations() if typ == enum[1]), None)
    if variable is None:
        return f"class {cls.name} declares no variable of type {enum[1]}"
    return variable, tuple(machine_states)


def variable_map(model: SystemModel, catalogue: Catalogue, mo_text: str,
                 model_name: str) -> VariableMap:
    """Which result variable holds each IR port and each state machine's active state."""
    vm = VariableMap()
    classes = _classes(mo_text)
    system = classes.get(model_name.rsplit(".", 1)[-1])
    instances = ({ir_id: name for _, name, ir_id in system.declarations() if ir_id}
                 if system else {})
    controllers = {}
    for cls in classes.values():
        tag = _IR_TAG.search(cls.description)
        if tag:
            controllers[tag[1]] = cls
    owned = {sm.owner: sm for sm in model.state_machines}
    for part in sorted(model.parts, key=lambda p: p.id):
        instance = instances.get(part.id)
        if instance is None:
            vm.notes.append(f"part {part.id}: no instance in the model")
            continue
        sm = owned.get(part.id)
        if sm is not None:
            cls = controllers.get(sm.id)
            if cls is None:
                vm.notes.append(f"state machine {sm.id}: no controller class in the model")
                continue
            connectors = {ir_id: name for _, name, ir_id in cls.declarations() if ir_id}
            for port in part.ports:
                if port.id in connectors:
                    vm.ports[port.id] = f"{instance}.{connectors[port.id]}"
                else:
                    vm.notes.append(f"port {port.id}: no connector in {cls.name}")
            states = _states(cls, [s.id for s in sm.states])
            if isinstance(states, str):
                vm.notes.append(f"state machine {sm.id}: {states}")
            else:
                vm.states[sm.id] = StateVariable(sm.id, f"{instance}.{states[0]}", states[1])
            continue
        try:
            connectors = catalogue.entry(part.kind).modelica.connectors
        except UnknownKind:
            vm.notes.append(f"part {part.id}: kind {part.kind!r} is not in the catalogue")
            continue
        for port in part.ports:
            if port.role in connectors:
                vm.ports[port.id] = f"{instance}.{connectors[port.role]}"
            else:
                vm.notes.append(f"port {port.id}: the catalogue maps no connector for role "
                                f"{port.role!r}")
    return vm
