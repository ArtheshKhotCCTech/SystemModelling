# Purpose: evaluates each IR acceptance criterion on the simulation result. A check's condition is
# parsed by the IR expression language and read row by row from the trace: ports through the
# variable map, parameters as their IR values, in_state() through the controller's state variable.
# Modes: `at` (the value just after any event at that time), `always` (first violation reported)
# and `eventually` over [start, end). Anything that cannot be read is NOT CHECKED with the reason,
# never a pass; an interlock assert that stopped the run fails its criterion with time and message.
from __future__ import annotations

from dataclasses import dataclass

from specalive.core.ir import (
    AcceptanceCriterion,
    BoolLit,
    BoolOp,
    Call,
    Compare,
    Expr,
    Name,
    Not,
    Number,
    SystemModel,
    parse_expression,
)
from specalive.toolchain.omc import AssertionStop
from specalive.verify.simulate import Trace, VariableMap

PASS, FAIL, NOT_CHECKED = "PASS", "FAIL", "NOT CHECKED"
_USABLE = ("effective", "verification_only")
_BOOL_DOMAINS = ("signal_bool", "event")


@dataclass(frozen=True)
class CriterionResult:
    id: str
    tags: list[str]
    text: str
    status: str  # PASS | FAIL | NOT_CHECKED
    detail: str
    check: dict | None
    time: float | None = None  # when it failed, or when an `eventually` was first met


class _Unchecked(Exception):
    """The condition reads something the result cannot supply."""


def _eps(t: float) -> float:
    # omc places events a few 1e-8 s after the nominal instant; this absorbs that, not a tolerance.
    return 1e-6 * max(1.0, abs(t))


class _Reader:
    """Evaluates one parsed condition at a row of the trace."""

    def __init__(self, model: SystemModel, trace: Trace, vm: VariableMap) -> None:
        self.trace, self.vm = trace, vm
        self.bool_ports = {q.id for p in model.parts for q in p.ports if q.domain in _BOOL_DOMAINS}
        self.params = {p.id: p.value for p in sorted(model.parameters, key=lambda p: p.status)
                       if p.status in _USABLE}
        self.machine_of = {s.id: sm.id for sm in model.state_machines for s in sm.states}

    def check_names(self, expr: Expr) -> None:
        """Raise _Unchecked before any row is read, so the reason names the operand."""
        if isinstance(expr, Name):
            self._series(expr.id)
        elif isinstance(expr, Call):
            self._state_series(expr)
        elif isinstance(expr, Not):
            self.check_names(expr.operand)
        elif isinstance(expr, BoolOp | Compare):
            self.check_names(expr.left)
            self.check_names(expr.right)

    def _series(self, name: str) -> list[float] | float:
        if name in self.vm.ports:
            variable = self.vm.ports[name]
            if variable not in self.trace.values:
                raise _Unchecked(f"{name} ({variable}) is not in the simulation result")
            return self.trace.values[variable]
        if name in self.params:
            value = self.params[name]
            if isinstance(value, list):
                raise _Unchecked(f"parameter {name} is a list, not a value a condition can read")
            return float(value)
        raise _Unchecked(f"{name} has no variable in the model")

    def _state_series(self, call: Call) -> tuple[list[float], int]:
        if call.func != "in_state":
            raise _Unchecked(f"{call.func}({call.arg}) reads a timer internal to the generated "
                             "controller, which the result does not name")
        machine = self.machine_of.get(call.arg)
        state = self.vm.states.get(machine) if machine else None
        if state is None or state.variable not in self.trace.values:
            raise _Unchecked(f"in_state({call.arg}): the result holds no state variable of its "
                             "machine")
        return self.trace.values[state.variable], state.states.index(call.arg) + 1

    def value(self, expr: Expr, row: int):
        if isinstance(expr, Number):
            return expr.value
        if isinstance(expr, BoolLit):
            return expr.value
        if isinstance(expr, Name):
            series = self._series(expr.id)
            if isinstance(series, float):
                return series
            return series[row] > 0.5 if expr.id in self.bool_ports else series[row]
        if isinstance(expr, Call):
            series, index = self._state_series(expr)
            return int(round(series[row])) == index
        if isinstance(expr, Not):
            return not self.value(expr.operand, row)
        if isinstance(expr, BoolOp):
            left = self.value(expr.left, row)
            if expr.op == "and":
                return bool(left) and bool(self.value(expr.right, row))
            return bool(left) or bool(self.value(expr.right, row))
        if isinstance(expr, Compare):
            a, b = self.value(expr.left, row), self.value(expr.right, row)
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b,
                    "!=": a != b}[expr.op]
        raise _Unchecked(f"unsupported expression {expr!r}")


