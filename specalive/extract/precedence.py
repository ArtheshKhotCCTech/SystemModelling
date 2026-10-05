# Purpose: engineering packets state one parameter several times across revisions. This module
# ranks every candidate value by the authority of its source role (approved change > review
# decision > released spec / design note > datasheet > legacy > informal; ADR ladder, R-EXT-5) —
# a register row takes the rank of the record it cites — after first honouring status columns the
# evidence itself carries (requirement 12). The winner becomes effective, each losing value is kept
# as superseded and named in a Conflict; configuration variants are kept without conflict; ties
# and provisional winners become Questions. A system-level value named like one part's value is
# ranked with it (fresh-run finding: one register's rows came back under two owners).
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from specalive.core.ids import make_id
from specalive.core.ir import (
    SYSTEM_OWNER,
    Candidate,
    Conflict,
    ConflictSubject,
    OriginalValue,
    Parameter,
    Question,
    Requirement,
    Source,
    TraceLink,
)
from specalive.core.units import UnknownUnit, to_si
from specalive.extract.fragments import (
    DocumentFragment,
    Found,
    ParameterFragment,
    RequirementFragment,
    name_key,
)

# Lower is more authoritative. Registers compile other documents and rank like a released
# specification unless a row cites its record. Verification documents are evidence of intent,
# not design authority: their values become verification_only and never win (ADR).
RANK: dict[str, int] = {
    "change_record": 1,
    "review_decision": 2,
    "requirement_spec": 3, "design_note": 3, "register": 3,
    "datasheet": 4,
    "legacy_model": 5, "legacy_architecture": 5,
    "correspondence": 6, "informal_note": 6, "other": 6,
    "verification_procedure": 6, "reference_data": 6,
}
LOWEST_RANK = 6
VERIFICATION_ROLES = frozenset({"verification_procedure", "reference_data"})

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REVISION_SUFFIX = re.compile(r"(?i)\s*\b(?:rev(?:ision)?\.?)\s*\S+\s*$")
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBER_LIST = re.compile(rf"^\s*{_NUMBER}(?:\s*[,;]?\s+{_NUMBER}|\s*[,;]\s*{_NUMBER})*\s*$")


def rank_of(role: str, approved: bool = True) -> int:
    """An unapproved change record is a proposal, so it ranks with informal notes."""
    if role == "change_record" and not approved:
        return LOWEST_RANK
    return RANK.get(role, LOWEST_RANK)


def iso_or_none(text: str | None) -> str | None:
    return text if text and _ISO_DATE.match(text) else None


# --- documents -----------------------------------------------------------------------------

@dataclass(frozen=True)
class DocInfo:
    source_id: str
    role: str
    date: str | None
    approved: bool


class DocRegistry:
    """Documents by identifier, whatever the spelling ("CR 9", "cr-9", "CR-9 Rev 1")."""

    def __init__(self) -> None:
        self._docs: dict[str, DocInfo] = {}

    def add(self, tag: str, info: DocInfo) -> None:
        key = name_key(tag)
        if key:
            self._docs.setdefault(key, info)

    def get(self, tag: str | None) -> DocInfo | None:
        if not tag:
            return None
        return self._docs.get(name_key(tag)) or self._docs.get(
            name_key(_REVISION_SUFFIX.sub("", tag)))


def _bundle_match(frag: DocumentFragment, sources: list[Source]) -> Source | None:
    """The one bundle source the fragment points at, if exactly one: by its file name, then by a
    bundle file name written in its verbatim quote, then by its identifier in a title or path."""
    files = [s for s in sources if s.path is not None]

    def basename(path: str) -> str:
        return path.replace("\\", "/").rsplit("/", 1)[-1]

    if frag.file_name and name_key(frag.file_name):
        want = name_key(basename(frag.file_name))
        hits = [s for s in files if want == name_key(basename(s.path))]
        if len(hits) == 1:
            return hits[0]
    hits = [s for s in files if basename(s.path) in frag.quote]
    if len(hits) == 1:
        return hits[0]
    key = name_key(frag.tag)
    hits = [s for s in files if key in name_key(s.title) or key in name_key(s.path)]
    return hits[0] if len(hits) == 1 else None


