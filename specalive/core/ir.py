# Purpose: the IR — the single source of truth both generated models come from (R-IR-1). Pydantic
# v2 records for parts, ports, connections, parameters, state machines, requirements, acceptance
# criteria and the honesty records, plus a SystemModel validator that enforces R-IR-2 (trace or
# assumption on every element), resolves every cross-reference, and parses guards, actions and
# checks with a small recursive-descent expression language over IR ids (R-IR-6).
from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from specalive.core.units import SI_UNITS

ID_PATTERN = r"^[a-z_][a-z0-9_]*$"
IdStr = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
MAX_QUOTE = 300

# The reserved transition target meaning "the state saved by the last save_history" (UML shallow
# history). Returning to it also restores the remaining time of that state's timers.
HISTORY = "history"
SYSTEM_OWNER = "system"

Domain = Literal["fluid", "signal_real", "signal_bool", "event", "thermal", "electric", "magnetic"]
Direction = Literal["in", "out", "inout"]
SourceRole = Literal[
    "change_record", "review_decision", "requirement_spec", "design_note", "datasheet",
    "verification_procedure", "reference_data", "legacy_model", "legacy_architecture",
    "correspondence", "informal_note", "register", "other",
]


# --- expression language ------------------------------------------------------------------
#
#   expr     := and_expr ("or" and_expr)*
#   and_expr := not_expr ("and" not_expr)*
#   not_expr := "not" not_expr | compare
#   compare  := operand (("<" | "<=" | ">" | ">=" | "==" | "!=") operand)?
#   operand  := NUMBER | "true" | "false" | IDENT | FUNC "(" IDENT ")" | "(" expr ")"
#   FUNC     := "timer_expired" | "in_state"
#
#   action   := "start_timer" "(" IDENT ")" | "save_history" | "clear_history"
#
# Identifiers are IR ids: ports and parameters as operands, timers and states as call arguments.

FUNCTIONS = frozenset({"timer_expired", "in_state"})
ACTIONS: dict[str, int] = {"start_timer": 1, "save_history": 0, "clear_history": 0}
COMPARATORS = frozenset({"<", "<=", ">", ">=", "==", "!="})
_KEYWORDS = frozenset({"and", "or", "not", "true", "false"})
_TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)|(?P<op><=|>=|==|!=|<|>)"
                    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<punct>[(),]))")


class ExpressionError(ValueError):
    """A guard, action or check condition that does not parse."""


@dataclass(frozen=True)
class Name:
    id: str


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class BoolLit:
    value: bool


@dataclass(frozen=True)
class Call:
    func: str
    arg: str


@dataclass(frozen=True)
class Not:
    operand: Expr


@dataclass(frozen=True)
class BoolOp:
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Compare:
    op: str
    left: Expr
    right: Expr


Expr = Name | Number | BoolLit | Call | Not | BoolOp | Compare


@dataclass(frozen=True)
class Action:
    verb: str
    args: tuple[str, ...]


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens, pos, end = [], 0, len(text.rstrip())
    while pos < end:
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ExpressionError(f"unexpected character at {pos} in {text!r}")
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = _tokenize(text)
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, value: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None or (value is not None and tok[1] != value):
            want = repr(value) if value else "more input"
            raise ExpressionError(f"expected {want} in {self.text!r}")
        self.pos += 1
        return tok

    def at(self, value: str) -> bool:
        tok = self.peek()
        return tok is not None and tok[1] == value

    def done(self) -> None:
        if self.peek() is not None:
            raise ExpressionError(f"unexpected {self.peek()[1]!r} in {self.text!r}")

    def identifier(self) -> str:
        kind, value = self.take()
        if kind != "name" or value in _KEYWORDS:
            raise ExpressionError(f"expected an identifier, got {value!r} in {self.text!r}")
        return value

    def expr(self) -> Expr:
        left = self.and_expr()
        while self.at("or"):
            self.take()
            left = BoolOp("or", left, self.and_expr())
        return left

    def and_expr(self) -> Expr:
        left = self.not_expr()
        while self.at("and"):
            self.take()
            left = BoolOp("and", left, self.not_expr())
        return left

    def not_expr(self) -> Expr:
        if self.at("not"):
            self.take()
            return Not(self.not_expr())
        return self.compare()

    def compare(self) -> Expr:
        left = self.operand()
        tok = self.peek()
        if tok and tok[0] == "op":
            self.take()
            return Compare(tok[1], left, self.operand())
        return left

    def operand(self) -> Expr:
        kind, value = self.take()
        if kind == "num":
            return Number(float(value))
        if value == "(":
            inner = self.expr()
            self.take(")")
            return inner
        if kind != "name" or value in {"and", "or", "not"}:
            raise ExpressionError(f"unexpected {value!r} in {self.text!r}")
        if value in ("true", "false"):
            return BoolLit(value == "true")
        if self.at("("):
            if value not in FUNCTIONS:
                raise ExpressionError(f"unknown function {value!r} in {self.text!r}")
            self.take("(")
            arg = self.identifier()
            self.take(")")
            return Call(value, arg)
        return Name(value)


