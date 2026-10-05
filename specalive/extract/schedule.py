# Purpose: a test procedure lists operator commands one row per press ("20 / START"), and a
# requirement may restate them ("START at 20 s"); the LLM reads rows one at a time and never
# assembles a button's press_times. This module does it without the LLM: it matches each button's
# aliases in verification and requirement chunks, collects the times per source, and gives each
# button one verification_only press_times traced to every verbatim match. Disagreeing sources
# become a Question with no value; nothing is guessed. press_times the LLM gave from a quote
# that does not name the button (a sentence about every button) are replaced when a schedule
# names it. Phase 10: a schedule_table part takes its times and values from the one table of
# start-time rows whose title shares a document identifier with the part's own evidence (the
# component row citing "Source: OCC-SCH-04", the sheet titled "... - OCC-SCH-04"); never guessed.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from specalive.core.ids import make_id
from specalive.core.ir import Assumption, OriginalValue, Parameter, Part, Question, TraceLink
from specalive.core.units import UnknownUnit, to_si
from specalive.extract.fragments import name_key
from specalive.extract.precedence import rank_of
from specalive.ingest.evidence import EvidenceBundle

BUTTON_KIND = "command_button"
PARAMETER = "press_times"
# Where a command schedule is stated: the procedure that runs the test, or a requirement on it.
SCHEDULE_ROLES = frozenset({"verification_procedure", "requirement_spec"})
_NUMBER = r"\d+(?:\.\d+)?"
_SECONDS_HEADER = re.compile(r"time\s*[(\[]\s*s\s*[)\]]", re.IGNORECASE)


@dataclass
class Schedules:
    parameters: list[Parameter] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    replaced: list[Parameter] = field(default_factory=list)  # press_times this schedule supersedes
    assumptions: list[Assumption] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    time: float
    quote: str


def _alias(name: str) -> str:
    return rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])"


def _matches(text: str, names: list[str], fields: dict[str, str]) -> list[_Match]:
    """Every press of the button called by one of `names` that the chunk states, in seconds."""
    found: list[_Match] = []
    for name in (n for n in names if n.strip()):
        for m in re.finditer(rf"{_alias(name)}\s+at\s+({_NUMBER})\s*s\b", text, re.IGNORECASE):
            found.append(_Match(m.start(), m.end(), float(m.group(1)), m.group(0)))
        if _SECONDS_HEADER.search(text):  # a table whose time column is in seconds
            pattern = rf"^[ \t]*({_NUMBER})[ \t]*\r?\n[ \t]*{_alias(name)}[ \t]*$"
            for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                found.append(_Match(m.start(), m.end(), float(m.group(1)), m.group(0).strip()))
    times = [v for k, v in fields.items() if _SECONDS_HEADER.search(k)
             and re.fullmatch(_NUMBER, v.strip())]
    if len(times) == 1 and any(v.strip().lower() == n.strip().lower()
                               for k, v in fields.items() for n in names if n.strip()):
        found.append(_Match(0, len(text), float(times[0]), text))
    # "PB-START at 20 s" also contains "START at 20 s": keep the widest match only
    kept = [m for m in found if not any(o != m and o.start <= m.start and m.end <= o.end
                                        and (o.end - o.start) > (m.end - m.start) for o in found)]
    return sorted(set(kept), key=lambda m: m.start)


def _written(times: list[float]) -> str:
    return ", ".join(f"{t:g}" for t in times)


