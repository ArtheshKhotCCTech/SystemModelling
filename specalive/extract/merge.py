# Purpose: entity resolution. The same component appears under several names (formal tag, short
# name, legacy name) across sources; a union-find over name keys joins the names the evidence
# equates (same tag, names given together, alias tables), then joins same-kind names that only look
# alike (letter + number signature) with a declared Assumption and lower confidence. Each resolved
# part gets a deterministic id, catalogue ports, every alias and the union of traces; connections
# are resolved through the aliases, and a controller's ports are made from its connections.
# Phase 9: an instrument's unconnected measured input is wired to the one part the evidence names
# as what it measures (catalogue `measures`), traced to that evidence; never guessed.
# An input wired from several ports keeps the best-evidenced driver, naming the others in a
# Conflict; a tie is a Question.
# Phase 10: a part named only by the system's own identifier, whose kind another part has, is
# dropped (the system named itself, not a component).
from __future__ import annotations

import re
from dataclasses import dataclass, field

from specalive.core.catalogue import Catalogue, PortSpec
from specalive.core.ids import IdCollision, IdRegistry, make_id
from specalive.core.ir import (
    Assumption,
    Candidate,
    Conflict,
    ConflictSubject,
    Connection,
    Part,
    Port,
    Question,
    Source,
    TraceLink,
)
from specalive.extract.fragments import (
    AliasFragment,
    ConnectionFragment,
    Found,
    PartFragment,
    name_key,
)
from specalive.extract.precedence import LOWEST_RANK, rank_of
from specalive.ingest.evidence import EvidenceBundle

__all__ = ["name_key", "ir_sources", "resolve_parts", "resolve_connections", "PartSet",
           "ConnectionSet", "SIMILAR_CONFIDENCE", "measurement_links", "MeasurementLinks"]

SIMILAR_CONFIDENCE = 0.7
UNKNOWN = "unknown"
# A formal tag: upper-case letters and digits in dash-separated groups (AB-12, PB-GO, AB-12-C).
_FORMAL = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
# Name keys that are letters then a number, reduced to first letter + number: "valve1" and "v1".
_SIGNATURE = re.compile(r"^([a-z])[a-z]*(\d+)$")
# A controller's ports come from its connections and carry signals, never fluid.
_SIGNAL_DOMAINS = frozenset({"signal_real", "signal_bool", "event"})


def ir_sources(bundle: EvidenceBundle) -> tuple[list[Source], dict[str, str]]:
    """IR sources for the bundle's files and the evidence id -> IR id map. A source whose header
    states a document number is named by it; otherwise it keeps its evidence id."""
    registry = IdRegistry()
    mapping: dict[str, str] = {}
    out: list[Source] = []
    for s in bundle.sources:
        sid = None
        if s.document:
            try:
                sid = registry.make("src", s.document)
            except (IdCollision, ValueError):
                sid = None
        if sid is None:
            sid = registry.make("src", s.id)
        mapping[s.id] = sid
        out.append(Source(id=sid, title=s.title or s.path, path=s.path, role=s.role,
                          revision=s.revision, date=s.date, reliability=s.reliability,
                          tags=[s.document] if s.document else []))
    return out, mapping


def _formal_keys(names: list[str]) -> set[str]:
    return {name_key(n) for n in names if _FORMAL.match(n.strip())}


def _linked_names(names: list[str]) -> list[str]:
    """The names one fragment may join: all of them, unless they carry several formal tags — a
    component has one, so the other tags are other components (siblings listed together)."""
    if len(_formal_keys(names)) <= 1:
        return names
    head = names[0]
    return [head, *[n for n in names[1:] if not _FORMAL.match(n.strip())]]