def parse_expression(text: str) -> Expr:
    """Parse a guard or check condition into its syntax tree."""
    parser = _Parser(text)
    if parser.peek() is None:
        raise ExpressionError("empty expression")
    expr = parser.expr()
    parser.done()
    return expr


def parse_action(text: str) -> Action:
    """Parse one transition or entry action."""
    parser = _Parser(text)
    verb = parser.identifier()
    if verb not in ACTIONS:
        raise ExpressionError(f"unknown action {verb!r}")
    args: list[str] = []
    if parser.at("("):
        parser.take("(")
        args.append(parser.identifier())
        parser.take(")")
    parser.done()
    if len(args) != ACTIONS[verb]:
        raise ExpressionError(f"action {verb!r} takes {ACTIONS[verb]} argument(s), got {len(args)}")
    return Action(verb, tuple(args))


def _walk(expr: Expr) -> Iterator[Expr]:
    yield expr
    if isinstance(expr, Not):
        yield from _walk(expr.operand)
    elif isinstance(expr, (BoolOp, Compare)):
        yield from _walk(expr.left)
        yield from _walk(expr.right)


def expression_names(expr: Expr) -> set[str]:
    """Identifiers used as operands (ports, parameters); call arguments are excluded."""
    return {node.id for node in _walk(expr) if isinstance(node, Name)}


def expression_calls(expr: Expr) -> list[Call]:
    return [node for node in _walk(expr) if isinstance(node, Call)]


# --- records ------------------------------------------------------------------------------

class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True,
                              serialize_by_alias=True)


class TraceLink(_Record):
    source_id: IdStr
    locator: str = Field(min_length=1, description="page, sheet+row, section or line")
    quote: str = Field(min_length=1, max_length=MAX_QUOTE, description="verbatim from the source")


class _Traced(_Record):
    trace: list[TraceLink] = []
    assumption_ids: list[str] = []


class Source(_Record):
    id: IdStr
    title: str
    path: str | None = Field(None, description="bundle-relative path; None for a cited record")
    role: SourceRole
    revision: str | None = None
    date: str | None = Field(None, description="ISO date")
    reliability: Literal["high", "medium", "low"] | None = None
    tags: list[str] = Field([], description="identifiers the source is cited by")


class Port(_Traced):
    """A port with no trace or assumption inherits its part's."""

    id: IdStr
    role: str = Field(description="catalogue port role, e.g. inlet, level_out, cmd_in")
    direction: Direction
    domain: Domain
    unit: str | None = None


class Part(_Traced):
    id: IdStr
    kind: str = Field(description="a catalogue key")
    name: str
    tags: list[str] = Field([], description="every alias seen: formal tag, short name, legacy name")
    attributes: dict[str, str | bool] = Field(
        {}, description="descriptive facts; numeric values are Parameters owned by the part")
    ports: list[Port] = []
    confidence: float = Field(1.0, ge=0.0, le=1.0)


class Connection(_Traced):
    id: IdStr
    from_port: str
    to_port: str
    medium_or_signal: str


class OriginalValue(_Record):
    value: str
    unit: str


class Parameter(_Traced):
    id: IdStr
    owner: str = Field(description=f"part id or '{SYSTEM_OWNER}'")
    name: str
    value: float | list[float] = Field(description="SI")
    unit: str = Field(description="SI unit from core/units.py")
    original: OriginalValue
    status: Literal["effective", "superseded", "as_built_only", "verification_only"]
    authority: str = Field(description="source id")


class Event(_Record):
    id: IdStr
    port: str = Field(description="input port of the machine's owner that carries the command")
    edge: Literal["rising", "falling"] = "rising"


class Timer(_Record):
    """Counts only while its state is active; save_history keeps its remaining time."""

    id: IdStr
    duration: str = Field(description="parameter id")


class State(_Record):
    id: IdStr
    name: str
    tags: list[str] = Field([], description="aliases, e.g. legacy state names")
    entry_actions: list[str] = []
    outputs: dict[str, bool | float] = Field(
        {}, description="owner output port id -> value held while in this state")


