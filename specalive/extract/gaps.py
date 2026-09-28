# Purpose: gaps and honesty (FR-04 requirements 13-16). Missing values are filled only through an
# explicit convention rule list or the catalogue's defaults, each producing a declared Assumption;
# a required value with neither becomes a Question and a missing-information entry. Simplifications
# a source states become traced Assumptions. The honesty gate then removes every element with no
# trace and no assumption — cascading to whatever referred to it — and never adds a trace.
# Phase 9: a system value whose name ends in a run parameter name (core RUN_PARAMETERS, what the
# generator's experiment reads) is also given that name, with a declared Assumption.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
            draft.questions.append(Question(
                id=make_id("q", f"q missing {part.id} {name}"),
                text=f"No source gives {name} for {part.name} ({part.id}), which a {part.kind} "
                     "requires, and the catalogue has no default. What is its value?",
                affects=[part.id]))
            missing.append(f"{part.id}.{name}: required by kind {part.kind}; no source gives it "
                           "and the catalogue has no default")
    return missing


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
