# Purpose: renders the IR as a SysML v2 textual model (FR-05), deterministically and without any
# LLM. Python turns the IR and the catalogue into a sorted view model — names escaped by ids.py,
# values only from effective parameters, guards translated from the IR expression syntax tree,
# a `doc` with IR id, primary source and ASSUMPTION marks on every element — and Jinja2
# templates (StrictUndefined) only lay it out. Every construct used is pinned by a validated
# fixture under tests/fixtures/sysml/ (R-SYS-5).
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import jinja2
from pydantic import ValidationError

from specalive.core.catalogue import Catalogue
from specalive.core.ids import sysml_name
from specalive.core.ir import (
    HISTORY,
    SYSTEM_OWNER,
    BoolLit,
    BoolOp,
    Call,
    Compare,
    Expr,
    Name,
    Not,
    Number,
    Parameter,
    Part,
    Port,
    StateMachine,
    SystemModel,
    TraceLink,
    expression_names,
    parse_action,
    parse_expression,
)

MODEL_FILE = "model.sysml"
TEMPLATES = Path(__file__).resolve().parent / "templates" / "sysml"
BEHAVIOUR_SUFFIX = "_behaviour"

# SI unit (core/units.py) -> (ISQ value type, SysML unit expression; None for a plain number).
UNIT_TYPES: dict[str, tuple[str, str | None]] = {
    "m": ("LengthValue", "m"),
    "m2": ("AreaValue", "m^2"),
    "m3": ("VolumeValue", "m^3"),
    "s": ("TimeValue", "s"),
    "kg": ("MassValue", "kg"),
    "kg/m3": ("MassDensityValue", "kg/m^3"),
    "kg/s": ("MassFlowRateValue", "kg/s"),
    "m3/s": ("VolumeFlowRateValue", "m^3/s"),
    "1": ("Real", None),
    "kg/kg": ("MassFractionValue", "kg/kg"),
    "Pa": ("PressureValue", "Pa"),
    "K": ("ThermodynamicTemperatureValue", "K"),
    "W": ("PowerValue", "W"),
    "A": ("ElectricCurrentValue", "A"),
    "V": ("ElectricPotentialValue", "V"),
    "Hz": ("FrequencyValue", "Hz"),
    "1/s": ("FrequencyValue", "s^-1"),
}

# IR port domain -> (port def, its one directed item, the item's type).
DOMAIN_PORTS: dict[str, tuple[str, str, str]] = {
    "fluid": ("FluidPort", "volume_flow", "VolumeFlowRateValue"),
    "signal_real": ("RealSignal", "value", "Real"),
    "signal_bool": ("BoolSignal", "value", "Boolean"),
    "event": ("EventSignal", "occurred", "Boolean"),
    "thermal": ("HeatPort", "heat_flow_rate", "HeatFlowRateValue"),
    "electric": ("ElectricPort", "current", "ElectricCurrentValue"),
    "magnetic": ("MagneticPort", "magnetic_flux", "MagneticFluxValue"),
}

_HISTORY_DOC = ["resume target: the state saved by the last save_history (UML shallow history); "
                "SysML v2 has no history pseudostate, so the IR's reserved target is a state here"]
_PRECEDENCE = {"or": 1, "and": 2}
_WHITESPACE = re.compile(r"\s+")


class IRError(ValueError):
    """ir.json is missing, unreadable or fails the IR's own validation."""


class SysmlGenerationError(ValueError):
    """The IR and the catalogue cannot be rendered: an unknown kind, port role or unit."""


# --- view model -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PortDefView:
    name: str
    domain: str
    item: str
    item_type: str


@dataclass(frozen=True)
class DefView:
    name: str
    doc: list[str]
    members: list[str]


@dataclass(frozen=True)
class DocItem:
    """A declaration with a doc body: `<text> { doc }`."""

    text: str
    doc: list[str]


@dataclass(frozen=True)
class StateView:
    name: str
    doc: list[str]
    entry: list[str]


@dataclass(frozen=True)
class RegionView:
    name: str
    doc: list[str]
    initial: str
    states: list[StateView]
    history: list[str]  # doc of the `history` resume state; empty when nothing resumes
    transitions: list[DocItem]