def build_registry(sources: list[Source], documents: list[Found[DocumentFragment]]
                   ) -> tuple[DocRegistry, list[Source]]:
    """Register the bundle's sources by their document numbers, then every document the evidence
    cites. A cited document found in the bundle by its identifier is the same source; one the
    bundle lacks becomes a cited-record Source with no path."""
    docs = DocRegistry()
    ids = {s.id for s in sources}
    for s in sources:
        for tag in [*s.tags, s.id]:
            docs.add(tag, DocInfo(s.id, s.role, s.date, approved=True))
    cited: list[Source] = []
    for f in documents:
        frag = f.fragment
        if not name_key(frag.tag) or docs.get(frag.tag) is not None:
            continue
        date = iso_or_none(frag.date)
        match = _bundle_match(frag, sources)
        if match is not None:
            docs.add(frag.tag, DocInfo(match.id, match.role, match.date or date, frag.approved))
            continue
        sid = make_id("src", frag.tag)
        if sid in ids:
            sid = make_id("src", f"cited {frag.tag}")
        ids.add(sid)
        cited.append(Source(id=sid, title=frag.title or frag.tag, path=None, role=frag.role,
                            revision=frag.revision, date=date, tags=[frag.tag]))
        docs.add(frag.tag, DocInfo(sid, frag.role, date, frag.approved))
    return docs, cited


# --- parameters ----------------------------------------------------------------------------

def parse_value(text: str) -> float | list[float] | None:
    """A number or a list of numbers as written; a tolerance "±2" or "+/-2" reads as 2."""
    cleaned = text.replace("±", "").replace("+/-", "").replace("−", "-")
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", cleaned)
    if not _NUMBER_LIST.match(cleaned):
        return None
    numbers = [float(n) for n in re.findall(_NUMBER, cleaned)]
    return numbers[0] if len(numbers) == 1 else numbers


def _same(a: float | list[float], b: float | list[float]) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return (isinstance(a, list) and isinstance(b, list) and len(a) == len(b)
                and all(_same(x, y) for x, y in zip(a, b)))
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


@dataclass
class _Cand:
    owner: str
    name: str
    found: Found[ParameterFragment]
    value: float | list[float]
    unit: str
    rank: int
    role: str
    authority: str
    date: str | None
    provisional: bool

    @property
    def written(self) -> str:
        return f"{self.found.fragment.value} {self.found.fragment.unit}"

    @property
    def stated(self) -> str | None:
        return self.found.fragment.stated_status

    def order(self) -> tuple:
        return (self.rank, self.authority, self.found.chunk_id)


@dataclass
class _Value:
    """One distinct value of a parameter and every candidate that states it."""

    cands: list[_Cand]

    @property
    def best(self) -> _Cand:
        return min(self.cands, key=_Cand.order)

    @property
    def rank(self) -> int:
        return self.best.rank


@dataclass
class ParameterSet:
    parameters: list[Parameter] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    unresolved_citations: set[str] = field(default_factory=set)


def _traces(cands: list[_Cand]) -> list[TraceLink]:
    seen: dict[tuple[str, str, str], TraceLink] = {}
    for c in sorted(cands, key=_Cand.order):
        t = c.found.trace
        seen.setdefault((t.source_id, t.locator, t.quote), t)
    return list(seen.values())


def _parameter(pid: str, value: _Value, status: str) -> Parameter:
    best = value.best
    return Parameter(id=pid, owner=best.owner, name=best.name, value=best.value, unit=best.unit,
                     original=OriginalValue(value=best.found.fragment.value,
                                            unit=best.found.fragment.unit),
                     status=status, authority=best.authority, trace=_traces(value.cands))


def _group(values: list[_Value], cand: _Cand) -> None:
    for v in values:
        if _same(v.cands[0].value, cand.value):
            v.cands.append(cand)
            return
    values.append(_Value([cand]))