class Transition(_Record):
    id: IdStr
    from_: str = Field(alias="from")
    to: str = Field(description=f"state id or '{HISTORY}'")
    trigger: str | None = Field(None, description="event id")
    guard: str | None = None
    actions: list[str] = []
    priority: int = Field(ge=1, description="1 is evaluated first; unique per source state")


class Region(_Record):
    id: IdStr
    name: str
    states: list[str]
    initial: str


class StateMachine(_Traced):
    id: IdStr
    owner: str
    initial: str
    events: list[Event] = []
    timers: list[Timer] = []
    states: list[State]
    transitions: list[Transition] = []
    regions: list[Region] = Field([], description="parallel branches; empty for a flat machine")


class Requirement(_Traced):
    id: IdStr
    tags: list[str] = Field([], description="identifiers as written in the sources, first is primary")
    text: str
    category: str
    status: Literal["active", "superseded"]
    superseded_by: str | None = None
    satisfied_by: list[str] = []


class Check(_Record):
    """A condition over a time window: [start_s, end_s), open ends meaning the run's bounds."""

    mode: Literal["at", "always", "eventually"]
    condition: str
    start_s: float | None = None
    end_s: float | None = None


class AcceptanceCriterion(_Record):
    id: IdStr
    tags: list[str] = []
    text: str
    check: Check | None = None
    reason: str | None = Field(None, description="why there is no check")
    trace: list[TraceLink] = []


class Assumption(_Record):
    id: IdStr
    text: str
    basis: Literal["engineering_convention", "default", "inferred"]
    affects: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    trace: list[TraceLink] = []


class Question(_Record):
    id: IdStr
    text: str
    options: list[str] = []
    default_if_unanswered: str | None = None
    affects: list[str] = []
    answer: str | None = None


class ConflictSubject(_Record):
    element_id: str
    field: str


class Candidate(_Record):
    value: str = Field(description="as written")
    source_id: str
    authority_rank: int = Field(ge=1, description="1 is the highest authority")
    element_id: str | None = Field(None, description="the parameter holding this value, if any")


class Conflict(_Record):
    id: IdStr
    subject: ConflictSubject
    candidates: list[Candidate] = Field(min_length=2)
    resolution: str = Field(description="winning value, or 'unresolved'")
    rationale: str


class SystemModel(_Record):
    name: str
    description: str
    sources: list[Source] = []
    parts: list[Part] = []
    connections: list[Connection] = []
    parameters: list[Parameter] = []
    state_machines: list[StateMachine] = []
    requirements: list[Requirement] = []
    acceptance_criteria: list[AcceptanceCriterion] = []
    assumptions: list[Assumption] = []
    questions: list[Question] = []
    conflicts: list[Conflict] = []

    @model_validator(mode="after")
    def _check_integrity(self) -> SystemModel:
        errors = _Integrity(self).errors()
        if errors:
            raise ValueError("IR integrity:\n  " + "\n  ".join(errors))
        return self


