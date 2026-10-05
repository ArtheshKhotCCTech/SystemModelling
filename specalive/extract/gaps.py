# Purpose: gaps and honesty (FR-04 requirements 13-16). Missing values are filled only through an
# explicit convention rule list or the catalogue's defaults, each producing a declared Assumption;
# a required value with neither becomes a Question and a missing-information entry. Simplifications
# a source states become traced Assumptions. The honesty gate then removes every element with no
# trace and no assumption — cascading to whatever referred to it — and never adds a trace.
# Phase 9: a system value whose name ends in a run parameter name (core RUN_PARAMETERS, what the
# generator's experiment reads) is also given that name, with a declared Assumption. An input port
# connected to nothing becomes a Question, so a model that cannot compile says why before omc.
# Phase 10: a source whose id another element has is renamed doc_<id>, references following.
# A one-parameter kind's single stated value under another name is that parameter (Assumption).
# A run whose length no source states spans the one reference trace (Assumption).
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from specalive.core.catalogue import Catalogue
from specalive.core.ids import make_id
from specalive.core.ir import (
    RUN_PARAMETERS,
    SYSTEM_OWNER,
    Assumption,
    ExpressionError,
    OriginalValue,
    Parameter,
    Question,
    Source,
    TraceLink,
    expression_calls,
    expression_names,
    parse_expression,
)
from specalive.extract.fragments import AssumptionHint, Draft, Found, Rejected, name_key

CATALOGUE_SOURCE_ID = "catalogue"
CONVENTION_CONFIDENCE = 0.8
DEFAULT_CONFIDENCE = 0.6
STATED_CONFIDENCE = 0.9


@dataclass(frozen=True)
class Rule:
    """An engineering convention: for a part of `kind` with no effective `target`, take the value
    of its effective `source` parameter, declaring `text` as the assumption."""

    name: str
    kind: str
    target: str
    source: str
    text: str


CONVENTIONS: tuple[Rule, ...] = (
    Rule(name="initial_level_from_low_level", kind="tank", target="initial_level",
         source="low_level",
         text="No initial level was stated for {part}; it is assumed to start at its stated low "
              "level ({value} {unit})."),
)


def _effective(draft: Draft) -> dict[tuple[str, str], Parameter]:
    return {(p.owner, p.name): p for p in draft.parameters if p.status == "effective"}


def _free_id(draft: Draft, pid: str) -> str:
    taken = draft.ids()
    base, n = pid, 1
    while pid in taken:
        n += 1
        pid = f"{base}_{n}"
    return pid


def apply_conventions(draft: Draft, rules: tuple[Rule, ...] = CONVENTIONS) -> None:
    for rule in rules:
        for part in sorted(draft.parts, key=lambda p: p.id):
            effective = _effective(draft)
            src = effective.get((part.id, rule.source))
            if part.kind != rule.kind or (part.id, rule.target) in effective or src is None:
                continue
            pid = _free_id(draft, f"{part.id}_{rule.target}")
            aid = make_id("as", f"as {rule.name} {part.id}")
            draft.assumptions.append(Assumption(
                id=aid, basis="engineering_convention", affects=[pid],
                confidence=CONVENTION_CONFIDENCE, trace=list(src.trace),
                text=rule.text.format(part=part.id, value=src.original.value,
                                      unit=src.original.unit)))
            draft.parameters.append(src.model_copy(update={
                "id": pid, "name": rule.target, "trace": list(src.trace),
                "assumption_ids": [aid]}))


_RUN_STATUSES = ("effective", "verification_only")


def apply_run_names(draft: Draft) -> list[str]:
    """Give a system value named `<qualifier>_<run parameter>` (simulation_stop_time) the run
    parameter's own name, so the generated experiment uses it; the original stays. Several
    candidates are reported, never chosen between. Returns the missing-information entries."""
    missing: list[str] = []
    for run_name, meaning in RUN_PARAMETERS.items():
        system = [p for p in draft.parameters
                  if p.owner == SYSTEM_OWNER and p.status in _RUN_STATUSES]
        if any(p.name == run_name for p in system):
            continue
        found = sorted((p for p in system if p.name.endswith(f"_{run_name}")), key=lambda p: p.id)
        if len({(str(p.value), p.unit) for p in found}) == 1:
            found = found[:1]  # several statements of one value are not a choice
        if len(found) > 1:
            missing.append(f"{run_name} ({meaning}): several system values could be it "
                           f"({', '.join(p.name for p in found)}); none is used")
            continue
        if not found:
            continue
        src = found[0]
        pid = _free_id(draft, f"{SYSTEM_OWNER}_{run_name}")
        aid = make_id("as", f"as run name {run_name}")
        draft.assumptions.append(Assumption(
            id=aid, basis="engineering_convention", affects=[pid],
            confidence=CONVENTION_CONFIDENCE, trace=list(src.trace),
            text=f"'{src.name}' ({src.original.value} {src.original.unit}) is taken as the run's "
                 f"{run_name}, {meaning}."))
        draft.parameters.append(src.model_copy(update={
            "id": pid, "name": run_name, "trace": list(src.trace), "assumption_ids": [aid]}))
    return missing


