# Purpose: entity resolution. The same component appears under several names (formal tag, short
# name, legacy name) across sources; a union-find over name keys joins the names the evidence
# equates (same tag, names given together, alias tables), then joins same-kind names that only look
# alike (letter + number signature) with a declared Assumption and lower confidence. Each resolved
# part gets a deterministic id, catalogue ports, every alias and the union of traces; connections
# are resolved through the aliases, and a controller's ports are made from its connections.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from specalive.core.catalogue import Catalogue, PortSpec
from specalive.core.ids import IdCollision, IdRegistry, make_id
from specalive.core.ir import Assumption, Connection, Part, Port, Question, Source, TraceLink
from specalive.extract.fragments import (
    AliasFragment,
    ConnectionFragment,
    Found,
    PartFragment,
    name_key,
)
from specalive.extract.precedence import rank_of
from specalive.ingest.evidence import EvidenceBundle

__all__ = ["name_key", "ir_sources", "resolve_parts", "resolve_connections", "PartSet",
           "ConnectionSet", "SIMILAR_CONFIDENCE"]

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