class _Integrity:
    """Cross-record checks, collected so one run reports every problem."""

    def __init__(self, m: SystemModel) -> None:
        self.m = m
        self.problems: list[str] = []
        self.sources = {s.id for s in m.sources}
        self.parts = {p.id: p for p in m.parts}
        self.ports = {port.id: (part, port) for part in m.parts for port in part.ports}
        self.params = {p.id: p for p in m.parameters}
        self.assumptions = {a.id for a in m.assumptions}
        self.requirements = {r.id for r in m.requirements}
        self.states = {s.id for sm in m.state_machines for s in sm.states}
        self.timers = {t.id for sm in m.state_machines for t in sm.timers}
        self.element_ids: set[str] = set()

    def errors(self) -> list[str]:
        self._unique_ids()
        self._honesty()
        self._connections()
        self._parameters()
        for sm in self.m.state_machines:
            self._state_machine(sm)
        self._requirements()
        self._criteria()
        self._records()
        return self.problems

    def fail(self, message: str) -> None:
        self.problems.append(message)

    def _all_ids(self) -> Iterator[str]:
        m = self.m
        for group in (m.sources, m.parts, m.connections, m.parameters, m.state_machines,
                      m.requirements, m.acceptance_criteria, m.assumptions, m.questions,
                      m.conflicts):
            yield from (item.id for item in group)
        for part in m.parts:
            yield from (port.id for port in part.ports)
        for sm in m.state_machines:
            for group in (sm.events, sm.timers, sm.states, sm.transitions, sm.regions):
                yield from (item.id for item in group)

    def _unique_ids(self) -> None:
        seen: set[str] = set()
        for item_id in self._all_ids():
            if item_id in seen:
                self.fail(f"duplicate id {item_id!r}")
            seen.add(item_id)
        self.element_ids = seen

    def _trace_or_assumption(self, kind: str, element: _Traced,
                             inherited: _Traced | None = None) -> None:
        for link in element.trace:
            if link.source_id not in self.sources:
                self.fail(f"{kind} {element.id!r}: trace cites unknown source {link.source_id!r}")
        for aid in element.assumption_ids:
            if aid not in self.assumptions:
                self.fail(f"{kind} {element.id!r}: unknown assumption {aid!r}")
        traced = element.trace or element.assumption_ids
        if not traced and not (inherited and (inherited.trace or inherited.assumption_ids)):
            self.fail(f"{kind} {element.id!r} has no trace and no assumption (R-IR-2)")

    def _honesty(self) -> None:
        m = self.m
        for part in m.parts:
            self._trace_or_assumption("part", part)
            for port in part.ports:
                self._trace_or_assumption("port", port, inherited=part)
        for kind, group in (("connection", m.connections), ("parameter", m.parameters),
                            ("state machine", m.state_machines), ("requirement", m.requirements)):
            for element in group:
                self._trace_or_assumption(kind, element)

    def _connections(self) -> None:
        for c in self.m.connections:
            ends = []
            for label, port_id in (("from_port", c.from_port), ("to_port", c.to_port)):
                if port_id not in self.ports:
                    self.fail(f"connection {c.id!r}: {label} {port_id!r} is not a port")
                else:
                    ends.append(self.ports[port_id][1])
            if len(ends) != 2:
                continue
            src, dst = ends
            if src.domain != dst.domain:
                self.fail(f"connection {c.id!r}: domain {src.domain} of {src.id!r} does not match "
                          f"{dst.domain} of {dst.id!r}")
            if src.direction == "in" or dst.direction == "out":
                self.fail(f"connection {c.id!r}: direction runs {src.direction} -> {dst.direction}; "
                          "it must run from an out/inout port to an in/inout port")

    def _parameters(self) -> None:
        effective: dict[tuple[str, str], str] = {}
        for p in self.m.parameters:
            if p.owner != SYSTEM_OWNER and p.owner not in self.parts:
                self.fail(f"parameter {p.id!r}: owner {p.owner!r} is not a part or 'system'")
            if p.authority not in self.sources:
                self.fail(f"parameter {p.id!r}: authority {p.authority!r} is not a source")
            if p.unit not in SI_UNITS:
                self.fail(f"parameter {p.id!r}: unit {p.unit!r} is not an SI unit (R-IR-4)")
            if p.status == "effective":
                key = (p.owner, p.name)
                if key in effective:
                    self.fail(f"parameter {p.id!r}: {p.owner}.{p.name} already has an effective "
                              f"value in {effective[key]!r}")
                effective.setdefault(key, p.id)

    def _expression(self, where: str, text: str, operands: set[str], timers: set[str]) -> None:
        try:
            expr = parse_expression(text)
        except ExpressionError as exc:
            self.fail(f"{where}: {exc}")
            return
        for name in sorted(expression_names(expr) - operands):
            self.fail(f"{where}: {name!r} is not a port or parameter id")
        for call in expression_calls(expr):
            known = timers if call.func == "timer_expired" else self.states
            if call.arg not in known:
                self.fail(f"{where}: {call.func}({call.arg}) names an unknown id")

    def _actions(self, where: str, actions: list[str], timers: set[str]) -> set[str]:
        verbs: set[str] = set()
        for text in actions:
            try:
                action = parse_action(text)
            except ExpressionError as exc:
                self.fail(f"{where}: {exc}")
                continue
            verbs.add(action.verb)
            if action.verb == "start_timer" and action.args[0] not in timers:
                self.fail(f"{where}: start_timer({action.args[0]}) names an unknown timer")
        return verbs

    def _state_machine(self, sm: StateMachine) -> None:
        where = f"state machine {sm.id!r}"
        if sm.owner not in self.parts:
            self.fail(f"{where}: owner {sm.owner!r} is not a part")
        owner_ports = {p.id: p for p in self.parts[sm.owner].ports} if sm.owner in self.parts else {}
        states = {s.id for s in sm.states}
        timers = {t.id for t in sm.timers}
        events = {e.id for e in sm.events}
        operands = set(self.ports) | set(self.params)
        if sm.initial not in states:
            self.fail(f"{where}: initial state {sm.initial!r} is not one of its states")
        for e in sm.events:
            port = owner_ports.get(e.port)
            if port is None or port.direction == "out":
                self.fail(f"{where}: event {e.id!r} port {e.port!r} is not an input of the owner")
        for t in sm.timers:
            if t.duration not in self.params:
                self.fail(f"{where}: timer {t.id!r} duration {t.duration!r} is not a parameter")
        verbs: set[str] = set()
        for s in sm.states:
            for port_id in s.outputs:
                port = owner_ports.get(port_id)
                if port is None or port.direction == "in":
                    self.fail(f"{where}: state {s.id!r} output {port_id!r} is not an output port "
                              "of the owner")
            verbs |= self._actions(f"state {s.id!r}", s.entry_actions, timers)
        priorities: set[tuple[str, int]] = set()
        for t in sm.transitions:
            tw = f"transition {t.id!r}"
            if t.from_ not in states:
                self.fail(f"{tw}: from {t.from_!r} is not a state of {sm.id!r}")
            if t.to not in states and t.to != HISTORY:
                self.fail(f"{tw}: to {t.to!r} is not a state of {sm.id!r}")
            if t.trigger is not None and t.trigger not in events:
                self.fail(f"{tw}: trigger {t.trigger!r} is not an event of {sm.id!r}")
            if t.guard is not None:
                self._expression(f"{tw} guard", t.guard, operands, timers)
            verbs |= self._actions(tw, t.actions, timers)
            if (t.from_, t.priority) in priorities:
                self.fail(f"{tw}: priority {t.priority} is already used from state {t.from_!r}")
            priorities.add((t.from_, t.priority))
        if any(t.to == HISTORY for t in sm.transitions) and "save_history" not in verbs:
            self.fail(f"{where}: a transition targets '{HISTORY}' but no action does save_history")
        for r in sm.regions:
            for sid in [*r.states, r.initial]:
                if sid not in states:
                    self.fail(f"{where}: region {r.id!r} names unknown state {sid!r}")

    def _requirements(self) -> None:
        for r in self.m.requirements:
            if r.superseded_by is not None:
                if r.status != "superseded":
                    self.fail(f"requirement {r.id!r} is {r.status} but has superseded_by")
                if r.superseded_by not in self.requirements:
                    self.fail(f"requirement {r.id!r}: superseded_by {r.superseded_by!r} "
                              "is not a requirement")
            for eid in r.satisfied_by:
                if eid not in self.element_ids:
                    self.fail(f"requirement {r.id!r}: satisfied_by {eid!r} is not an element")

    def _criteria(self) -> None:
        operands = set(self.ports) | set(self.params)
        for ac in self.m.acceptance_criteria:
            for link in ac.trace:
                if link.source_id not in self.sources:
                    self.fail(f"criterion {ac.id!r}: trace cites unknown source {link.source_id!r}")
            if ac.check is None:
                if not ac.reason:
                    self.fail(f"criterion {ac.id!r} has no check and no reason")
                continue
            c = ac.check
            if c.mode == "at" and c.start_s is None:
                self.fail(f"criterion {ac.id!r}: an 'at' check needs start_s")
            if c.start_s is not None and c.end_s is not None and c.start_s > c.end_s:
                self.fail(f"criterion {ac.id!r}: start_s {c.start_s} is after end_s {c.end_s}")
            self._expression(f"criterion {ac.id!r}", c.condition, operands, self.timers)

    def _records(self) -> None:
        for a in self.m.assumptions:
            for link in a.trace:
                if link.source_id not in self.sources:
                    self.fail(f"assumption {a.id!r}: trace cites unknown source {link.source_id!r}")
        for kind, group in (("assumption", self.m.assumptions), ("question", self.m.questions)):
            for record in group:
                for eid in record.affects:
                    if eid not in self.element_ids:
                        self.fail(f"{kind} {record.id!r}: affects {eid!r} is not an element")
        for c in self.m.conflicts:
            if c.subject.element_id not in self.element_ids:
                self.fail(f"conflict {c.id!r}: subject {c.subject.element_id!r} is not an element")
            for cand in c.candidates:
                if cand.source_id not in self.sources:
                    self.fail(f"conflict {c.id!r}: candidate source {cand.source_id!r} "
                              "is not a source")
                if cand.element_id is not None and cand.element_id not in self.element_ids:
                    self.fail(f"conflict {c.id!r}: candidate element {cand.element_id!r} "
                              "is not an element")


# --- JSON Schema export -------------------------------------------------------------------

def json_schema_text() -> str:
    """The committed docs/ir.schema.json, byte for byte."""
    schema = SystemModel.model_json_schema(by_alias=True)
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    # python -m specalive.core.ir > docs/ir.schema.json
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.stdout.write(json_schema_text())