_SPAN = re.compile(r"^time span: (\S+) from (\S+) to (\S+)$", re.MULTILINE)
_ROWS = re.compile(r"^rows: (\d+)$", re.MULTILINE)
_SECONDS_COLUMN = re.compile(r"(?:_s|\(s\)|\[s\])$")


def run_span_from_reference(draft: Draft, bundle, source_map: dict[str, str]) -> list[str]:
    """When no source states the run length, the run spans the one reference trace whose time
    column is in seconds: stop_time its end, output_interval its sample spacing, both
    verification-only with an Assumption traced to the trace's summary. Traces that disagree
    are reported, never chosen between. Returns the missing-information entries."""
    stated = {p.name for p in draft.parameters
              if p.owner == SYSTEM_OWNER and p.status in _RUN_STATUSES}
    if "stop_time" in stated:
        return []
    spans = []
    for c in bundle.chunks:
        if c.kind != "data_summary" or c.source_id not in source_map:
            continue
        span, rows = _SPAN.search(c.text), _ROWS.search(c.text)
        if span and _SECONDS_COLUMN.search(span.group(1)):
            spans.append((c, float(span.group(2)), float(span.group(3)),
                          int(rows.group(1)) if rows else None, span.group(0)))
    if not spans:
        return []
    if len({(start, end) for _, start, end, _, _ in spans}) > 1:
        return ["stop_time (the simulated run length): no source states it and the reference "
                "traces span different times; none is used"]
    chunk, start, end, rows, quote = spans[0]
    trace = [TraceLink(source_id=source_map[chunk.source_id], locator=chunk.locator, quote=quote)]
    aid = make_id("as", "as run spans reference")
    values = [("stop_time", end, f"{end:g}")]
    if rows and rows > 1 and "output_interval" not in stated:
        step = (end - start) / (rows - 1)
        values.append(("output_interval", step, f"{step:g}"))
    pids = []
    for name, value, written in values:
        pid = _free_id(draft, f"{SYSTEM_OWNER}_{name}")
        pids.append(pid)
        draft.parameters.append(Parameter(
            id=pid, owner=SYSTEM_OWNER, name=name, value=value, unit="s",
            original=OriginalValue(value=written, unit="s"), status="verification_only",
            authority=source_map[chunk.source_id], trace=trace, assumption_ids=[aid]))
    draft.assumptions.append(Assumption(
        id=aid, basis="inferred", affects=pids, confidence=CONVENTION_CONFIDENCE, trace=trace,
        text=f"No source states the run length; the run is taken to span the reference trace "
             f"({start:g} to {end:g} s" + (f", {rows} rows" if rows else "") + ")."))
    return []


def _ensure_catalogue_source(draft: Draft) -> None:
    if all(s.id != CATALOGUE_SOURCE_ID for s in draft.sources):
        draft.sources.append(Source(id=CATALOGUE_SOURCE_ID, path=None, role="other",
                                    title="SpecAlive component catalogue "
                                          "(catalogue/components.yaml)"))


def apply_catalogue(draft: Draft, catalogue: Catalogue) -> list[str]:
    """Fill absent catalogue defaults, each with its assumption; ask for required values that have
    no default. Returns the missing-information entries."""
    missing: list[str] = []
    for part in sorted(draft.parts, key=lambda p: p.id):
        if part.kind not in catalogue:
            continue
        entry = catalogue.entry(part.kind)
        effective = _effective(draft)
        for name, default in sorted(entry.defaults.items()):
            if (part.id, name) in effective:
                continue
            _ensure_catalogue_source(draft)
            pid = _free_id(draft, f"{part.id}_{name}")
            aid = make_id("as", f"as default {part.id} {name}")
            draft.assumptions.append(Assumption(id=aid, text=default.assumption, basis="default",
                                                affects=[pid], confidence=DEFAULT_CONFIDENCE))
            draft.parameters.append(Parameter(
                id=pid, owner=part.id, name=name, value=default.value, unit=default.unit,
                original=OriginalValue(value=f"{default.value:g}", unit=default.unit),
                status="effective", authority=CATALOGUE_SOURCE_ID, assumption_ids=[aid]))
        for name in entry.required:
            if (part.id, name) in effective or name in entry.defaults:
                continue
            if _adopt_only_value(draft, part, name, entry.modelica.parameters):
                continue
            draft.questions.append(Question(
                id=make_id("q", f"q missing {part.id} {name}"),
                text=f"No source gives {name} for {part.name} ({part.id}), which a {part.kind} "
                     "requires, and the catalogue has no default. What is its value?",
                affects=[part.id]))
            missing.append(f"{part.id}.{name}: required by kind {part.kind}; no source gives it "
                           "and the catalogue has no default")
    return missing


