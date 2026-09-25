# Purpose: compares the simulation with the reference trace the inputs supply. Each reference column
# is mapped to an IR element: a column of state names to the machine whose states they are, else by
# tag alias to one part, then by port role or connector name to one port, with the unit suffix
# checked; anything unmatched or ambiguous is NOT COMPARED with the reason. Continuous signals are
# compared by error at the reference sample times, discrete signals and states by their change
# times matched in order, within tolerances whose source (the IR or a declared default) is stated.
from __future__ import annotations

import bisect
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from specalive.config import Settings
from specalive.core.ir import SYSTEM_OWNER, Part, Port, StateMachine, SystemModel
from specalive.core.units import UnknownUnit, to_si
from specalive.verify.coverage import alias_key
from specalive.verify.simulate import Trace, VariableMap, VerifyInputError

PASS, FAIL, NOT_COMPARED, MAPPED = "PASS", "FAIL", "NOT COMPARED", "mapped"
EVIDENCE_FILE = "evidence.json"
REFERENCE_ROLE = "reference_data"
_TIME_NAMES = ("time", "t")
_DISCRETE_DOMAINS = ("signal_bool", "event")


@dataclass(frozen=True)
class Reference:
    path: Path
    time_column: str
    times: list[float]
    columns: dict[str, list[str]]  # raw cells, so state names survive


@dataclass(frozen=True)
class ColumnMapping:
    column: str
    status: str  # MAPPED | NOT_COMPARED
    kind: str | None  # continuous | discrete | state
    ir_id: str | None  # the port, or the state machine for a state column
    variable: str | None  # the result variable compared against
    reason: str  # how it was matched, or why it was not


@dataclass(frozen=True)
class Tolerance:
    value: float
    unit: str
    source: str
    declared_default: bool


@dataclass(frozen=True)
class Tolerances:
    event_time: Tolerance
    continuous_fraction: Tolerance


@dataclass(frozen=True)
class SignalResult:
    column: str
    variable: str | None
    ir_id: str | None
    kind: str | None
    status: str  # PASS | FAIL | NOT_COMPARED
    detail: str
    numbers: dict = field(default_factory=dict)


# --- the reference ---------------------------------------------------------------------------

def find_reference(run_dir: Path, explicit: Path | None) -> tuple[Path | None, str]:
    """(the reference CSV, how it was found) or (None, why there is none)."""
    if explicit is not None:
        if not Path(explicit).is_file():
            raise VerifyInputError(f"reference {explicit} not found")
        return Path(explicit), "given with --reference"
    evidence_path = Path(run_dir) / EVIDENCE_FILE
    if not evidence_path.is_file():
        return None, f"no {EVIDENCE_FILE} in the run folder and no --reference given"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{evidence_path} is unreadable ({exc}); give --reference"
    found = sorted((s["path"], s["id"]) for s in evidence.get("sources", [])
                   if s.get("role") == REFERENCE_ROLE and s.get("format") == "csv")
    if not found:
        return None, f"ingestion found no {REFERENCE_ROLE} CSV; give --reference"
    if len(found) > 1:
        names = ", ".join(path for path, _ in found)
        return None, f"several {REFERENCE_ROLE} CSVs ({names}); choose one with --reference"
    path, sid = found[0]
    full = Path(evidence.get("root", "")) / path
    if not full.is_file():
        return None, f"the {REFERENCE_ROLE} source {sid} ({full}) is missing"
    return full, f"ingestion source {sid} with role {REFERENCE_ROLE}"


def load_reference(path: Path) -> Reference:
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [row for row in csv.reader(f) if row]
    except OSError as exc:
        raise VerifyInputError(f"cannot read {path}: {exc.strerror or exc}") from None
    if len(rows) < 2:
        raise VerifyInputError(f"{path} holds no rows")
    header = [h.strip() for h in rows[0]]
    time_index = next((i for i, h in enumerate(header)
                       if h.lower() in _TIME_NAMES or h.lower().split("_")[0] == "time"), None)
    if time_index is None:
        raise VerifyInputError(f"{path} has no time column (a header named time, t or time_<unit>)")
    try:
        times = [float(row[time_index]) for row in rows[1:]]
    except (ValueError, IndexError) as exc:
        raise VerifyInputError(f"{path}: unreadable time value: {exc}") from None
    columns = {h: [row[i].strip() if i < len(row) else "" for row in rows[1:]]
               for i, h in enumerate(header) if i != time_index}
    return Reference(Path(path), header[time_index], times, columns)


