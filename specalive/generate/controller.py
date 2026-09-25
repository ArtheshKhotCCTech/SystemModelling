# Purpose: renders one IR state machine as a Modelica controller class (FR-06 requirements 8-9),
# deterministically and with no domain events built in (R-MO-7). One enumeration literal per IR
# state; one `when` over every command edge and every `pre(state) == S and guard`, whose body
# checks transitions in IR priority order; a deadline and a remaining time per timer, so
# save_history freezes a timer and a history return restores it; outputs as equations over the
# state; window-free `always` acceptance criteria that read only this controller as asserts.
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import jinja2

from specalive.core.ir import (
    HISTORY,
    AcceptanceCriterion,
    BoolLit,
    BoolOp,
    Call,
    Compare,
    Expr,
    Name,
    Not,
    Number,
    Port,
    StateMachine,
    SystemModel,
    parse_action,
    parse_expression,
)
from specalive.generate.modelica_text import (
    ModelicaGenerationError,
    modelica_name,
    number,
    one_line,
    string,
)

TEMPLATES = Path(__file__).resolve().parent / "templates" / "modelica"
CLASS_PREFIX = "Controller_"
STATE_VAR, HISTORY_VAR = "state", "history_state"
_USABLE = ("effective", "verification_only")
_LEVEL = {"or": 1, "and": 2}
_NOT, _COMPARE, _OPERAND = 3, 4, 5
_OPERATORS = {"==": "==", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
_CONNECTORS = {("signal_real", "in"): "SpecAlive.Interfaces.RealInput",
               ("signal_real", "out"): "SpecAlive.Interfaces.RealOutput",
               ("signal_bool", "in"): "SpecAlive.Interfaces.BooleanInput",
               ("signal_bool", "out"): "SpecAlive.Interfaces.BooleanOutput"}


@dataclass(frozen=True)
class TransitionView:
    condition: str
    statements: list[str]


@dataclass(frozen=True)
class BranchView:
    state: str
    transitions: list[TransitionView]


@dataclass(frozen=True)
class ControllerView:
    class_name: str
    description: str
    comments: list[str]
    literals: list[str]
    declarations: list[str]
    conditions: list[str]
    branches: list[BranchView]
    equations: list[str]


@dataclass(frozen=True)
class RenderedController:
    class_name: str
    text: str
    parameters: list[str]  # Modelica names the instance must bind, sorted
    asserted: list[str]  # ids of the acceptance criteria rendered as asserts
    not_asserted: dict[str, str]  # invariant id -> why this controller could not assert it


class _Unresolvable(ModelicaGenerationError):
    """An expression names something outside this controller."""


def class_name(sm: StateMachine) -> str:
    """Capitalised, so it can never equal an IR id (all lower case) used as an instance name."""
    return CLASS_PREFIX + modelica_name(sm.id)


def invariants(model: SystemModel) -> list[AcceptanceCriterion]:
    """Acceptance criteria that must hold for the whole run: interlocks (FR-06 requirement 8)."""
    return sorted((ac for ac in model.acceptance_criteria
                   if ac.check is not None and ac.check.mode == "always"
                   and ac.check.start_s is None and ac.check.end_s is None),
                  key=lambda ac: ac.id)


def assumption_comments(model: SystemModel, element_id: str, own: list[str]) -> list[str]:
    text = {a.id: a.text for a in model.assumptions}
    ids = set(own) | {a.id for a in model.assumptions if element_id in a.affects}
    return [f"// ASSUMPTION {aid}: {one_line(text.get(aid, '(unknown assumption)'))}"
            for aid in sorted(ids)]


class _Controller:
    def __init__(self, sm: StateMachine, model: SystemModel) -> None:
        self.sm, self.m = sm, model
        where = f"state machine {sm.id!r}"
        if sm.regions:
            raise ModelicaGenerationError(
                f"{where} has parallel regions; the Modelica controller generator renders flat "
                "machines only")
        owner = next(p for p in model.parts if p.id == sm.owner)
        self.owner = owner
        self.ports: dict[str, Port] = {p.id: p for p in owner.ports}
        self.connector = {p.id: modelica_name(p.role) for p in owner.ports}
        self.params = {p.id: p for p in model.parameters}
        self.states = [s.id for s in sm.states]
        self.literal = {s.id: modelica_name(s.id) for s in sm.states}
        self.timer = {t.id: t for t in sm.timers}
        self.deadline = {t.id: f"{modelica_name(t.id)}_deadline" for t in sm.timers}
        self.remaining = {t.id: f"{modelica_name(t.id)}_remaining" for t in sm.timers}
        self.events = {e.id: e for e in sm.events}
        self.used_params: set[str] = set()
        self.not_asserted: dict[str, str] = {}
        self.timers_of = self._timer_owners()
        self._check_names()

    # --- names ---

    def _check_names(self) -> None:
        names = [STATE_VAR, HISTORY_VAR, "State", *self.connector.values(),
                 *self.deadline.values(), *self.remaining.values()]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise ModelicaGenerationError(
                    f"state machine {self.sm.id!r}: the name {name!r} is used twice in its "
                    "controller (a port role clashes with a generated variable)")
            seen.add(name)
        self.reserved = seen

    def _param_name(self, pid: str, where: str) -> str:
        p = self.params[pid]
        if p.status not in _USABLE:
            raise ModelicaGenerationError(
                f"{where}: parameter {pid!r} is {p.status}; only effective or verification-only "
                "values can drive the controller")
        if isinstance(p.value, list):
            raise ModelicaGenerationError(f"{where}: parameter {pid!r} is a list, not a number")
        name = modelica_name(pid)
        if name in self.reserved:
            raise ModelicaGenerationError(f"{where}: parameter {pid!r} clashes with a controller "
                                          "name")
        self.used_params.add(pid)
        return name

    # --- timers ---

    def _timer_owners(self) -> dict[str, list[str]]:
        """State -> timers that count while it is active: those its entry actions start and
        those started by a transition into it."""
        owners: dict[str, set[str]] = defaultdict(set)
        for s in self.sm.states:
            for action in map(parse_action, s.entry_actions):
                if action.verb == "start_timer":
                    owners[s.id].add(action.args[0])
        for t in self.sm.transitions:
            if t.to == HISTORY:
                continue
            for action in map(parse_action, t.actions):
                if action.verb == "start_timer":
                    owners[t.to].add(action.args[0])
        order = [t.id for t in self.sm.timers]
        return {s: sorted(ts, key=order.index) for s, ts in owners.items()}

    # --- expressions ---

    def _is_real(self, expr: Expr) -> bool:
        if isinstance(expr, Number):
            return True
        if isinstance(expr, Name):
            port = self.ports.get(expr.id)
            return expr.id in self.params or (port is not None and port.domain == "signal_real")
        return False

    def expression(self, expr: Expr, where: str, state_ref: str, parent: int = 0) -> str:
        text, level = self._render(expr, where, state_ref)
        return f"({text})" if level < parent else text

    def _render(self, expr: Expr, where: str, state_ref: str) -> tuple[str, int]:
        sub = lambda e, lvl: self.expression(e, where, state_ref, lvl)  # noqa: E731
        if isinstance(expr, Number):
            return number(expr.value), _OPERAND
        if isinstance(expr, BoolLit):
            return ("true" if expr.value else "false"), _OPERAND
        if isinstance(expr, Name):
            if expr.id in self.connector:
                return self.connector[expr.id], _OPERAND
            if expr.id in self.params:
                return self._param_name(expr.id, where), _OPERAND
            raise _Unresolvable(f"{where}: {expr.id!r} is not a port of {self.owner.id!r} or a "
                                "parameter, so the controller cannot read it")
        if isinstance(expr, Call):
            if expr.func == "in_state":
                if expr.arg not in self.literal:
                    raise _Unresolvable(f"{where}: {expr.arg!r} is not a state of {self.sm.id!r}")
                return f"{state_ref} == State.{self.literal[expr.arg]}", _COMPARE
            if expr.arg not in self.deadline:
                raise _Unresolvable(f"{where}: {expr.arg!r} is not a timer of {self.sm.id!r}")
            return f"time >= {self.deadline[expr.arg]}", _COMPARE
        if isinstance(expr, Not):
            return f"not {sub(expr.operand, _NOT)}", _NOT
        if isinstance(expr, BoolOp):
            level = _LEVEL[expr.op]
            return f"{sub(expr.left, level)} {expr.op} {sub(expr.right, level)}", level
        if isinstance(expr, Compare):
            if expr.op in ("==", "!=") and (self._is_real(expr.left) or self._is_real(expr.right)):
                raise ModelicaGenerationError(
                    f"{where}: {expr.op!r} on a Real is not allowed in a Modelica condition; "
                    "the IR must state a threshold with <, <=, > or >=")
            return (f"{sub(expr.left, _OPERAND)} {_OPERATORS[expr.op]} "
                    f"{sub(expr.right, _OPERAND)}"), _COMPARE
        raise ModelicaGenerationError(f"{where}: unsupported expression {expr!r}")

    def _edge(self, event_id: str) -> str:
        event = self.events[event_id]
        port = self.connector[event.port]
        return f"edge({port})" if event.edge == "rising" else f"not {port} and pre({port})"

    # --- statements ---

    def _actions(self, texts: list[str], source: str, skip_timers: bool = False) -> list[str]:
        out: list[str] = []
        for action in map(parse_action, texts):
            if action.verb == "start_timer":
                if skip_timers:
                    continue
                tid = action.args[0]
                duration = self._param_name(self.timer[tid].duration, f"timer {tid!r}")
                out.append(f"{self.deadline[tid]} := time + {duration};")
            elif action.verb == "save_history":
                out.append(f"{HISTORY_VAR} := State.{self.literal[source]};")
                for tid in self.timers_of.get(source, []):
                    out.append(f"{self.remaining[tid]} := {self.deadline[tid]} - time;")
            elif action.verb == "clear_history":
                out.append(f"{HISTORY_VAR} := State.{self.literal[self.sm.initial]};")
        return out

    def _history_return(self) -> list[str]:
        out = [f"{STATE_VAR} := {HISTORY_VAR};"]
        for s in self.sm.states:
            restore = [f"{self.deadline[tid]} := time + {self.remaining[tid]};"
                       for tid in self.timers_of.get(s.id, [])]
            restore += self._actions(s.entry_actions, s.id, skip_timers=True)
            if restore:
                out.append(f"if {HISTORY_VAR} == State.{self.literal[s.id]} then "
                           f"{' '.join(restore)} end if;")
        return out

    def _transition(self, t) -> TransitionView:
        where = f"transition {t.id!r}"
        parts = []
        if t.trigger is not None:
            parts.append(self._edge(t.trigger))
        if t.guard is not None:
            guard = parse_expression(t.guard)
            parts.append(self.expression(guard, where, f"pre({STATE_VAR})",
                                         _LEVEL["and"] if parts else 0))
        names = {s.id: s.name for s in self.sm.states}
        target = names.get(t.to, t.to)
        statements = [f"// IR {t.id}: {one_line(names[t.from_])} -> {one_line(target)}"]
        statements += self._actions(t.actions, t.from_)
        if t.to == HISTORY:
            statements += self._history_return()
        else:
            statements.append(f"{STATE_VAR} := State.{self.literal[t.to]};")
            state = next(s for s in self.sm.states if s.id == t.to)
            statements += self._actions(state.entry_actions, t.to)
        return TransitionView(" and ".join(parts) or "true", statements)

    def _when_conditions(self) -> list[str]:
        conditions: list[str] = []
        triggers = {t.trigger for t in self.sm.transitions if t.trigger is not None}
        conditions += [self._edge(e.id) for e in self.sm.events if e.id in triggers]
        for sid in self.states:
            for t in self._outgoing(sid):
                if t.trigger is not None:
                    continue
                cond = f"pre({STATE_VAR}) == State.{self.literal[sid]}"
                if t.guard is not None:
                    guard = self.expression(parse_expression(t.guard), f"transition {t.id!r}",
                                            f"pre({STATE_VAR})", _LEVEL["and"])
                    cond += f" and {guard}"
                conditions.append(cond)
        return list(dict.fromkeys(conditions))

    def _outgoing(self, sid: str):
        return sorted((t for t in self.sm.transitions if t.from_ == sid), key=lambda t: t.priority)

    # --- outputs and invariants ---

    def _outputs(self) -> list[str]:
        out: list[str] = []
        for port in self.owner.ports:
            if port.direction != "out":
                continue
            name = self.connector[port.id]
            if port.domain == "signal_bool":
                on = []
                for s in self.sm.states:
                    value = s.outputs.get(port.id, False)
                    if not isinstance(value, bool):
                        raise ModelicaGenerationError(
                            f"state {s.id!r}: Boolean output {port.id!r} is given {value!r}")
                    if value:
                        on.append(f"{STATE_VAR} == State.{self.literal[s.id]}")
                out.append(f"{name} = {' or '.join(on) or 'false'};")
            elif port.domain == "signal_real":
                values = []
                for s in self.sm.states:
                    value = s.outputs.get(port.id)
                    if value is None or isinstance(value, bool):
                        raise ModelicaGenerationError(
                            f"Real output {port.id!r} has no numeric value in state {s.id!r}; "
                            "every state must give one")
                    values.append((s.id, number(value)))
                expr = values[-1][1]
                if len(values) > 1:
                    arms = " elseif ".join(f"{STATE_VAR} == State.{self.literal[sid]} then {v}"
                                           for sid, v in values[:-1])
                    expr = f"if {arms} else {expr}"
                out.append(f"{name} = {expr};")
            else:
                raise ModelicaGenerationError(
                    f"state machine {self.sm.id!r}: output port {port.id!r} has domain "
                    f"{port.domain}, which a controller cannot drive")
        return out

    def _asserts(self) -> tuple[list[str], list[str]]:
        lines, asserted = [], []
        for ac in invariants(self.m):
            saved = set(self.used_params)
            try:
                cond = self.expression(parse_expression(ac.check.condition),
                                       f"criterion {ac.id!r}", STATE_VAR)
            except ModelicaGenerationError as exc:
                self.used_params = saved
                self.not_asserted[ac.id] = str(exc)
                continue
            lines.append(f"assert({cond}, {string(f'{ac.id}: {ac.text}')});")
            asserted.append(ac.id)
        return lines, asserted

    # --- the class ---

    def _declarations(self) -> list[str]:
        decls = []
        for port in self.owner.ports:
            key = (port.domain, port.direction)
            if key not in _CONNECTORS:
                raise ModelicaGenerationError(
                    f"part {self.owner.id!r}: port {port.id!r} ({port.direction} {port.domain}) "
                    "has no controller connector; controllers take real and Boolean signals")
            unit = f'(unit = "{port.unit}")' if port.unit and port.domain == "signal_real" else ""
            decls.append(f"{_CONNECTORS[key]} {self.connector[port.id]}{unit} "
                         f"{string(f'[IR {port.id}]')};")
        for pid in sorted(self.used_params):
            p = self.params[pid]
            decls.append(f'parameter Real {modelica_name(pid)}(unit = "{p.unit}") '
                         f"{string(f'[IR {pid}]')};")
        initial = self.literal[self.sm.initial]
        decls.append(f"State {STATE_VAR}(start = State.{initial}, fixed = true) "
                     '"Active state";')
        decls.append(f"State {HISTORY_VAR}(start = State.{initial}, fixed = true) "
                     '"State a history return goes back to";')
        for t in self.sm.timers:
            decls.append(f"discrete Real {self.deadline[t.id]}(start = Modelica.Constants.inf, "
                         f"fixed = true) {string(f'Time the timer expires [IR {t.id}]')};")
            decls.append(f"discrete Real {self.remaining[t.id]}(start = 0, fixed = true) "
                         f"{string(f'Time left when frozen [IR {t.id}]')};")
        return decls

    def view(self) -> tuple[ControllerView, list[str]]:
        conditions = self._when_conditions()
        branches = [BranchView(self.literal[sid], [self._transition(t) for t in self._outgoing(sid)])
                    for sid in self.states if self._outgoing(sid)]
        asserts, asserted = self._asserts()
        equations = self._outputs() + asserts
        literals = [f"{self.literal[s.id]} {string(s.name)}" for s in self.sm.states]
        description = string(f"State machine {self.sm.id} of {self.owner.name} [IR {self.sm.id}]")
        view = ControllerView(class_name(self.sm), description,
                              assumption_comments(self.m, self.sm.id, self.sm.assumption_ids),
                              literals, self._declarations(), conditions, branches, equations)
        return view, asserted


def _environment() -> jinja2.Environment:
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)),
                              undefined=jinja2.StrictUndefined, autoescape=False,
                              trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)


def render_controller(sm: StateMachine, model: SystemModel) -> RenderedController:
    """The controller class for `sm`; the same IR always gives the same text."""
    builder = _Controller(sm, model)
    view, asserted = builder.view()
    text = _environment().get_template("controller.mo.j2").render(c=view)
    return RenderedController(view.class_name, text,
                              sorted(modelica_name(p) for p in builder.used_params), asserted,
                              builder.not_asserted)
