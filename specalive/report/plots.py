# Purpose: report/plots/*.png — the simulation drawn so an engineer can see it agree with the
# reference: one figure per signal group (continuous signals per unit, Boolean signals as offset
# step traces, one state step trace per machine), the reference overlaid on every signal that
# verification compared. Without a reference it draws the variable map's outputs and states.
# Signal choice comes from verification.json, values from sim/result.csv and the reference CSV.
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from specalive.core.ir import SystemModel
from specalive.report.artefacts import NOT_RUN, Run
from specalive.verify import compare, simulate
from specalive.verify.coverage import alias_key

PLOTS_DIR = "plots"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Series:
    name: str  # reference column, else IR id
    variable: str  # result variable
    reference: str | None  # reference column overlaid, if any
    ir_id: str | None = None  # the port or state machine it shows


@dataclass(frozen=True)
class Plot:
    file: str
    title: str
    signals: list[str]
    reference: bool
    y_label: str


@dataclass
class PlotsResult:
    status: str  # "ok" | NOT_RUN
    reason: str | None = None
    figures: list[Plot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class _Group:
    kind: str  # continuous | boolean | state
    key: str  # unit, or machine id
    series: list[Series] = field(default_factory=list)


def _ports(model: SystemModel) -> dict:
    return {port.id: port for part in model.parts for port in part.ports}


def _group(groups: dict[str, _Group], kind: str, key: str) -> _Group:
    name = {"continuous": f"continuous_{key}", "boolean": "boolean"}.get(kind, f"state_{key}")
    return groups.setdefault(name, _Group(kind, key))


def _unit_key(unit: str | None) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in unit) if unit else "no_unit"


def _from_signals(verification: dict, model: SystemModel, trace) -> dict[str, _Group]:
    ports, groups = _ports(model), {}
    for s in verification.get("signals") or []:
        if s.get("status") == compare.NOT_COMPARED or s.get("variable") not in trace.values:
            continue
        series = Series(s["column"], s["variable"], s["column"], s.get("ir_id"))
        if s.get("kind") == "state":
            _group(groups, "state", s["ir_id"]).series.append(series)
        elif s.get("kind") == "continuous":
            port = ports.get(s.get("ir_id"))
            _group(groups, "continuous", _unit_key(port.unit if port else None)).series.append(
                series)
        else:
            _group(groups, "boolean", "").series.append(series)
    return groups


def _from_variable_map(verification: dict, model: SystemModel, trace) -> dict[str, _Group]:
    vm = verification.get("variable_map") or {}
    ports, groups = _ports(model), {}
    for port_id, variable in sorted((vm.get("ports") or {}).items()):
        port = ports.get(port_id)
        if port is None or port.direction == "in" or variable not in trace.values:
            continue
        if port.domain == "signal_real":
            _group(groups, "continuous", _unit_key(port.unit)).series.append(
                Series(port_id, variable, None, port_id))
        elif port.domain == "signal_bool":
            _group(groups, "boolean", "").series.append(Series(port_id, variable, None, port_id))
    for machine, state in sorted((vm.get("states") or {}).items()):
        if state.get("variable") in trace.values:
            _group(groups, "state", machine).series.append(
                Series(machine, state["variable"], None))
    return groups


def _reference(verification: dict, notes: list[str]):
    ref = verification.get("reference") or {}
    if ref.get("status") != "ok":
        return None
    try:
        return compare.load_reference(Path(ref["path"]))
    except simulate.VerifyInputError as exc:
        notes.append(f"reference not overlaid: {exc}")
        return None


def _boolean(cell: str) -> float | None:
    text = cell.strip().lower()
    if text in _TRUE:
        return 1.0
    if text in _FALSE:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def _numbers(cells: list[str], parse) -> tuple[list[int], list[float]]:
    rows = [(i, parse(c)) for i, c in enumerate(cells)]
    rows = [(i, v) for i, v in rows if v is not None]
    return [i for i, _ in rows], [v for _, v in rows]


def _float(cell: str) -> float | None:
    try:
        return float(cell)
    except ValueError:
        return None


_REFERENCE = {"color": "black", "linewidth": 1.0}