def tolerances(model: SystemModel, settings: Settings) -> Tolerances:
    """The event-time tolerance the IR states (a system-owned verification value with a time unit
    and 'tolerance' in its name), else the declared default; the continuous one is declared."""
    stated = sorted((p for p in model.parameters
                     if p.owner == SYSTEM_OWNER and "tolerance" in p.name and p.unit == "s"
                     and p.status in ("verification_only", "effective")
                     and not isinstance(p.value, list)), key=lambda p: p.id)
    if stated:
        event = Tolerance(float(stated[0].value), "s", f"IR parameter {stated[0].id}", False)
    else:
        event = Tolerance(settings.event_time_tolerance_s, "s",
                          "declared default (SPECALIVE_EVENT_TOLERANCE); the inputs state none",
                          True)
    continuous = Tolerance(settings.continuous_abs_tolerance_frac, "1",
                           "declared default (SPECALIVE_CONTINUOUS_TOLERANCE), a fraction of the "
                           "reference signal's range; the inputs state none", True)
    return Tolerances(event, continuous)


# --- column -> IR element ------------------------------------------------------------------

def _state_lookup(sm: StateMachine) -> dict[str, str]:
    return {alias_key(x): s.id for s in sm.states for x in (s.id, s.name, *s.tags)}


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _si_unit(unit: str) -> str | None:
    try:
        return to_si(1.0, unit)[1]
    except UnknownUnit:
        return None


def _not(column: str, reason: str) -> ColumnMapping:
    return ColumnMapping(column, NOT_COMPARED, None, None, None, reason)


def _map_states(column: str, values: set[str], model: SystemModel,
                vm: VariableMap) -> ColumnMapping:
    machines = [sm for sm in sorted(model.state_machines, key=lambda m: m.id)
                if {alias_key(v) for v in values} <= set(_state_lookup(sm))]
    if len(machines) != 1:
        reason = ("its values are not the state names of any state machine" if not machines else
                  "its values fit several state machines: " + ", ".join(m.id for m in machines))
        return _not(column, reason)
    sm = machines[0]
    if sm.id not in vm.states:
        return _not(column, f"state machine {sm.id} has no state variable in the model")
    return ColumnMapping(column, MAPPED, "state", sm.id, vm.states[sm.id].variable,
                         f"values are state names of {sm.id}")


def _port_tokens(port: Port, vm: VariableMap) -> set[str]:
    tokens = {alias_key(t) for t in port.role.split("_")} | {alias_key(port.role)}
    variable = vm.ports.get(port.id)
    if variable:
        connector = variable.rsplit(".", 1)[-1]
        tokens |= {alias_key(connector)} | {alias_key(t) for t in connector.split("_")}
    return tokens - {""}


def _choose_port(part: Part, rest: list[str], vm: VariableMap) -> tuple[Port | None, str]:
    if rest:
        scored = sorted(((len(set(rest) & _port_tokens(q, vm)), q.id, q) for q in part.ports),
                        key=lambda s: (-s[0], s[1]))
        if scored and scored[0][0] > 0:
            best = [s for s in scored if s[0] == scored[0][0]]
            if len(best) > 1:
                return None, ("ports " + ", ".join(s[1] for s in best) + f" fit {'_'.join(rest)} "
                              "equally")
            return best[0][2], f"port {best[0][1]} by role or connector '{'_'.join(rest)}'"
    outputs = [q for q in part.ports if q.direction == "out" and q.domain != "fluid"]
    if len(outputs) == 1:
        return outputs[0], f"port {outputs[0].id}, the part's only signal output"
    return None, f"no port of {part.id} fits '{'_'.join(rest) or _ports_hint(part)}'"


def _ports_hint(part: Part) -> str:
    return f"(ports {', '.join(q.id for q in part.ports)})"