def _adopt_only_value(draft: Draft, part, name: str, mapped: dict[str, str]) -> bool:
    """For a kind that maps a single parameter: the part's one effective value under a name the
    kind does not know is that parameter, declared as an Assumption. Two or more such values, or
    a kind with several parameters, are left to the Question."""
    if list(mapped) != [name]:
        return False
    others = [p for p in draft.parameters if p.owner == part.id and p.status == "effective"
              and p.name not in mapped]
    if len({p.name for p in others}) != 1 or len(others) != 1:
        return False
    src = others[0]
    aid = make_id("as", f"as only value {part.id} {name}")
    draft.assumptions.append(Assumption(
        id=aid, basis="inferred", affects=[src.id], confidence=CONVENTION_CONFIDENCE,
        trace=list(src.trace),
        text=f"{part.id} is a {part.kind}, whose only parameter is {name}; its one stated value, "
             f"'{src.name}' ({src.original.value} {src.original.unit}), is taken as it."))
    draft.parameters.append(src.model_copy(update={
        "id": _free_id(draft, f"{part.id}_{name}"), "name": name, "trace": list(src.trace),
        "assumption_ids": [*src.assumption_ids, aid]}))
    return True


def hint_assumptions(hints: list[Found[AssumptionHint]],
                     lookup: Callable[[str], str | None]) -> list[Assumption]:
    """Simplifications the sources state, as Assumptions traced to where they are stated."""
    by_text: dict[str, Assumption] = {}
    for f in hints:
        frag = f.fragment
        affects = sorted({pid for pid in (lookup(name_key(t)) for t in frag.affects_tags) if pid})
        existing = by_text.get(frag.text.strip())
        if existing is not None:
            existing.affects = sorted(set(existing.affects) | set(affects))
            if f.trace not in existing.trace:
                existing.trace.append(f.trace)
            continue
        by_text[frag.text.strip()] = Assumption(
            id=f"as_stated_{len(by_text) + 1:02d}", text=frag.text.strip(),
            basis="engineering_convention", affects=affects, confidence=STATED_CONFIDENCE,
            trace=[f.trace])
    return list(by_text.values())


def missing_documents(sources: list[Source], unresolved: set[str]) -> list[str]:
    out = []
    for s in sorted(sources, key=lambda s: s.id):
        if s.path is None and s.id != CATALOGUE_SOURCE_ID:
            name = s.tags[0] if s.tags else s.title
            out.append(f"{name} ({s.role}) is cited by the evidence, but the bundle does not "
                       "contain it; it is known only from the rows that cite it")
    for tag in sorted(unresolved):
        out.append(f"{tag} is named as a value's source, but the bundle neither contains nor "
                   "describes it")
    return out


def unconnected_inputs(draft: Draft) -> list[Question]:
    """A Question for each input port connected to nothing: its value is then undetermined and
    the Modelica model cannot compile, so the gap is named before omc is run. Never wired here."""
    connected = {c.to_port for c in draft.connections} | {c.from_port for c in draft.connections}
    out = []
    for part in sorted(draft.parts, key=lambda p: p.id):
        name = part.tags[0] if part.tags else part.name
        for port in sorted(part.ports, key=lambda q: q.id):
            if port.direction != "in" or port.id in connected:
                continue
            out.append(Question(
                id=make_id("q", f"q unconnected {port.id}"), affects=[part.id],
                text=f"Input {port.role} ({port.id}) of {name} ({part.id}) is connected to "
                     "nothing, so the model cannot be completed. What drives it?"))
    return out


_GROUPS = ("parts", "connections", "parameters", "state_machines", "requirements",
           "acceptance_criteria", "assumptions", "questions", "conflicts")


def _rewrite_source(node, old: str, new: str) -> None:
    """Every reference to source `old` under `node` (a trace, a parameter's authority, a
    conflict candidate) now names `new`."""
    if isinstance(node, BaseModel):
        for name in type(node).model_fields:
            value = getattr(node, name)
            if name in ("source_id", "authority") and value == old:
                setattr(node, name, new)
            else:
                _rewrite_source(value, old, new)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _rewrite_source(item, old, new)
    elif isinstance(node, dict):
        for item in node.values():
            _rewrite_source(item, old, new)