class _UnionFind:
    """Name keys joined into components; two components with different formal tags never join."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.formal: dict[str, str] = {}

    def find(self, key: str) -> str:
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def mark_formal(self, key: str) -> None:
        self.formal.setdefault(self.find(key), key)

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        fa, fb = self.formal.get(ra), self.formal.get(rb)
        if fa and fb and fa != fb:
            return False
        keep, gone = min(ra, rb), max(ra, rb)
        self.parent[gone] = keep
        if fa or fb:
            self.formal[keep] = fa or fb
        return True


def _dedupe_traces(traces: list[TraceLink]) -> list[TraceLink]:
    seen = {(t.source_id, t.locator, t.quote): t for t in traces}
    return [seen[k] for k in sorted(seen)]


@dataclass
class _Component:
    parts: list[Found[PartFragment]] = field(default_factory=list)
    aliases: list[Found[AliasFragment]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)  # spellings in first-seen order
    kind: str = UNKNOWN
    similar_to: list[tuple[str, str, list[TraceLink]]] = field(default_factory=list)

    def add_name(self, name: str) -> None:
        if name_key(name) and name.strip() not in self.names:
            self.names.append(name.strip())


@dataclass
class PartSet:
    parts: list[Part] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)  # name key -> part id

    def lookup(self, name: str | None) -> str | None:
        return self.names.get(name_key(name)) if name else None

    def part(self, pid: str) -> Part:
        return next(p for p in self.parts if p.id == pid)


def _names(f: Found[PartFragment]) -> list[str]:
    return _linked_names([f.fragment.tag, *f.fragment.aliases])


def _components(parts: list[Found[PartFragment]], aliases: list[Found[AliasFragment]],
                uf: _UnionFind) -> dict[str, _Component]:
    for f in parts:
        for n in _names(f):
            if name_key(n) and _FORMAL.match(n.strip()):
                uf.mark_formal(name_key(n))
    for f in parts:
        keys = [k for k in map(name_key, _names(f)) if k]
        for k in keys[1:]:
            uf.union(keys[0], k)
        if keys:
            uf.find(keys[0])
    for a in aliases:
        if len(_formal_keys(a.fragment.names)) > 1:
            continue
        keys = [k for k in map(name_key, a.fragment.names) if k]
        for k in keys[1:]:
            uf.union(keys[0], k)
    comps: dict[str, _Component] = {}
    for f in parts:
        keys = [k for k in map(name_key, _names(f)) if k]
        if not keys:
            continue
        comp = comps.setdefault(uf.find(keys[0]), _Component())
        comp.parts.append(f)
        for n in _names(f):
            comp.add_name(n)
    for a in aliases:
        keys = [k for k in map(name_key, a.fragment.names) if k]
        if len(_formal_keys(a.fragment.names)) > 1:
            continue
        if keys and uf.find(keys[0]) in comps:
            comp = comps[uf.find(keys[0])]
            comp.aliases.append(a)
            for n in a.fragment.names:
                comp.add_name(n)
    return comps


def _choose_kind(comp: _Component, catalogue: Catalogue) -> tuple[str, list[str]]:
    """The kind of the most authoritative fragments, and the kinds tied with it if they differ."""
    ranked: dict[str, int] = {}
    for f in comp.parts:
        kind = f.fragment.kind
        if kind != UNKNOWN and kind in catalogue:
            ranked[kind] = min(ranked.get(kind, 99), rank_of(f.role))
    if not ranked:
        return UNKNOWN, []
    best = min(ranked.values())
    tied = sorted(k for k, r in ranked.items() if r == best)
    if len(tied) == 1:
        return tied[0], []
    counts = {k: sum(f.fragment.kind == k for f in comp.parts) for k in tied}
    return max(tied, key=lambda k: (counts[k], -tied.index(k))), tied


def _merge_similar(comps: dict[str, _Component], uf: _UnionFind) -> dict[str, _Component]:
    """Join two same-kind components when a name of each has the same letter + number signature
    and no third component of that kind shares it."""
    by_sig: dict[tuple[str, str], dict[str, str]] = {}
    for root, comp in comps.items():
        if comp.kind == UNKNOWN:
            continue
        for n in comp.names:
            m = _SIGNATURE.match(name_key(n))
            if m:
                by_sig.setdefault((comp.kind, m[1] + m[2]), {}).setdefault(root, n)
    for sig in sorted(by_sig):
        holders = by_sig[sig]
        if len(holders) != 2:
            continue
        (ra, na), (rb, nb) = sorted(holders.items())
        ra, rb = uf.find(ra), uf.find(rb)
        if ra == rb or ra not in comps or rb not in comps or not uf.union(ra, rb):
            continue
        keep, gone = (ra, rb) if ra < rb else (rb, ra)
        a, b = comps[keep], comps.pop(gone)
        a.parts.extend(b.parts)
        a.aliases.extend(b.aliases)
        for n in b.names:
            a.add_name(n)
        a.similar_to.extend(b.similar_to)
        traces = [f.trace for f in a.parts if na in _names(f) or nb in _names(f)][:2]
        a.similar_to.append((na, nb, traces))
    return comps


def _canonical(comp: _Component) -> str:
    ordered = sorted(comp.parts, key=lambda f: rank_of(f.role))
    tags = [f.fragment.tag.strip() for f in ordered if name_key(f.fragment.tag)]
    formal = [t for t in tags if _FORMAL.match(t)] or [n for n in comp.names if _FORMAL.match(n)]
    return formal[0] if formal else (tags or comp.names)[0]


def _static_ports(pid: str, kind: str, catalogue: Catalogue) -> list[Port]:
    entry = catalogue.entry(kind)
    if entry.dynamic_ports:
        return []
    return [Port(id=f"{pid}_{role}", role=role, direction=spec.direction, domain=spec.domain,
                 unit=spec.unit) for role, spec in sorted(entry.ports.items())]


def resolve_parts(parts: list[Found[PartFragment]], aliases: list[Found[AliasFragment]],
                  catalogue: Catalogue) -> PartSet:
    uf = _UnionFind()
    comps = _components(parts, aliases, uf)
    out = PartSet()
    ties: dict[str, list[str]] = {}
    for root, comp in comps.items():
        comp.kind, ties[root] = _choose_kind(comp, catalogue)
    for root, comp in sorted(comps.items()):
        if comp.kind == UNKNOWN:
            tag = _canonical(comp)
            what = next((f.fragment.description or f.fragment.name for f in comp.parts
                         if f.fragment.description or f.fragment.name), "a component")
            out.questions.append(Question(
                id=make_id("q", f"q unknown {tag}"),
                text=f"The input describes {tag} ({what}); no catalogue component matches it. "
                     "Which catalogue kind should model it, or should it be left out?"))
    comps = _merge_similar(comps, uf)
    registry = IdRegistry()
    for root, comp in sorted(comps.items(), key=lambda kv: _canonical(kv[1])):
        if comp.kind == UNKNOWN:
            continue
        tag = _canonical(comp)
        try:
            pid = registry.make(comp.kind, tag)
        except IdCollision:
            pid = registry.make(comp.kind, f"{tag} {comp.kind}")
        ordered = sorted(comp.parts, key=lambda f: (rank_of(f.role), f.source_id, f.chunk_id))
        name = next((f.fragment.name for f in ordered if f.fragment.name), tag)
        attributes: dict[str, str | bool] = {}
        for f in ordered:
            for attr in f.fragment.attributes:
                key = re.sub(r"\W+", "_", attr.key.strip().lower()).strip("_")
                if key:
                    attributes.setdefault(key, attr.value)
        part = Part(id=pid, kind=comp.kind, name=name,
                    tags=[tag, *[n for n in comp.names if n != tag]], attributes=attributes,
                    ports=_static_ports(pid, comp.kind, catalogue),
                    trace=_dedupe_traces([f.trace for f in comp.parts]
                                         + [a.trace for a in comp.aliases]))
        if ties.get(root):
            out.questions.append(Question(
                id=make_id("q", f"q kind {pid}"),
                text=f"Sources of equal authority describe {tag} as different kinds "
                     f"({', '.join(ties[root])}); {comp.kind} is used until this is answered.",
                options=ties[root], default_if_unanswered=comp.kind, affects=[pid]))
        for na, nb, traces in comp.similar_to:
            aid = make_id("as", f"as similar {pid} {name_key(nb)}")
            out.assumptions.append(Assumption(
                id=aid, basis="inferred", affects=[pid], confidence=SIMILAR_CONFIDENCE,
                text=f"'{na}' and '{nb}' are taken to be the same {comp.kind} ({pid}): the names "
                     "look alike, but no source equates them.", trace=traces))
            part.assumption_ids.append(aid)
            part.confidence = SIMILAR_CONFIDENCE
        out.parts.append(part)
        for n in comp.names:
            out.names[name_key(n)] = pid
    out.parts.sort(key=lambda p: p.id)
    return out


def drop_system_names(parts: PartSet, system_name: str | None) -> list[str]:
    """A part named only by the system's own identifier ("System: RM-9 room ventilation") names
    the system, not a component, when another part has its kind; it is dropped, and fragments
    naming it are then reported as naming no known part. Returns the reasons."""
    if not system_name:
        return []
    reasons = []
    for part in sorted(parts.parts, key=lambda p: p.id):
        same_kind = [q for q in parts.parts if q.kind == part.kind and q.id != part.id]
        if not part.tags or not same_kind or not all(_names_any(system_name, [t]) for t in part.tags):
            continue
        parts.parts.remove(part)
        parts.names = {k: v for k, v in parts.names.items() if v != part.id}
        parts.questions = [q for q in parts.questions if part.id not in q.affects]
        parts.assumptions = [a for a in parts.assumptions if part.id not in a.affects]
        reasons.append(f"{part.id} ({', '.join(part.tags)}): its only name is the system's own "
                       f"({system_name!r}) and {same_kind[0].id} is the {part.kind}; not a part")
    return reasons


# --- connections ---------------------------------------------------------------------------

@dataclass
class ConnectionSet:
    connections: list[Connection] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _end_specs(part: Part, catalogue: Catalogue, sending: bool,
               role: str | None) -> dict[str, PortSpec] | None:
    """Candidate catalogue ports for one end, narrowed to the stated role when it exists; None
    for a part whose ports come from its connections."""
    entry = catalogue.entry(part.kind)
    if entry.dynamic_ports:
        return None
    allowed = ("out", "inout") if sending else ("in", "inout")
    specs = {r: s for r, s in entry.ports.items() if s.direction in allowed}
    return {role: specs[role]} if role in specs else specs


def _dynamic_port(part: Part, role_hint: str, sending: bool, spec: PortSpec,
                  trace: TraceLink) -> Port | str:
    role = make_id("port", role_hint)
    pid = f"{part.id}_{role}"
    direction = "out" if sending else "in"
    for port in part.ports:
        if port.id == pid:
            if (port.direction, port.domain) != (direction, spec.domain):
                return f"port {pid} is already {port.direction} {port.domain}"
            if trace not in port.trace:
                port.trace.append(trace)
            return port
    port = Port(id=pid, role=role, direction=direction, domain=spec.domain, unit=spec.unit,
                trace=[trace])
    part.ports.append(port)
    part.ports.sort(key=lambda p: p.id)
    return port


def _signal_name(static: Part, role: str, frag: ConnectionFragment, catalogue: Catalogue) -> str:
    """A controller port is named after the part it connects to — its first short (non-formal)
    alias, with the port role when several of its signal ports face the same way — so the name
    does not depend on which source mentioned the signal first. Fallback: the signal name, then
    the id."""
    alias = next((t for t in static.tags[1:] if not _FORMAL.match(t) and name_key(t)), None)
    if alias is None:
        return frag.signal_name if frag.signal_name and name_key(frag.signal_name) else static.id
    ports = catalogue.entry(static.kind).ports
    facing = [r for r, s in ports.items() if s.domain in _SIGNAL_DOMAINS
              and s.direction in ("inout", ports[role].direction)]
    return alias if len(facing) <= 1 else f"{alias} {role}"


def _ends(src: Part, dst: Part, frag: ConnectionFragment, catalogue: Catalogue,
          trace: TraceLink, wired: dict[tuple[str, str], Port]) -> tuple[Port, Port] | str:
    """The two ports a connection joins. `wired` maps (static port, controller) to the controller
    port already joined to it: sources name one I/O signal differently (short name, channel
    number), so a static port reaches a given controller through one port only."""
    a = _end_specs(src, catalogue, True, frag.from_role)
    b = _end_specs(dst, catalogue, False, frag.to_role)
    if a is None and b is None:
        return "both ends are controllers with connection-defined ports"
    if a is not None and b is not None:
        pairs = [(ra, rb) for ra, sa in a.items() for rb, sb in b.items() if sa.domain == sb.domain]
        if len(pairs) != 1:
            return ("no port pair with matching domains" if not pairs
                    else f"ambiguous ports {sorted(pairs)}")
        ra, rb = pairs[0]
        return (next(p for p in src.ports if p.role == ra),
                next(p for p in dst.ports if p.role == rb))
    static, dynamic, sending_static = (src, dst, True) if a is not None else (dst, src, False)
    specs = {r: s for r, s in (a if a is not None else b).items() if s.domain in _SIGNAL_DOMAINS}
    if len(specs) != 1:
        return (f"no signal port on {static.id}" if not specs
                else f"ambiguous ports on {static.id}: {sorted(specs)}")
    role, spec = next(iter(specs.items()))
    static_port = next(p for p in static.ports if p.role == role)
    port = wired.get((static_port.id, dynamic.id))
    if port is None:
        port = _dynamic_port(dynamic, _signal_name(static, role, frag, catalogue),
                             not sending_static, spec, trace)
        if isinstance(port, str):
            return port
        wired[(static_port.id, dynamic.id)] = port
    return (static_port, port) if sending_static else (port, static_port)


def resolve_connections(found: list[Found[ConnectionFragment]], parts: PartSet,
                        catalogue: Catalogue) -> ConnectionSet:
    out = ConnectionSet()
    by_ends: dict[tuple[str, str], Connection] = {}
    registry = IdRegistry()
    wired: dict[tuple[str, str], Port] = {}
    for f in found:
        frag = f.fragment
        where = f"connection {frag.from_tag} -> {frag.to_tag} ({f.chunk_id})"
        a, b = parts.lookup(frag.from_tag), parts.lookup(frag.to_tag)
        if a is None or b is None:
            missing = frag.from_tag if a is None else frag.to_tag
            out.problems.append(f"{where}: '{missing}' is not a known part")
            continue
        if a == b:
            out.problems.append(f"{where}: both ends are the same part")
            continue
        ends = _ends(parts.part(a), parts.part(b), frag, catalogue, f.trace, wired)
        if isinstance(ends, str):
            out.problems.append(f"{where}: {ends}")
            continue
        key = (ends[0].id, ends[1].id)
        if key in by_ends:
            if f.trace not in by_ends[key].trace:
                by_ends[key].trace.append(f.trace)
            continue
        cid = None
        if frag.tag:
            try:
                cid = registry.make("conn", frag.tag)
            except (IdCollision, ValueError):
                cid = None
        if cid is None:
            cid = registry.make("conn", f"{key[0]} to {key[1]}")
        by_ends[key] = Connection(id=cid, from_port=key[0], to_port=key[1],
                                  medium_or_signal=frag.medium_or_signal, trace=[f.trace])
    out.connections = sorted(by_ends.values(), key=lambda c: c.id)
    return out


# --- measurement links -----------------------------------------------------------------------

@dataclass
class MeasurementLinks:
    connections: list[Connection] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _names_any(text: str, names: list[str]) -> bool:
    """Whether `text` mentions one of `names` as a whole token (AB-1 is not in AB-12)."""
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", text, re.IGNORECASE)
               for n in names if n.strip())


def measurement_links(parts: PartSet, connections: list[Connection],
                      catalogue: Catalogue) -> MeasurementLinks:
    """Wire each unconnected measured input (catalogue `measures`) to the one part that offers
    the measured output and that the evidence names: the instrument's own quotes naming the part,
    or the part's quotes naming the instrument. The link is traced to those quotes. Several named
    parts are a Question; none is reported as missing information. Nothing is guessed."""
    out = MeasurementLinks()
    connected = {c.to_port for c in connections}
    taken = {c.id for c in connections}
    for sensor in sorted(parts.parts, key=lambda p: p.id):
        if sensor.kind not in catalogue:
            continue
        for role, measured in sorted(catalogue.entry(sensor.kind).measures.items()):
            port = next((q for q in sensor.ports if q.role == role), None)
            if port is None or port.id in connected:
                continue
            named: dict[str, tuple[Port, list[TraceLink]]] = {}
            for other in sorted(parts.parts, key=lambda p: p.id):
                source = next((q for q in other.ports if q.role == measured
                               and q.direction == "out" and q.domain == port.domain), None)
                # an instrument does not measure another instrument of its own kind
                if other.id == sensor.id or other.kind == sensor.kind or source is None:
                    continue
                links = ([t for t in sensor.trace if _names_any(t.quote, other.tags)]
                         + [t for t in other.trace if _names_any(t.quote, sensor.tags)])
                if links:
                    named[other.id] = (source, _dedupe_traces(links))
            if len(named) == 1:
                source, trace = next(iter(named.values()))
                cid = make_id("conn", f"{source.id} to {port.id}")
                if cid in taken:
                    cid = make_id("conn", f"conn measured {source.id} to {port.id}")
                taken.add(cid)
                out.connections.append(Connection(
                    id=cid, from_port=source.id, to_port=port.id,
                    medium_or_signal=measured.removesuffix("_out"), trace=trace))
            elif named:
                out.questions.append(Question(
                    id=make_id("q", f"q measures {port.id}"),
                    text=f"{sensor.tags[0] if sensor.tags else sensor.id} ({sensor.id}) has an "
                         f"unconnected {role}; the sources name several parts it could measure "
                         f"({', '.join(sorted(named))}). Which one does it measure?",
                    options=sorted(named), affects=[sensor.id]))
            else:
                out.missing.append(f"{sensor.id}: input {role} is not connected and no source "
                                   f"names the part whose {measured} it measures")
    return out


# --- one driver per input ----------------------------------------------------------------------

@dataclass
class Drivers:
    connections: list[Connection] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)


def single_drivers(connections: list[Connection], sources: list[Source]) -> Drivers:
    """An input takes its value from one port. When the evidence wires an input from several,
    the connection traced to the most authoritative source (then to the most sources) is kept
    and the others are named in a Conflict; a tie is a Question and keeps none, never a guess."""
    roles = {s.id: s.role for s in sources}

    def evidence(c: Connection) -> tuple[int, int]:
        ranks = [rank_of(roles.get(t.source_id, "other")) for t in c.trace]
        return (min(ranks, default=LOWEST_RANK), -len({t.source_id for t in c.trace}))

    out = Drivers()
    by_input: dict[str, list[Connection]] = {}
    for c in connections:
        by_input.setdefault(c.to_port, []).append(c)
    for port, group in sorted(by_input.items()):
        if len(group) == 1:
            out.connections.append(group[0])
            continue
        ranked = sorted(group, key=lambda c: (evidence(c), c.id))
        drivers = sorted({c.from_port for c in group})
        if evidence(ranked[0]) == evidence(ranked[1]):
            out.questions.append(Question(
                id=make_id("q", f"q driver {port}"), options=drivers, affects=[port],
                text=f"Input {port} is wired from {', '.join(drivers)} by equally authoritative "
                     "evidence, and an input takes one value. Which one drives it?"))
            continue
        win = ranked[0]
        out.connections.append(win)
        out.conflicts.append(Conflict(
            id=make_id("cf", f"cf driver {port}"),
            subject=ConflictSubject(element_id=win.id, field="from_port"),
            candidates=[Candidate(value=c.from_port, element_id=c.id,
                                  source_id=c.trace[0].source_id if c.trace else "unknown",
                                  authority_rank=evidence(c)[0]) for c in ranked],
            resolution=win.from_port,
            rationale=f"{port} can take one driver; {win.from_port} is traced to the most "
                      "authoritative evidence"))
    out.connections.sort(key=lambda c: c.id)
    return out