@dataclass(frozen=True)
class StateDefView:
    name: str
    doc: list[str]
    parallel: bool
    declarations: list[str]
    timers: list[DocItem]
    body: RegionView
    regions: list[RegionView]


@dataclass(frozen=True)
class ExhibitView:
    name: str
    definition: str
    doc: list[str]
    bindings: list[str]


@dataclass(frozen=True)
class PartUsageView:
    name: str
    definition: str
    doc: list[str]
    ports: list[DocItem]
    attributes: list[DocItem]
    exhibits: list[ExhibitView]


@dataclass(frozen=True)
class SystemView:
    name: str
    doc: list[str]
    parts: list[PartUsageView]
    attributes: list[DocItem]
    connections: list[DocItem]
    satisfies: list[str]


@dataclass(frozen=True)
class PackageView:
    name: str
    doc: list[str]
    library: list[str]
    port_defs: list[PortDefView]
    part_defs: list[DefView]
    events: list[DocItem]
    state_defs: list[StateDefView]
    requirements: list[DocItem]
    system: SystemView


# --- helpers --------------------------------------------------------------------------------

def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().replace("*/", "* /")


def doc_block(lines: list[str], indent: int) -> str:
    """A SysML `doc` comment; one line stays on one line, more become a starred block."""
    pad = " " * indent
    cleaned = [_clean(line) for line in lines]
    if len(cleaned) == 1:
        return f"{pad}doc /* {cleaned[0]} */"
    body = [f"{pad}doc /* {cleaned[0]}"] + [f"{pad} * {line}" for line in cleaned[1:]]
    return "\n".join(body + [f"{pad} */"])


def environment() -> jinja2.Environment:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)),
                             undefined=jinja2.StrictUndefined, autoescape=False,
                             trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["doc"] = doc_block
    return env


def _number(value: float) -> str:
    text = repr(float(value))
    if text in ("inf", "-inf", "nan"):
        raise SysmlGenerationError(f"value {value!r} has no SysML literal")
    return text


def _path(*segments: str) -> str:
    return ".".join(sysml_name(s) for s in segments)


def _source_line(trace: list[TraceLink]) -> str:
    if not trace:
        return "source: none; the element rests on its assumptions"
    first, more = trace[0], len(trace) - 1
    return f"source: {first.source_id} @ {first.locator}" + (f" (+{more} more)" if more else "")