def _window_rows(times: list[float], start: float, end: float | None) -> list[int]:
    """Rows in [start, end): at `start` only the last row (after its events); none at `end`."""
    rows = [i for i, t in enumerate(times)
            if t > start + _eps(start) and (end is None or t < end - _eps(end))]
    at_start = [i for i, t in enumerate(times) if abs(t - start) <= _eps(start)]
    before = [i for i, t in enumerate(times) if t < start - _eps(start)]
    first = at_start[-1:] or before[-1:]  # the value in force at `start`
    return first + rows


def _result(ac: AcceptanceCriterion, status: str, detail: str,
            time: float | None = None) -> CriterionResult:
    check = ac.check.model_dump() if ac.check is not None else None
    return CriterionResult(ac.id, list(ac.tags), ac.text, status, detail, check, time)


def _evaluate(ac: AcceptanceCriterion, reader: _Reader, trace: Trace,
              complete: bool, stop_note: str) -> CriterionResult:
    c = ac.check
    expr = parse_expression(c.condition)
    try:
        reader.check_names(expr)
    except _Unchecked as exc:
        return _result(ac, NOT_CHECKED, str(exc))
    times = trace.times
    run_start, run_end = times[0], times[-1]
    start = run_start if c.start_s is None else c.start_s
    if start > run_end + _eps(run_end):
        return _result(ac, NOT_CHECKED, f"starts at {start:g} s, after the run ended at "
                                        f"{run_end:g} s{stop_note}")
    if c.mode == "at":
        row = max(i for i, t in enumerate(times) if t <= start + _eps(start))
        ok = bool(reader.value(expr, row))
        return (_result(ac, PASS, f"holds at {start:g} s") if ok else
                _result(ac, FAIL, f"does not hold at {start:g} s", start))
    past_end = c.end_s is not None and c.end_s > run_end + _eps(run_end)
    if past_end or (c.end_s is None and not complete):
        end_text = f"{c.end_s:g} s" if c.end_s is not None else "the end of the run"
        return _result(ac, NOT_CHECKED, f"the window runs to {end_text}, but the run ended at "
                                        f"{run_end:g} s{stop_note}")
    rows = _window_rows(times, start, c.end_s)
    if not rows:
        return _result(ac, NOT_CHECKED, "no simulation samples inside the window")
    window = (f"[{start:g}, {c.end_s:g}) s" if c.end_s is not None
              else f"[{start:g} s, end of run]")
    for i in rows:
        holds = bool(reader.value(expr, i))
        t = max(times[i], start)
        if c.mode == "always" and not holds:
            return _result(ac, FAIL, f"violated at {t:g} s (window {window})", t)
        if c.mode == "eventually" and holds:
            return _result(ac, PASS, f"first holds at {t:g} s (window {window})", t)
    if c.mode == "always":
        return _result(ac, PASS, f"holds at all {len(rows)} samples in {window}")
    return _result(ac, FAIL, f"never holds in {window}")


def evaluate_criteria(model: SystemModel, trace: Trace | None, vm: VariableMap, *,
                      complete: bool = True, assertion: AssertionStop | None = None,
                      not_run_reason: str | None = None) -> list[CriterionResult]:
    """One result per IR acceptance criterion, sorted by id. `complete` is False when the run
    stopped early; an `assertion` that names a criterion (its message starts `<id>:`) fails it."""
    complete = complete and assertion is None
    stop_note = (f" (stopped by an assertion at {assertion.time:g} s)" if assertion else "")
    results = []
    for ac in sorted(model.acceptance_criteria, key=lambda a: a.id):
        if assertion is not None and assertion.message.startswith(f"{ac.id}:"):
            results.append(_result(ac, FAIL, f"interlock assert stopped the simulation at "
                                             f"{assertion.time:g} s: {assertion.message}",
                                   assertion.time))
        elif ac.check is None:
            results.append(_result(ac, NOT_CHECKED, ac.reason or "no machine-checkable form"))
        elif trace is None or not trace.times:
            results.append(_result(ac, NOT_CHECKED, "not evaluated: "
                                   f"{not_run_reason or 'there is no simulation result'}"))
        else:
            results.append(_evaluate(ac, _Reader(model, trace, vm), trace, complete, stop_note))
    return results
