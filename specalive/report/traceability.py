# Purpose: traceability.md — the answer to "where did this element come from?" for every IR
# element: its primary source (first trace link), locator, verbatim quote and confidence, the
# assumptions it rests on, or the owner whose trace it inherits (ports from their part, states,
# transitions, events, timers and regions from their machine). Grouped by type, sorted by id.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specalive.core.ir import SystemModel, TraceLink
from specalive.report.artefacts import Run, source_label, table, write_report

REPORT_FILE = "traceability.md"
ASSUMPTION_ONLY = "— (assumption only)"
NO_VALUE = "—"

GROUPS = [("Parts", "parts"), ("Ports", "ports"), ("Connections", "connections"),
          ("Parameters", "parameters"), ("State machines", "state_machines"),
          ("States", "states"), ("Transitions", "transitions"), ("Events", "events"),
          ("Timers", "timers"), ("Regions", "regions"), ("Requirements", "requirements"),
          ("Acceptance criteria", "acceptance_criteria"), ("Assumptions", "assumptions")]
HEADER = ["Id", "Name", "Primary source", "Locator", "Quote", "Confidence", "Assumed"]


@dataclass(frozen=True)
class TraceRow:
    group: str
    id: str
    name: str
    source: str
    locator: str
    quote: str
    confidence: str
    assumed: str


class _Rows:
    def __init__(self, model: SystemModel) -> None:
        self.model = model
        self.affected: dict[str, list[str]] = {}
        for a in model.assumptions:
            for eid in a.affects:
                self.affected.setdefault(eid, []).append(a.id)
        self.rows: list[TraceRow] = []

    def add(self, group: str, element_id: str, name: str, trace: list[TraceLink],
            assumption_ids: list[str] = (), inherits: str | None = None,
            confidence: float | None = None) -> None:
        assumed = sorted({*assumption_ids, *self.affected.get(element_id, [])})
        if trace:
            first = trace[0]
            more = f" (+{len(trace) - 1} more)" if len(trace) > 1 else ""
            source = f"{first.source_id} ({source_label(self.model, first.source_id)})"
            locator, quote = first.locator + more, first.quote
        elif inherits is not None and not assumption_ids:
            source, locator, quote = f"inherits {inherits}", "", ""
        else:
            source, locator, quote = ASSUMPTION_ONLY, "", ""
        self.rows.append(TraceRow(group, element_id, name, source, locator, quote,
                                  NO_VALUE if confidence is None else f"{confidence:g}",
                                  ", ".join(assumed)))


def trace_rows(model: SystemModel) -> list[TraceRow]:
    """One row per IR element, in GROUPS order and sorted by id within a group."""
    r = _Rows(model)
    for p in model.parts:
        r.add("Parts", p.id, p.name, p.trace, p.assumption_ids, confidence=p.confidence)
        for port in p.ports:
            r.add("Ports", port.id, f"{port.role} ({port.direction}, {port.domain})",
                  port.trace, port.assumption_ids, inherits=p.id)
    for c in model.connections:
        r.add("Connections", c.id, f"{c.from_port} → {c.to_port}", c.trace, c.assumption_ids)
    for p in model.parameters:
        value = p.value if isinstance(p.value, list) else f"{p.value:g}"
        r.add("Parameters", p.id, f"{p.owner}.{p.name} = {value} {p.unit} ({p.status})",
              p.trace, p.assumption_ids)
    for sm in model.state_machines:
        r.add("State machines", sm.id, f"owned by {sm.owner}", sm.trace, sm.assumption_ids)
        for s in sm.states:
            r.add("States", s.id, s.name, [], inherits=sm.id)
        for t in sm.transitions:
            r.add("Transitions", t.id, f"{t.from_} → {t.to}", [], inherits=sm.id)
        for e in sm.events:
            r.add("Events", e.id, f"{e.edge} edge of {e.port}", [], inherits=sm.id)
        for t in sm.timers:
            r.add("Timers", t.id, f"duration {t.duration}", [], inherits=sm.id)
        for g in sm.regions:
            r.add("Regions", g.id, g.name, [], inherits=sm.id)
    for q in model.requirements:
        r.add("Requirements", q.id, f"{q.tags[0] if q.tags else q.id} ({q.status})", q.trace,
              q.assumption_ids)
    for ac in model.acceptance_criteria:
        r.add("Acceptance criteria", ac.id, ac.tags[0] if ac.tags else ac.id, ac.trace)
    for a in model.assumptions:
        r.add("Assumptions", a.id, a.basis, a.trace, confidence=a.confidence)
    order = [g for g, _ in GROUPS]
    return sorted(r.rows, key=lambda row: (order.index(row.group), row.id))


def render_traceability(run: Run) -> str:
    model = run.model
    if model is None:
        return f"# Traceability\n\n{run.ir.not_run}\n"
    rows = trace_rows(model)
    traced = sum(1 for row in rows if row.source not in (ASSUMPTION_ONLY,)
                 and not row.source.startswith("inherits "))
    only = sum(1 for row in rows if row.source == ASSUMPTION_ONLY)
    lines = [f"# Traceability — {model.name}", "",
             "Every IR element with the input fragment that justifies it: the first trace link "
             "(`+n more` when there are several), its locator and verbatim quote. `Assumed` lists "
             "the assumptions an element rests on; an element with no trace of its own inherits "
             "its owner's.", "",
             f"{len(rows)} elements: {traced} traced to a source, {only} resting on assumptions "
             f"only, {len(rows) - traced - only} inheriting their owner's trace."]
    for heading, _ in GROUPS:
        group = [row for row in rows if row.group == heading]
        lines += ["", f"## {heading}", ""]
        if not group:
            lines.append("None in the IR.")
            continue
        lines += table(HEADER, [[f"`{row.id}`", row.name, row.source, row.locator, row.quote,
                                 row.confidence, row.assumed] for row in group])
    return "\n".join(lines) + "\n"


def write_traceability(run: Run, out_dir: Path) -> Path:
    return write_report(out_dir, REPORT_FILE, render_traceability(run))