class _Resolver:
    def __init__(self, docs: DocRegistry) -> None:
        self.docs = docs
        self.out = ParameterSet()
        self.used: set[str] = set()

    def unique(self, pid: str) -> str:
        base, n = pid, 1
        while pid in self.used:
            n += 1
            pid = f"{base}_{n}"
        self.used.add(pid)
        return pid

    def question(self, q: Question) -> None:
        if all(q.id != existing.id for existing in self.out.questions):
            self.out.questions.append(q)

    def candidate(self, owner: str, f: Found[ParameterFragment]) -> _Cand | None:
        frag = f.fragment
        if not name_key(frag.name):
            self.out.problems.append(f"{owner} ({f.chunk_id}): parameter name {frag.name!r} "
                                     "has no letters or digits")
            return None
        name = make_id("param", frag.name)
        where = f"{owner}.{name} ({f.chunk_id})"
        value = parse_value(frag.value)
        if value is None:
            self.out.problems.append(f"{where}: value {frag.value!r} is not a number or list")
            return None
        try:
            si, unit = to_si(value, frag.unit)
        except UnknownUnit:
            self.out.problems.append(f"{where}: unit {frag.unit!r} is not in the unit table")
            self.question(Question(
                id=make_id("q", f"q unit {owner} {name}"),
                text=f"The unit {frag.unit!r} given for {owner}.{name} ({frag.value} {frag.unit}) "
                     "is not in the unit table; what is the value in SI units?",
                affects=[] if owner == SYSTEM_OWNER else [owner]))
            return None
        cited = self.docs.get(frag.cited_document)
        if frag.cited_document and cited is None:
            self.out.unresolved_citations.add(frag.cited_document)
        if cited is not None:
            role, date, approved, authority = cited.role, cited.date, cited.approved, \
                cited.source_id
        else:
            role, date, approved, authority = f.role, f.date, True, f.source_id
        provisional = frag.provisional or (role == "change_record" and not approved)
        return _Cand(owner, name, f, si, unit, rank_of(role, approved), role, authority,
                     iso_or_none(date), provisional)

    def resolve(self, cands: list[tuple[str, Found[ParameterFragment]]]) -> ParameterSet:
        nominal: dict[tuple[str, str], list[_Value]] = {}
        variants: dict[tuple[str, str, str], list[_Value]] = {}
        for owner, f in cands:
            c = self.candidate(owner, f)
            if c is None:
                continue
            config = f.fragment.configuration
            if config in ("as_built", "prototype"):
                _group(variants.setdefault((c.owner, c.name, "as_built_only"), []), c)
            elif config == "verification" or c.role in VERIFICATION_ROLES:
                _group(variants.setdefault((c.owner, c.name, "verification_only"), []), c)
            else:
                _group(nominal.setdefault((c.owner, c.name), []), c)
        for key in sorted(nominal):
            self.nominal(*key, nominal[key])
        for key in sorted(variants):
            self.variant(*key, variants[key])
        return self.out

    def nominal(self, owner: str, name: str, values: list[_Value]) -> None:
        pid = self.unique(f"{owner}_{name}")
        values.sort(key=lambda v: v.best.order())
        winner, reason, tie = self.choose(values)
        eff = _parameter(pid, winner, "effective")
        self.out.parameters.append(eff)
        holder = {id(winner): pid}
        for v in values:
            if v is not winner:
                lid = self.unique(f"{pid}_{v.best.authority}")
                holder[id(v)] = lid
                self.out.parameters.append(_parameter(lid, v, "superseded"))
        options = [v.best.written for v in values]
        best = winner.best
        if tie:
            self.question(Question(
                id=make_id("q", f"q value {pid}"),
                text=f"Sources of equal authority disagree on {owner}.{name}: "
                     f"{', '.join(options)}. Which value applies?",
                options=options, default_if_unanswered=best.written, affects=[pid]))
        if any(c.provisional for c in winner.cands if c.rank == winner.rank):
            self.question(Question(
                id=make_id("q", f"q provisional {pid}"),
                text=f"{owner}.{name} = {best.written} comes from {best.authority}, which marks "
                     "it provisional (subject to change or confirmation); confirm the value.",
                options=options, default_if_unanswered=best.written, affects=[pid]))
        if len(values) == 1:
            return
        per_source: dict[tuple[str, str], Candidate] = {}
        for v in values:
            for c in sorted(v.cands, key=_Cand.order):
                per_source.setdefault((c.authority, c.written), Candidate(
                    value=c.written, source_id=c.authority, authority_rank=c.rank,
                    element_id=holder[id(v)]))
        candidates = sorted(per_source.values(), key=lambda c: (c.authority_rank, c.source_id))
        self.out.conflicts.append(Conflict(
            id=make_id("cf", f"cf {pid}"), subject=ConflictSubject(element_id=pid, field="value"),
            candidates=candidates, resolution="unresolved" if tie else best.written,
            rationale=self.rationale(reason, winner, values)))

    def choose(self, values: list[_Value]) -> tuple[_Value, str, bool]:
        """The winning value, the rule that picked it, and whether it was a tie."""
        if len(values) == 1:
            return values[0], "single", False
        marked = [v for v in values if any(c.stated == "effective" for c in v.cands)]
        if len(marked) == 1:
            return marked[0], "status", False
        if not marked:
            live = [v for v in values if not all(c.stated == "superseded" for c in v.cands)]
            if len(live) == 1:
                return live[0], "status", False
        top_rank = min(v.rank for v in values)
        top = [v for v in values if v.rank == top_rank]
        if len(top) == 1:
            return top[0], "ladder", False
        dates = [max((c.date for c in v.cands if c.rank == top_rank and c.date), default=None)
                 for v in top]
        if all(dates) and dates.count(max(dates)) == 1:
            return top[dates.index(max(dates))], "later", False
        return top[0], "tie", True

    @staticmethod
    def rationale(reason: str, winner: _Value, values: list[_Value]) -> str:
        best = winner.best
        losers = [v.best for v in values if v is not winner]
        if reason == "status":
            return (f"The evidence itself marks {best.written} ({best.authority}) as the effective "
                    "value and the others as superseded, so the ladder was not needed.")
        if reason == "ladder":
            beaten = ", ".join(f"{c.role} rank {c.rank}" for c in losers)
            return (f"{best.authority} is a {best.role} (rank {best.rank} on the precedence "
                    f"ladder), which outranks {beaten}; lower-ranked values are kept as "
                    "superseded.")
        if reason == "later":
            return (f"The leading sources share rank {best.rank} ({best.role}); the later dated "
                    f"one, {best.authority} of {best.date}, wins.")
        return (f"Sources of equal rank {best.rank} disagree and none is later; {best.written} from "
                f"{best.authority} is used until the open question is answered.")

    def variant(self, owner: str, name: str, status: str, values: list[_Value]) -> None:
        short = "as_built" if status == "as_built_only" else "verification"
        for v in sorted(values, key=lambda v: v.best.order()):
            base = f"{owner}_{name}"
            pid = base if base not in self.used else f"{base}_{short}"
            if pid in self.used:
                pid = f"{pid}_{v.best.authority}"
            self.out.parameters.append(_parameter(self.unique(pid), v, status))