def press_schedules(bundle: EvidenceBundle, parts: list[Part], parameters: list[Parameter],
                    source_map: dict[str, str]) -> Schedules:
    """press_times for every button that has none yet, from the schedules the evidence states."""
    out = Schedules()
    sources = {s.id: s for s in bundle.sources}
    given = {}  # button -> its press_times whose quotes do not name it
    have = set()
    for p in parameters:
        if p.name != PARAMETER:
            continue
        tags = next((q.tags for q in parts if q.id == p.owner), [])
        if any(re.search(_alias(t), link.quote, re.IGNORECASE) for t in tags if t.strip()
               for link in p.trace):
            have.add(p.owner)
        else:
            given.setdefault(p.owner, []).append(p)
    taken = {p.id for p in parameters}
    for part in sorted(parts, key=lambda p: p.id):
        if part.kind != BUTTON_KIND or part.id in have:
            continue
        per_source: dict[str, tuple[set[float], list[TraceLink]]] = {}
        for c in bundle.chunks:
            role = c.role or sources[c.source_id].role
            if role not in SCHEDULE_ROLES or sources[c.source_id].status == "unread":
                continue
            for m in _matches(c.text, part.tags, c.fields):
                times, traces = per_source.setdefault(c.source_id, (set(), []))
                times.add(m.time)
                link = TraceLink(source_id=source_map[c.source_id], locator=c.locator,
                                 quote=m.quote[:300])
                if link not in traces:
                    traces.append(link)
        if not per_source:
            continue
        for old in given.get(part.id, []):
            out.replaced.append(old)
            taken.discard(old.id)
        schedules = {sid: sorted(t) for sid, (t, _) in per_source.items()}
        order = sorted(per_source, key=lambda sid: (rank_of(sources[sid].role), sid))
        if len({tuple(v) for v in schedules.values()}) > 1:
            out.questions.append(Question(
                id=make_id("q", f"q schedule {part.id}"),
                text=f"The sources disagree on when {part.tags[0] if part.tags else part.id} is "
                     "pressed; which schedule applies?",
                options=[f"{_written(schedules[sid])} s ({source_map[sid]})" for sid in order],
                affects=[part.id]))
            continue
        times = schedules[order[0]]
        pid = f"{part.id}_{PARAMETER}"
        if pid in taken:
            pid = make_id("p", f"{part.id} {PARAMETER} schedule")
        out.parameters.append(Parameter(
            id=pid, owner=part.id, name=PARAMETER, value=times, unit="s",
            original=OriginalValue(value=_written(times), unit="s"), status="verification_only",
            authority=source_map[order[0]],
            trace=[t for sid in order for t in per_source[sid][1]]))
    return out


# --- schedule tables ------------------------------------------------------------------------

SCHEDULE_KIND = "schedule_table"
_CLOCK = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?![A-Za-z0-9-])")
_HEADER_UNIT = re.compile(r"\(([^()]+)\)\s*$")
_INDEX_WORDS = ("row", "id", "no", "index", "number")


def _table(locator: str) -> str | None:
    """'sheet X, row 4' -> 'sheet X': the table a row belongs to."""
    head, sep, _ = locator.rpartition(", row ")
    return head if sep else None


def _start_seconds(fields: dict[str, str]) -> tuple[str, float] | None:
    """(written, seconds) of the row's start time: a clock time, or a number in seconds."""
    for header, value in fields.items():
        key = name_key(header)
        if "start" not in key and key not in ("time", "times"):
            continue
        clock = _CLOCK.match(value)
        if clock:
            return value.strip(), int(clock.group(1)) * 3600.0 + int(clock.group(2)) * 60.0
        if _SECONDS_HEADER.search(header) and re.fullmatch(_NUMBER, value.strip()):
            return value.strip(), float(value)
    return None


def _value_column(rows: list[dict[str, str]]) -> str | None:
    """The one numeric column that is not a start/end time or a row number."""
    columns = []
    for header in rows[0]:
        key = name_key(header)
        if "time" in key or any(key.startswith(w) or key.endswith(w) for w in _INDEX_WORDS):
            continue
        if all(re.fullmatch(_NUMBER, r.get(header, "").strip()) for r in rows):
            columns.append(header)
    return columns[0] if len(columns) == 1 else None