def unique_ids(draft: Draft) -> list[str]:
    """Ids are unique across every element kind. A source whose id another element has (a cited
    record named like a part, a document numbered like one of its requirements) becomes
    doc_<id>, and every reference to it follows; parts and requirements keep theirs, since
    everything else points at them. Returns a note per rename."""
    sources, draft.sources = draft.sources, []
    others = draft.ids()
    draft.sources = sources
    taken = others | {s.id for s in sources}
    notes = []
    for src in sorted(sources, key=lambda s: s.id):
        if src.id not in others:
            continue
        new, n = make_id("doc", f"doc {src.id}"), 2
        while new in taken:
            new, n = make_id("doc", f"doc {src.id} {n}"), n + 1
        taken.add(new)
        old, src.id = src.id, new
        for group in _GROUPS:
            _rewrite_source(getattr(draft, group), old, new)
        notes.append(f"source {old} shares its id with another element; it is {new}")
    return notes


# --- honesty gate --------------------------------------------------------------------------

def _traced(element) -> bool:
    return bool(element.trace or getattr(element, "assumption_ids", None))


def _expression_ok(text: str, operands: set[str], timers: set[str], states: set[str]) -> bool:
    try:
        expr = parse_expression(text)
    except ExpressionError:
        return False
    calls_ok = all(c.arg in (timers if c.func == "timer_expired" else states)
                   for c in expression_calls(expr))
    return expression_names(expr) <= operands and calls_ok


def _machine_ok(sm, operands: set[str]) -> bool:
    timers = {t.id for t in sm.timers}
    states = {s.id for s in sm.states}
    guards = [t.guard for t in sm.transitions if t.guard]
    if not all(_expression_ok(g, operands, timers, states) for g in guards):
        return False
    return all(t.duration in operands for t in sm.timers)


def honesty_gate(draft: Draft) -> list[Rejected]:
    """Remove every element with neither a trace nor an assumption, and whatever depended on a
    removed element; return what was removed and why. Never adds a trace."""
    rejected: list[Rejected] = []

    def reject(kind: str, eid: str, reason: str) -> None:
        rejected.append(Rejected(kind=kind, id=eid, reason=reason))

    untraced = "no trace and no assumption"
    kept_parts = []
    for p in draft.parts:
        if _traced(p):
            kept_parts.append(p)
        else:
            reject("part", p.id, untraced)
    draft.parts = kept_parts
    part_ids = {p.id for p in draft.parts}
    port_ids = {q.id for p in draft.parts for q in p.ports}

    kept = []
    for c in draft.connections:
        if not _traced(c):
            reject("connection", c.id, untraced)
        elif c.from_port not in port_ids or c.to_port not in port_ids:
            reject("connection", c.id, "an end belonged to a removed part")
        else:
            kept.append(c)
    draft.connections = kept

    kept = []
    for p in draft.parameters:
        if not _traced(p):
            reject("parameter", p.id, untraced)
        elif p.owner != SYSTEM_OWNER and p.owner not in part_ids:
            reject("parameter", p.id, f"its owner {p.owner!r} was removed")
        else:
            kept.append(p)
    draft.parameters = kept
    operands = port_ids | {p.id for p in draft.parameters}

    kept = []
    for sm in draft.state_machines:
        if not _traced(sm):
            reject("state machine", sm.id, untraced)
        elif sm.owner not in part_ids or not _machine_ok(sm, operands):
            reject("state machine", sm.id, "it refers to a removed element")
        else:
            kept.append(sm)
    draft.state_machines = kept

    kept = []
    for r in draft.requirements:
        if _traced(r):
            kept.append(r)
        else:
            reject("requirement", r.id, untraced)
    draft.requirements = kept

    timers = {t.id for sm in draft.state_machines for t in sm.timers}
    states = {s.id for sm in draft.state_machines for s in sm.states}
    kept = []
    for ac in draft.acceptance_criteria:
        if not ac.trace:
            reject("acceptance criterion", ac.id, "no trace")
            continue
        if ac.check is not None and not _expression_ok(ac.check.condition, operands, timers,
                                                       states):
            ac.check = None
            ac.reason = "Its check referred to an element the honesty gate removed."
        kept.append(ac)
    draft.acceptance_criteria = kept

    ids = draft.ids()
    for r in draft.requirements:
        r.satisfied_by = [e for e in r.satisfied_by if e in ids]
    for record in (*draft.assumptions, *draft.questions):
        record.affects = [e for e in record.affects if e in ids]
    kept = []
    for c in draft.conflicts:
        if c.subject.element_id not in ids:
            reject("conflict", c.id, f"its subject {c.subject.element_id!r} was removed")
            continue
        for cand in c.candidates:
            if cand.element_id is not None and cand.element_id not in ids:
                cand.element_id = None
        kept.append(c)
    draft.conflicts = kept
    return rejected