def _map_by_name(column: str, model: SystemModel, vm: VariableMap) -> ColumnMapping:
    raw = [t for t in column.replace("-", "_").split("_") if t.strip()]
    unit = None
    if len(raw) > 1 and _si_unit(raw[-1]) is not None:
        unit, raw = raw[-1], raw[:-1]
    tokens = [alias_key(t) for t in raw if alias_key(t)]
    hits = []
    for part in sorted(model.parts, key=lambda p: p.id):
        keys = {alias_key(x) for x in (part.id, part.name, *part.tags)} - {""}
        matched = [t for t in tokens if t in keys]
        if matched:
            hits.append((len(matched), part, matched))
    if not hits:
        return _not(column, "no part's id, name or tag appears in the column name")
    top = max(h[0] for h in hits)
    best = [h for h in hits if h[0] == top]
    if len(best) > 1:
        return _not(column, "ambiguous: parts " + ", ".join(h[1].id for h in best) +
                    " all match the column name")
    _, part, matched = best[0]
    rest = [t for t in tokens if t not in matched]
    port, how = _choose_port(part, rest, vm)
    if port is None:
        return _not(column, f"part {part.id} matched, but {how}")
    if unit is not None and port.unit is not None and _si_unit(unit) != _si_unit(port.unit):
        return _not(column, f"unit {unit!r} of the column does not match {port.id}'s unit "
                            f"{port.unit!r}")
    variable = vm.ports.get(port.id)
    if variable is None:
        return _not(column, f"port {port.id} has no variable in the model")
    kind = "discrete" if port.domain in _DISCRETE_DOMAINS else "continuous"
    return ColumnMapping(column, MAPPED, kind, port.id, variable,
                         f"part {part.id} by alias '{'_'.join(matched)}', {how}")


def map_columns(ref: Reference, model: SystemModel, vm: VariableMap) -> list[ColumnMapping]:
    """One mapping per reference column, in the reference's column order."""
    out = []
    for column, cells in ref.columns.items():
        values = {c for c in cells if c}
        if not values:
            out.append(_not(column, "the column is empty"))
        elif not all(_is_number(v) for v in values):
            out.append(_map_states(column, values, model, vm))
        else:
            out.append(_map_by_name(column, model, vm))
    return out


# --- comparisons -----------------------------------------------------------------------------

def _at(trace_times: list[float], values: list[float], t: float) -> float:
    """Linear interpolation; at an event instant, the value after the event."""
    i = bisect.bisect_right(trace_times, t) - 1
    if i < 0:
        return values[0]
    if i >= len(values) - 1 or trace_times[i] == t:
        return values[i]
    t0, t1 = trace_times[i], trace_times[i + 1]
    return values[i] + (values[i + 1] - values[i]) * (t - t0) / (t1 - t0)


def _hold(trace_times: list[float], values: list[float], t: float) -> float:
    """The value in force at t (after any event at t), for discrete signals."""
    i = bisect.bisect_right(trace_times, t) - 1
    return values[max(i, 0)]


def _changes(times: list[float], values: list) -> list[tuple[float, object]]:
    return [(times[i], values[i]) for i in range(1, len(values)) if values[i] != values[i - 1]]


def _continuous(ref: Reference, m: ColumnMapping, trace: Trace, span, tol: Tolerances):
    series = trace.values[m.variable]
    samples = [(t, float(v)) for t, v in zip(ref.times, ref.columns[m.column])
               if span[0] <= t <= span[1] and v != ""]
    if not samples:
        return NOT_COMPARED, "no reference samples in the common time span", {}
    worst_abs, worst_t, worst_rel = -1.0, None, 0.0
    for t, want in samples:
        err = abs(_at(trace.times, series, t) - want)
        if err > worst_abs:
            worst_abs, worst_t = err, t
        if abs(want) > 1e-12:
            worst_rel = max(worst_rel, err / abs(want))
    ref_values = [v for _, v in samples]
    spread = max(ref_values) - min(ref_values) or max(abs(v) for v in ref_values) or 1.0
    limit = tol.continuous_fraction.value * spread
    numbers = {"max_abs_error": worst_abs, "at_time": worst_t, "max_rel_error": worst_rel,
               "tolerance_abs": limit, "samples": len(samples)}
    status = PASS if worst_abs <= limit else FAIL
    detail = (f"max |error| {worst_abs:.4g} at {worst_t:g} s against a tolerance of {limit:.4g} "
              f"over {len(samples)} reference samples")
    return status, detail, numbers