def adopt_system_values(cands: list[tuple[str, Found[ParameterFragment]]]
                        ) -> list[tuple[str, Found[ParameterFragment]]]:
    """A system-level value named like a value of exactly one part is that part's value, so the
    two are ranked against each other; with several such parts it stays system-level."""
    owners: dict[str, set[str]] = {}
    for owner, f in cands:
        if owner != SYSTEM_OWNER:
            owners.setdefault(f.fragment.name, set()).add(owner)
    out = []
    for owner, f in cands:
        named = owners.get(f.fragment.name, set())
        out.append((next(iter(named)) if owner == SYSTEM_OWNER and len(named) == 1 else owner, f))
    return out


def resolve_parameters(cands: list[tuple[str, Found[ParameterFragment]]],
                       docs: DocRegistry) -> ParameterSet:
    """Parameters, conflicts and questions from (owner id, fragment) candidates."""
    return _Resolver(docs).resolve(cands)


# --- requirements --------------------------------------------------------------------------

def usable_tag(tag: str | None) -> str | None:
    """An identifier the LLM gave, or None when it has no letters or digits, such as "-"."""
    return tag.strip() if tag and name_key(tag) else None


def _requirement_id(f: Found[RequirementFragment]) -> str:
    tag = usable_tag(f.fragment.tag)
    return make_id("req", tag) if tag else make_id("req", f"req {f.source_id} {f.locator}")


def resolve_requirements(found: list[Found[RequirementFragment]]) -> list[Requirement]:
    """One requirement per identifier; text and category from the most authoritative statement,
    superseded when any statement says so, superseded_by kept only when it names a requirement."""
    groups: dict[str, list[Found[RequirementFragment]]] = {}
    for f in found:
        groups.setdefault(_requirement_id(f), []).append(f)
    out: list[Requirement] = []
    for rid in sorted(groups):
        items = sorted(groups[rid], key=lambda f: (rank_of(f.role), f.source_id, f.chunk_id))
        best = items[0].fragment
        superseded = any(f.fragment.status == "superseded" for f in items)
        by = next((usable_tag(f.fragment.superseded_by) for f in items
                   if usable_tag(f.fragment.superseded_by)), None)
        by_id = make_id("req", by) if by else None
        trace: dict[tuple[str, str, str], TraceLink] = {}
        for f in items:
            t = f.trace
            trace.setdefault((t.source_id, t.locator, t.quote), t)
        out.append(Requirement(
            id=rid, tags=[usable_tag(best.tag)] if usable_tag(best.tag) else [], text=best.text, category=best.category,
            status="superseded" if superseded else "active",
            superseded_by=by_id if superseded and by_id in groups and by_id != rid else None,
            trace=list(trace.values())))
    return out