def schedule_tables(bundle: EvidenceBundle, parts: list[Part], parameters: list[Parameter],
                    source_map: dict[str, str]) -> Schedules:
    """times and values for every schedule_table part that has neither, from the table its own
    evidence names by a shared document identifier."""
    out = Schedules()
    sources = {s.id: s for s in bundle.sources}
    have = {(p.owner, p.name) for p in parameters}
    by_place = {(source_map.get(c.source_id), c.locator): c for c in bundle.chunks}
    tables: dict[tuple[str, str], dict] = {}
    for c in bundle.chunks:
        if sources[c.source_id].status == "unread":
            continue
        name = _table(c.locator)
        if name is None:
            continue
        entry = tables.setdefault((c.source_id, name), {"rows": [], "titles": []})
        if c.kind == "table_row" and _start_seconds(c.fields):
            entry["rows"].append(c)
        elif c.kind != "table_row":
            entry["titles"].append(c)
    for part in sorted(parts, key=lambda p: p.id):
        if part.kind != SCHEDULE_KIND or (part.id, "times") in have or (part.id, "values") in have:
            continue
        own = {name_key(t) for t in part.tags}
        cited = {i for t in part.trace
                 for i in _IDENTIFIER.findall(getattr(by_place.get((t.source_id, t.locator)),
                                                      "text", t.quote))
                 if name_key(i) not in own}
        found = []
        for (sid, name), entry in sorted(tables.items()):
            if not entry["rows"]:
                continue
            named = {i for c in entry["titles"] for i in _IDENTIFIER.findall(c.text)}
            if cited & named:
                found.append((sid, name, entry))
        if len(found) != 1:
            if found:
                out.questions.append(Question(
                    id=make_id("q", f"q schedule table {part.id}"), affects=[part.id],
                    options=[f"{name} ({source_map[sid]})" for sid, name, _ in found],
                    text=f"Several tables are named by the evidence of {part.id}; which one is "
                         "its schedule?"))
            else:
                out.missing.append(f"{part.id}: no table of start times is named by its evidence "
                                   f"(identifiers cited: {', '.join(sorted(cited)) or 'none'})")
            continue
        sid, name, entry = found[0]
        rows = sorted(entry["rows"], key=lambda c: _start_seconds(c.fields)[1])
        column = _value_column([c.fields for c in rows])
        if column is None:
            out.missing.append(f"{part.id}: table {name} has no single value column")
            continue
        written_unit = _HEADER_UNIT.search(column)
        values = [float(c.fields[column]) for c in rows]
        unit, assumption_ids = "1", []
        if written_unit:
            try:
                values, unit = to_si(values, written_unit.group(1).strip())
            except UnknownUnit:
                out.missing.append(f"{part.id}: column {column!r} has an unknown unit")
                continue
        else:
            aid = make_id("as", f"as unitless {part.id} values")
            assumption_ids = [aid]
            out.assumptions.append(Assumption(
                id=aid, basis="inferred", affects=[f"{part.id}_values"], confidence=0.8,
                text=f"Column {column!r} of {name} states no unit; its values are taken as plain "
                     "numbers (counts or a dimensionless signal).",
                trace=[]))
        ir_source = source_map[sid]
        title = [TraceLink(source_id=ir_source, locator=c.locator, quote=c.text[:300])
                 for c in entry["titles"] if set(_IDENTIFIER.findall(c.text)) & cited]
        link = [t for t in part.trace if t.source_id == ir_source] + title
        row_trace = [TraceLink(source_id=ir_source, locator=c.locator, quote=c.text[:300])
                     for c in rows]
        starts = [_start_seconds(c.fields) for c in rows]
        out.parameters += [
            Parameter(id=f"{part.id}_times", owner=part.id, name="times",
                      value=[t for _, t in starts], unit="s",
                      original=OriginalValue(value=", ".join(w for w, _ in starts),
                                             unit="hh:mm" if _CLOCK.match(starts[0][0]) else "s"),
                      status="effective", authority=ir_source, trace=row_trace + link),
            Parameter(id=f"{part.id}_values", owner=part.id, name="values", value=values,
                      unit=unit, original=OriginalValue(
                          value=", ".join(c.fields[column].strip() for c in rows),
                          unit=written_unit.group(1).strip() if written_unit else ""),
                      status="effective", authority=ir_source, trace=row_trace + link,
                      assumption_ids=assumption_ids)]
        for a in out.assumptions:
            if a.id in assumption_ids:
                a.trace = row_trace[:1] + link
    return out