def _draw(group: _Group, model: SystemModel, trace, ref, target: Path) -> Plot:
    """Simulation in one colour per signal, the reference over it in black (dashed or dots)."""
    from matplotlib.figure import Figure  # object API only: no pyplot global state

    fig = Figure(figsize=(9, 4.5), dpi=100)
    ax = fig.subplots()
    names = [s.name for s in group.series]
    overlays = 0

    def overlay(s: Series, parse, shift: float = 0.0, **style) -> None:
        nonlocal overlays
        if ref is None or s.reference not in ref.columns:
            return
        index, values = _numbers(ref.columns[s.reference], parse)
        label = "reference" if overlays == 0 else None
        xs, ys = [ref.times[i] for i in index], [shift + v for v in values]
        if style.pop("step", False):
            ax.step(xs, ys, where="post", linestyle="--", label=label, **_REFERENCE, **style)
        else:
            ax.plot(xs, ys, linestyle="none", marker=".", markersize=3, label=label,
                    color="black", **style)
        overlays += 1

    if group.kind == "state":
        sm = next(m for m in model.state_machines if m.id == group.key)
        lookup = {alias_key(x): i for i, st in enumerate(sm.states)
                  for x in (st.id, st.name, *st.tags)}
        for k, s in enumerate(group.series):
            ax.step(trace.times, [v - 1 for v in trace.values[s.variable]], where="post",
                    color=f"C{k}", linewidth=2, label=f"simulation ({s.variable})")
            overlay(s, lambda c: lookup.get(alias_key(c)), step=True)
        ax.set_yticks(range(len(sm.states)), [st.name for st in sm.states])
        y_label, title = "state", f"State machine {sm.id}"
    elif group.kind == "boolean":
        for k, s in enumerate(group.series):
            ax.step(trace.times, [1.5 * k + v for v in trace.values[s.variable]], where="post",
                    color=f"C{k}", linewidth=2, label="simulation" if k == 0 else None)
            overlay(s, _boolean, 1.5 * k, step=True)
        ax.set_yticks([1.5 * k + 0.5 for k in range(len(names))], names)
        y_label, title = "Boolean signal (low = false, high = true)", "Boolean signals"
    else:
        ports = [p for p in (_ports(model).get(s.ir_id) for s in group.series) if p]
        roles = sorted({p.role for p in ports})
        unit = next((p.unit for p in ports if p.unit), None)
        for k, s in enumerate(group.series):
            ax.plot(trace.times, trace.values[s.variable], color=f"C{k}", linewidth=2,
                    label=f"{s.name} simulation")
            overlay(s, _float)
        quantity = roles[0] if len(roles) == 1 else "value"
        y_label = f"{quantity} [{unit}]" if unit else f"{quantity} [unit not stated]"
        title = f"Continuous signals [{unit or 'no unit'}]"
    ax.set_xlabel("time [s]")
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize="small")
    fig.tight_layout()
    fig.savefig(target, format="png", metadata={"Software": None})
    return Plot(target.name, title, names, overlays > 0, y_label)


def write_plots(run: Run, plots_dir: Path) -> PlotsResult:
    if not run.verification.ok:
        return PlotsResult(NOT_RUN, run.verification.reason)
    if run.model is None:
        return PlotsResult(NOT_RUN, run.ir.reason)
    result_csv = run.run_dir / simulate.SIM_DIR / simulate.RESULT_FILE
    if not result_csv.is_file():
        return PlotsResult(NOT_RUN, f"{simulate.SIM_DIR}/{simulate.RESULT_FILE} not found; "
                                    "the simulation did not run")
    try:
        trace = simulate.load_result(result_csv)
    except simulate.VerifyInputError as exc:
        return PlotsResult(NOT_RUN, str(exc))
    notes: list[str] = []
    ref = _reference(run.verification.data, notes)
    groups = (_from_signals(run.verification.data, run.model, trace) if ref is not None
              else _from_variable_map(run.verification.data, run.model, trace))
    if not groups:
        return PlotsResult(NOT_RUN, "no simulated signal maps to an IR element", notes=notes)
    plots_dir = Path(plots_dir)
    plots_dir.mkdir(parents=True, exist_ok=True)
    for old in plots_dir.glob("*.png"):
        old.unlink()
    figures = [_draw(g, run.model, trace, ref, plots_dir / f"{name}.png")
               for name, g in sorted(groups.items())]
    return PlotsResult("ok", None, figures, notes)