def _discrete(ref: Reference, m: ColumnMapping, trace: Trace, span, tol: Tolerances,
              model: SystemModel, vm: VariableMap):
    series = trace.values[m.variable]
    if m.kind == "state":
        sm = next(s for s in model.state_machines if s.id == m.ir_id)
        lookup, states = _state_lookup(sm), vm.states[m.ir_id].states

        def ref_value(cell: str):
            return lookup.get(alias_key(cell), cell)

        def sim_value(x: float):
            n = int(round(x))
            return states[n - 1] if 1 <= n <= len(states) else f"<{n}>"
    else:
        def ref_value(cell: str):
            return float(cell) > 0.5

        def sim_value(x: float):
            return x > 0.5

    ref_rows = [(t, ref_value(c)) for t, c in zip(ref.times, ref.columns[m.column])
                if span[0] <= t <= span[1] and c != ""]
    sim_rows = [(t, sim_value(v)) for t, v in zip(trace.times, series) if span[0] <= t <= span[1]]
    if not ref_rows or not sim_rows:
        return NOT_COMPARED, "no samples in the common time span", {}
    ref_changes = _changes([t for t, _ in ref_rows], [v for _, v in ref_rows])
    sim_changes = _changes([t for t, _ in sim_rows], [v for _, v in sim_rows])
    limit = tol.event_time.value
    start_ref, start_sim = ref_rows[0][1], sim_value(_hold(trace.times, series, ref_rows[0][0]))
    pairs, first_bad = [], None
    if start_ref != start_sim:
        first_bad = f"starts at {start_sim} in the model, {start_ref} in the reference"
    for (rt, rv), (st, sv) in zip(ref_changes, sim_changes):
        ok = rv == sv and abs(st - rt) <= limit
        pairs.append({"reference_time": rt, "model_time": st, "value": rv, "model_value": sv,
                      "time_error": abs(st - rt), "ok": ok})
        if not ok and first_bad is None:
            first_bad = (f"change to {rv} at {rt:g} s in the reference, the model changes to {sv} "
                         f"at {st:g} s (|dt| {abs(st - rt):.3g} s, tolerance {limit:g} s)")
    if len(ref_changes) != len(sim_changes) and first_bad is None:
        n = min(len(ref_changes), len(sim_changes))
        extra = (ref_changes[n:] and f"the reference changes to {ref_changes[n][1]} at "
                 f"{ref_changes[n][0]:g} s with no matching model change") or (
                 f"the model changes to {sim_changes[n][1]} at {sim_changes[n][0]:g} s with no "
                 "matching reference change")
        first_bad = extra
    numbers = {"reference_changes": len(ref_changes), "model_changes": len(sim_changes),
               "max_time_error": max((p["time_error"] for p in pairs), default=0.0),
               "tolerance_s": limit, "changes": pairs}
    if first_bad is None:
        return PASS, (f"{len(ref_changes)} changes matched in order, max |dt| "
                      f"{numbers['max_time_error']:.3g} s within {limit:g} s"), numbers
    return FAIL, first_bad, numbers


def compare_signals(ref: Reference, trace: Trace, mappings: list[ColumnMapping],
                    model: SystemModel, vm: VariableMap, tol: Tolerances) -> list[SignalResult]:
    """One result per reference column; `vm` gives the state enumerations for state columns."""
    span = (max(ref.times[0], trace.times[0]) if trace.times else 0.0,
            min(ref.times[-1], trace.times[-1]) if trace.times else 0.0)
    results = []
    for m in mappings:
        if m.status != MAPPED:
            results.append(SignalResult(m.column, None, None, None, NOT_COMPARED, m.reason))
            continue
        if m.variable not in trace.values:
            results.append(SignalResult(m.column, m.variable, m.ir_id, m.kind, NOT_COMPARED,
                                        f"{m.variable} is not in the simulation result"))
            continue
        if m.kind == "state" and m.ir_id not in vm.states:
            results.append(SignalResult(m.column, m.variable, m.ir_id, m.kind, NOT_COMPARED,
                                        f"no state enumeration known for {m.ir_id}"))
            continue
        if m.kind == "continuous":
            status, detail, numbers = _continuous(ref, m, trace, span, tol)
        else:
            status, detail, numbers = _discrete(ref, m, trace, span, tol, model, vm)
        results.append(SignalResult(m.column, m.variable, m.ir_id, m.kind, status, detail,
                                    numbers))
    return results
