# Purpose: a test procedure lists operator commands one row per press ("20 / START"), and a
# requirement may restate them ("START at 20 s"); the LLM reads rows one at a time and never
# assembles a button's press_times. This module does it without the LLM: it matches each button's
# aliases in verification and requirement chunks, collects the times per source, and gives each
# button one verification_only press_times traced to every verbatim match. Disagreeing sources
# become a Question with no value; nothing is guessed.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from specalive.core.ids import make_id
from specalive.core.ir import OriginalValue, Parameter, Part, Question, TraceLink
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
    have = {p.owner for p in parameters if p.name == PARAMETER}
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