class _Builder:
    """Everything render_sysml needs, computed once from one IR and one catalogue."""

    def __init__(self, model: SystemModel, catalogue: Catalogue) -> None:
        self.m = model
        self.cat = catalogue
        self.assumption_text = {a.id: a.text for a in model.assumptions}
        self.affected: dict[str, set[str]] = defaultdict(set)
        for a in model.assumptions:
            for eid in a.affects:
                self.affected[eid].add(a.id)
        self.parts = {p.id: p for p in model.parts}
        self.ports: dict[str, tuple[Part, Port]] = {
            port.id: (part, port) for part in model.parts for port in part.ports}
        self.params = {p.id: p for p in model.parameters}
        self.effective: dict[tuple[str, str], Parameter] = {
            (p.owner, p.name): p for p in model.parameters if p.status == "effective"}
        self.library: set[str] = set()
        self._check()

    # --- checks before any template runs ---

    def _check(self) -> None:
        problems: list[str] = []
        ids = {p.id for p in self.m.parts}
        for part in self.m.parts:
            if part.kind not in self.cat:
                problems.append(f"part {part.id!r}: kind {part.kind!r} is not in the catalogue")
                continue
            entry = self.cat.entry(part.kind)
            for role, def_name in sorted(entry.sysml.ports.items()):
                expected = DOMAIN_PORTS[entry.ports[role].domain][0]
                if def_name != expected:
                    problems.append(f"catalogue kind {part.kind!r} port {role!r} maps to "
                                    f"{def_name!r}, but its {entry.ports[role].domain} domain is "
                                    f"written {expected!r}")
            if not entry.dynamic_ports:
                for port in part.ports:
                    if port.role not in entry.ports:
                        problems.append(f"part {part.id!r}: port role {port.role!r} is not "
                                        f"defined for kind {part.kind!r}")
        for sm in self.m.state_machines:
            if any(s.id == HISTORY for s in sm.states):
                problems.append(f"state machine {sm.id!r}: a state is named {HISTORY!r}, the "
                                "reserved resume target")
            if sm.id + BEHAVIOUR_SUFFIX in ids:
                problems.append(f"state machine {sm.id!r}: {sm.id + BEHAVIOUR_SUFFIX!r} is taken")
        if problems:
            raise SysmlGenerationError("cannot render SysML:\n  " + "\n  ".join(problems))

    # --- shared pieces ---

    def assumptions_of(self, eid: str, own: Iterable[str] = ()) -> list[str]:
        ids = sorted(set(own) | self.affected.get(eid, set()))
        return [f"ASSUMPTION {aid}: {self.assumption_text.get(aid, '(unknown assumption)')}"
                for aid in ids]

    def unit_type(self, unit: str, what: str) -> tuple[str, str | None]:
        if unit not in UNIT_TYPES:
            raise SysmlGenerationError(f"unit {unit!r} of {what} has no SysML type "
                                       "(generate/sysml.py UNIT_TYPES)")
        return UNIT_TYPES[unit]

    def value_type(self, p: Parameter) -> str:
        qtype, _ = self.unit_type(p.unit, f"parameter {p.id!r}")
        return qtype + ("[*]" if isinstance(p.value, list) else "")

    def value_text(self, p: Parameter) -> str:
        _, uexpr = self.unit_type(p.unit, f"parameter {p.id!r}")

        def one(v: float) -> str:
            return _number(v) + (f" [{uexpr}]" if uexpr else "")

        if isinstance(p.value, list):
            return "(" + ", ".join(one(v) for v in p.value) + ")"
        return one(p.value)

    def dynamic(self, part: Part) -> bool:
        return self.cat.entry(part.kind).dynamic_ports

    def port_name(self, part: Part, port: Port) -> str:
        return port.id if self.dynamic(part) else port.role

    def port_path(self, port_id: str) -> str:
        part, port = self.ports[port_id]
        return _path(part.id, self.port_name(part, port))

    def port_type(self, port: Port) -> str:
        return ("~" if port.direction == "in" else "") + DOMAIN_PORTS[port.domain][0]

    def param_path(self, p: Parameter) -> str:
        return _path(p.owner, p.name)

    def behaviour(self, sm: StateMachine) -> str:
        return sm.id + BEHAVIOUR_SUFFIX

    # --- package pieces ---

    def port_defs(self) -> list[PortDefView]:
        domains = {port.domain for part in self.m.parts for port in part.ports}
        for kind in {p.kind for p in self.m.parts}:
            domains |= {spec.domain for spec in self.cat.entry(kind).ports.values()}
        views = [PortDefView(DOMAIN_PORTS[d][0], d, DOMAIN_PORTS[d][1], DOMAIN_PORTS[d][2])
                 for d in domains]
        return sorted(views, key=lambda v: v.name)

    def part_defs(self) -> list[DefView]:
        by_def: dict[str, str] = {}
        for kind in sorted({p.kind for p in self.m.parts}):
            def_name = self.cat.entry(kind).sysml.part_def
            if by_def.setdefault(def_name, kind) != kind:
                raise SysmlGenerationError(f"catalogue kinds {by_def[def_name]!r} and {kind!r} "
                                           f"share the SysML part def {def_name!r}")
        views = []
        for def_name, kind in sorted(by_def.items()):
            entry = self.cat.entry(kind)
            attrs: dict[str, str | None] = {}
            for p in self.m.parameters:
                owner = self.parts.get(p.owner)
                if p.status != "effective" or owner is None or owner.kind != kind:
                    continue
                vtype = self.value_type(p)
                # a block's value has the unit of its use (a gain on kg/kg here, on 1/s there):
                # the def leaves it untyped and each usage binds its own typed value
                if attrs.setdefault(p.name, vtype) not in (vtype, None):
                    attrs[p.name] = None
            members = [f"attribute {sysml_name(n)}" + (f" : {t}" if t else "")
                       for n, t in sorted(attrs.items())]
            for role, spec in sorted(entry.ports.items()):
                conj = "~" if spec.direction == "in" else ""
                members.append(f"port {sysml_name(role)} : {conj}{DOMAIN_PORTS[spec.domain][0]}")
            doc = [f"kind: {kind}", f"catalogue: {entry.description}"]
            if entry.dynamic_ports:
                doc.append("ports come from each IR part and are declared on its usage")
            views.append(DefView(sysml_name(def_name), doc, members))
        return views

    def events(self) -> list[DocItem]:
        items = []
        for sm in self.m.state_machines:
            for e in sm.events:
                doc = [f"ir: {e.id}", f"event of {sm.id}: {e.edge} edge of port {e.port}"]
                items.append((e.id, DocItem(f"attribute def {sysml_name(e.id)}", doc)))
        return [item for _, item in sorted(items, key=lambda x: x[0])]

    # --- behaviour ---

    def _expression(self, expr: Expr, state_paths: dict[str, str], parent: int = 0) -> str:
        if isinstance(expr, Name):
            return sysml_name(expr.id)
        if isinstance(expr, Number):
            return _number(expr.value)
        if isinstance(expr, BoolLit):
            return "true" if expr.value else "false"
        if isinstance(expr, Call):
            self.library.add(expr.func)
            arg = state_paths[expr.arg] if expr.func == "in_state" else sysml_name(expr.arg)
            return f"{expr.func}({arg})"
        if isinstance(expr, Not):
            inner = self._expression(expr.operand, state_paths, 3)
            atomic = isinstance(expr.operand, (Name, Number, BoolLit, Call))
            return f"not {inner}" if atomic else f"not ({inner})"
        if isinstance(expr, Compare):
            left = self._expression(expr.left, state_paths, 4)
            right = self._expression(expr.right, state_paths, 4)
            text = f"{left} {expr.op} {right}"
            return f"({text})" if parent > 4 else text
        assert isinstance(expr, BoolOp)
        prec = _PRECEDENCE[expr.op]
        text = (f"{self._expression(expr.left, state_paths, prec)} {expr.op} "
                f"{self._expression(expr.right, state_paths, prec + 1)}")
        return f"({text})" if parent > prec else text

    def _action(self, text: str) -> tuple[str, str]:
        """(verb, argument block) for one IR action."""
        action = parse_action(text)
        self.library.add(action.verb)
        args = f" {{ in timer = {sysml_name(action.args[0])}; }}" if action.args else ""
        return action.verb, args

    def _effect(self, actions: list[str]) -> str:
        parts = [self._action(a) for a in actions]
        if len(parts) == 1:
            verb, args = parts[0]
            return f"action : {verb}{args}"
        inner = " ".join(f"action : {verb}{args}" if args else f"action : {verb};"
                         for verb, args in parts)
        return f"action {{ {inner} }}"

    def _state(self, sm: StateMachine, sid: str) -> StateView:
        s = next(st for st in sm.states if st.id == sid)
        doc = [f"ir: {s.id}", f"name: {s.name}"]
        if s.tags:
            doc.append("tags: " + ", ".join(s.tags))
        entry = []
        for port_id, value in sorted(s.outputs.items()):
            literal = ("true" if value else "false") if isinstance(value, bool) else _number(value)
            entry.append(f"assign {sysml_name(port_id)} := {literal};")
        for text in s.entry_actions:
            verb, args = self._action(text)
            entry.append(f"perform action : {verb}{args}" if args
                         else f"perform action : {verb};")
        return StateView(sysml_name(s.id), doc, entry)

    def _transitions(self, sm: StateMachine, state_ids: list[str],
                     state_paths: dict[str, str]) -> list[DocItem]:
        order = {sid: i for i, sid in enumerate(s.id for s in sm.states)}
        chosen = sorted((t for t in sm.transitions if t.from_ in state_ids),
                        key=lambda t: (order[t.from_], t.priority, t.id))
        items = []
        for t in chosen:
            text = f"transition {sysml_name(t.id)} first {sysml_name(t.from_)}"
            if t.trigger:
                text += f" accept {sysml_name(t.trigger)}"
            if t.guard:
                text += f" if {self._expression(parse_expression(t.guard), state_paths)}"
            if t.actions:
                text += f" do {self._effect(t.actions)}"
            text += f" then {sysml_name(t.to)}"
            items.append(DocItem(text, [f"ir: {t.id}", f"priority: {t.priority}"]))
        return items

    def _operands(self, sm: StateMachine) -> tuple[list[str], list[str], list[str]]:
        """(port operands, parameter operands, output ports) the machine refers to."""
        names: set[str] = set()
        for t in sm.transitions:
            if t.guard:
                names |= expression_names(parse_expression(t.guard))
        outputs = sorted({pid for s in sm.states for pid in s.outputs})
        clash = sorted(names & set(outputs))
        if clash:
            raise SysmlGenerationError(f"state machine {sm.id!r}: {clash} are read by a guard and "
                                       "written by a state; SysML needs them to be distinct")
        return (sorted(n for n in names if n in self.ports),
                sorted(n for n in names if n in self.params), outputs)

    def state_def(self, sm: StateMachine) -> StateDefView:
        port_ops, param_ops, outputs = self._operands(sm)
        decls = []
        for pid in port_ops:
            decls.append(f"in attribute {sysml_name(pid)} : "
                         f"{DOMAIN_PORTS[self.ports[pid][1].domain][2]}")
        for pid in param_ops:
            decls.append(f"in attribute {sysml_name(pid)} : {self.value_type(self.params[pid])}")
        for pid in outputs:
            decls.append(f"out attribute {sysml_name(pid)} : "
                         f"{DOMAIN_PORTS[self.ports[pid][1].domain][2]}")
        timers = [DocItem(f"attribute {sysml_name(t.id)} : TimeValue",
                          [f"ir: {t.id}", f"duration: parameter {t.duration}; counts only while "
                                          "its state is active"])
                  for t in sm.timers]
        region_of = {sid: r for r in sm.regions for sid in r.states}
        state_paths = {s.id: (_path(region_of[s.id].id, s.id) if s.id in region_of
                              else sysml_name(s.id)) for s in sm.states}
        doc =[f"ir: {sm.id}", f"owner: {sm.owner}", _source_line(sm.trace),
               *self.assumptions_of(sm.id, sm.assumption_ids)]
        if not sm.regions:
            ids = [s.id for s in sm.states]
            history = any(t.to == HISTORY for t in sm.transitions)
            body = RegionView("", [], sysml_name(sm.initial),
                              [self._state(sm, sid) for sid in ids],
                              _HISTORY_DOC if history else [],
                              self._transitions(sm, ids, state_paths))
            return StateDefView(sysml_name(sm.id), doc, False, decls, timers, body, [])
        return StateDefView(sysml_name(sm.id), doc, True, decls, timers,
                            RegionView("", [], "", [], [], []),
                            self._regions(sm, region_of, state_paths))

    def _regions(self, sm: StateMachine, region_of: dict, state_paths: dict[str, str]
                 ) -> list[RegionView]:
        loose = [s.id for s in sm.states if s.id not in region_of]
        if loose:
            raise SysmlGenerationError(f"state machine {sm.id!r}: states {loose} are in no region")
        for t in sm.transitions:
            if t.to != HISTORY and region_of[t.to].id != region_of[t.from_].id:
                raise SysmlGenerationError(f"transition {t.id!r} crosses from region "
                                           f"{region_of[t.from_].id!r} to {region_of[t.to].id!r}")
        views = []
        for r in sm.regions:
            ids = [s.id for s in sm.states if s.id in r.states]
            history = any(t.to == HISTORY for t in sm.transitions if t.from_ in ids)
            views.append(RegionView(sysml_name(r.id), [f"ir: {r.id}", f"name: {r.name}"],
                                    sysml_name(r.initial), [self._state(sm, sid) for sid in ids],
                                    _HISTORY_DOC if history else [],
                                    self._transitions(sm, ids, state_paths)))
        return views

    def exhibit(self, sm: StateMachine) -> ExhibitView:
        port_ops, param_ops, outputs = self._operands(sm)
        bindings, unbound = [], []
        for pid in port_ops:
            item = DOMAIN_PORTS[self.ports[pid][1].domain][1]
            bindings.append(f"in :>> {sysml_name(pid)} = {self.port_path(pid)}.{item}")
        for pid in param_ops:
            p = self.params[pid]
            eff = self.effective.get((p.owner, p.name))
            if eff is None:
                unbound.append(f"{pid} (no effective value)")
            else:
                bindings.append(f"in :>> {sysml_name(pid)} = {self.param_path(eff)}")
        for pid in outputs:
            item = DOMAIN_PORTS[self.ports[pid][1].domain][1]
            bindings.append(f"out :>> {sysml_name(pid)} = {self.port_path(pid)}.{item}")
        for t in sm.timers:
            d = self.params[t.duration]
            eff = self.effective.get((d.owner, d.name))
            if eff is None:
                unbound.append(f"{t.id} (duration {t.duration} has no effective value)")
            else:
                bindings.append(f"attribute :>> {sysml_name(t.id)} = {self.param_path(eff)}")
        doc = [f"behaviour: state machine {sm.id}"]
        if unbound:
            doc.append("unbound: " + "; ".join(unbound))
        return ExhibitView(sysml_name(self.behaviour(sm)), sysml_name(sm.id), doc, bindings)

    # --- structure ---

    def element_paths(self) -> dict[str, str]:
        """IR element id -> SysML feature path from inside the system part, for satisfy."""
        paths: dict[str, str] = {p.id: sysml_name(p.id) for p in self.m.parts}
        paths.update({pid: self.port_path(pid) for pid in self.ports})
        paths.update({c.id: sysml_name(c.id) for c in self.m.connections})
        paths.update({p.id: self.param_path(p) for p in self.m.parameters
                      if p.status == "effective"})
        for sm in self.m.state_machines:
            base = _path(sm.owner, self.behaviour(sm))
            paths[sm.id] = base
            region_of = {sid: r.id for r in sm.regions for sid in r.states}
            for s in sm.states:
                inner = [region_of[s.id]] if s.id in region_of else []
                paths[s.id] = ".".join([base, _path(*inner, s.id)])
            for t in sm.transitions:
                inner = [region_of[t.from_]] if t.from_ in region_of else []
                paths[t.id] = ".".join([base, _path(*inner, t.id)])
            for r in sm.regions:
                paths[r.id] = ".".join([base, sysml_name(r.id)])
            for tm in sm.timers:
                paths[tm.id] = ".".join([base, sysml_name(tm.id)])
        return paths

    def _why_not_modelled(self, eid: str) -> str:
        if eid in self.params:
            return f"{self.params[eid].status} parameter; reported, not modelled"
        if any(r.id == eid for r in self.m.requirements):
            return "requirement"
        return "not an element of the SysML model"

    def requirements(self, paths: dict[str, str]) -> tuple[list[DocItem], list[str]]:
        items, satisfies = [], []
        for r in sorted((r for r in self.m.requirements if r.status == "active"),
                        key=lambda r: r.id):
            doc = [f"ir: {r.id}"]
            if r.tags:
                doc.append("tags: " + ", ".join(r.tags))
            doc += [f"category: {r.category}", f"text: {r.text}", _source_line(r.trace)]
            missing = [f"{eid} ({self._why_not_modelled(eid)})"
                       for eid in r.satisfied_by if eid not in paths]
            if missing:
                doc.append("satisfied by, not modelled in SysML: " + ", ".join(missing))
            doc += self.assumptions_of(r.id, r.assumption_ids)
            items.append(DocItem(f"requirement {sysml_name(r.id)}", doc))
            satisfies += [f"satisfy {sysml_name(r.id)} by {paths[eid]}"
                          for eid in r.satisfied_by if eid in paths]
        return items, satisfies

    def _attribute(self, p: Parameter, text: str) -> DocItem:
        doc = [f"ir: {p.id}", f"authority: {p.authority}",
               f"original: {p.original.value} {p.original.unit}", _source_line(p.trace),
               *self.assumptions_of(p.id, p.assumption_ids)]
        return DocItem(text, doc)

    def part_usage(self, part: Part) -> PartUsageView:
        doc = [f"ir: {part.id}", f"name: {part.name}"]
        if part.tags:
            doc.append("tags: " + ", ".join(part.tags))
        for key, value in sorted(part.attributes.items()):
            shown = ("true" if value else "false") if isinstance(value, bool) else value
            doc.append(f"attribute: {key} = {shown}")
        doc += [_source_line(part.trace), *self.assumptions_of(part.id, part.assumption_ids)]
        ports = []
        if self.dynamic(part):
            for port in sorted(part.ports, key=lambda p: p.id):
                pdoc = [f"ir: {port.id}", f"role: {port.role}"]
                if port.trace:
                    pdoc.append(_source_line(port.trace))
                pdoc += self.assumptions_of(port.id, port.assumption_ids)
                ports.append(DocItem(f"port {sysml_name(port.id)} : {self.port_type(port)}",
                                     pdoc))
        attrs = [self._attribute(p, f"attribute :>> {sysml_name(p.name)} = {self.value_text(p)}")
                 for p in sorted(self.m.parameters, key=lambda p: (p.name, p.id))
                 if p.owner == part.id and p.status == "effective"]
        exhibits = [self.exhibit(sm) for sm in sorted(self.m.state_machines, key=lambda s: s.id)
                    if sm.owner == part.id]
        definition = sysml_name(self.cat.entry(part.kind).sysml.part_def)
        return PartUsageView(sysml_name(part.id), definition, doc, ports, attrs, exhibits)

    def connections(self) -> list[DocItem]:
        items = []
        for c in sorted(self.m.connections, key=lambda c: c.id):
            doc = [f"ir: {c.id}", f"from: {c.from_port} -> to: {c.to_port}",
                   f"carries: {c.medium_or_signal}", _source_line(c.trace),
                   *self.assumptions_of(c.id, c.assumption_ids)]
            items.append(DocItem(f"connection {sysml_name(c.id)} connect "
                                 f"{self.port_path(c.from_port)} to {self.port_path(c.to_port)}",
                                 doc))
        return items

    def package(self) -> PackageView:
        state_defs = [self.state_def(sm) for sm in sorted(self.m.state_machines,
                                                          key=lambda s: s.id)]
        paths = self.element_paths()
        requirements, satisfies = self.requirements(paths)
        system_attrs = [self._attribute(p, f"attribute {sysml_name(p.name)} : "
                                           f"{self.value_type(p)} = {self.value_text(p)}")
                        for p in sorted(self.m.parameters, key=lambda p: (p.name, p.id))
                        if p.owner == SYSTEM_OWNER and p.status == "effective"]
        system = SystemView(
            sysml_name(SYSTEM_OWNER),
            ["the system: one usage per IR part, its connections, effective values and the "
             "requirements it satisfies"],
            [self.part_usage(p) for p in sorted(self.m.parts, key=lambda p: p.id)],
            system_attrs, self.connections(), satisfies)
        doc = [f"model: {self.m.name}", f"description: {self.m.description}",
               "generated from the IR by SpecAlive (generate/sysml.py); regenerate, do not edit"]
        return PackageView(sysml_name(self.m.name), doc, sorted(self.library), self.port_defs(),
                           self.part_defs(), self.events(), state_defs, requirements, system)


# --- entry points ---------------------------------------------------------------------------

def load_ir(path: Path) -> SystemModel:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise IRError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        return SystemModel.model_validate_json(text)
    except ValidationError as exc:
        raise IRError(f"{path} is not a valid IR: {exc}") from None


def render_sysml(model: SystemModel, catalogue: Catalogue) -> str:
    """The SysML v2 text for `model`; the same IR always gives the same bytes (R-SYS-1)."""
    view = _Builder(model, catalogue).package()
    return environment().get_template("package.sysml.j2").render(pkg=view)


def write_sysml(model: SystemModel, catalogue: Catalogue, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / MODEL_FILE
    target.write_text(render_sysml(model, catalogue), encoding="utf-8", newline="\n")
    return target
