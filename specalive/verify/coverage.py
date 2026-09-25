# Purpose: how much of a reference IR a produced IR covers, and whether two runs agree. Coverage
# matches parts by id, then by any shared tag alias; ports within matched parts by id, then role;
# connections by their mapped endpoints; parameters by id or (owner, name), counted only when the
# effective values agree within tolerance; states and transitions within matched machines. Each
# category reports matched, missing, extra and a percentage. Repeatability compares topology only
# (parts by kind, connections by endpoint kinds), so a renamed element alone is not a failure.
from __future__ import annotations

import re
from collections import Counter

from specalive.core.ir import HISTORY, SYSTEM_OWNER, Parameter, Part, StateMachine, SystemModel

CATEGORIES = ("parts", "ports", "connections", "parameters", "states", "transitions")
VALUE_REL_TOL = 1e-6
_VALUE_ABS_TOL = 1e-12


def alias_key(text: str) -> str:
    """A name or tag reduced to lower-case letters and digits, so P-12 meets p_12."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _part_keys(part: Part) -> set[str]:
    return {k for k in (alias_key(t) for t in (part.id, *part.tags)) if k}


class _Category:
    def __init__(self, reference_ids: list[str], produced_ids: list[str]) -> None:
        self.reference = sorted(reference_ids)
        self.produced = sorted(produced_ids)
        self.matched: dict[str, tuple[str, str]] = {}  # reference id -> (produced id, by)
        self.mismatched: list[dict] = []

    def match(self, ref_id: str, prod_id: str, by: str) -> None:
        self.matched[ref_id] = (prod_id, by)

    def taken(self) -> set[str]:
        return {prod for prod, _ in self.matched.values()}

    def report(self) -> dict:
        mismatched = {m["reference"] for m in self.mismatched}
        taken = self.taken() | {m["produced"] for m in self.mismatched}
        n = len(self.reference)
        out = {
            "reference": n,
            "matched": [{"reference": r, "produced": p, "by": by}
                        for r, (p, by) in sorted(self.matched.items())],
            "missing": [r for r in self.reference if r not in self.matched and r not in mismatched],
            "extra": [p for p in self.produced if p not in taken],
            "percent": round(100.0 * len(self.matched) / n, 2) if n else 100.0,
        }
        if self.mismatched:
            out["mismatched"] = sorted(self.mismatched, key=lambda m: m["reference"])
        return out


def _pair(cat: _Category, ref_items: dict, prod_items: dict, keys) -> None:
    """Match by id first, then by any shared key; each produced item is used once."""
    for rid in cat.reference:
        if rid in prod_items and rid not in cat.taken():
            cat.match(rid, rid, "id")
    for rid in cat.reference:
        if rid in cat.matched:
            continue
        want = keys(ref_items[rid])
        for pid in cat.produced:
            if pid not in cat.taken() and want & keys(prod_items[pid]):
                cat.match(rid, pid, "alias")
                break


def _values_agree(a: float | list[float], b: float | list[float]) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return (isinstance(a, list) and isinstance(b, list) and len(a) == len(b)
                and all(_values_agree(x, y) for x, y in zip(a, b)))
    return abs(a - b) <= max(VALUE_REL_TOL * max(abs(a), abs(b)), _VALUE_ABS_TOL)


def coverage(produced: SystemModel, reference: SystemModel) -> dict:
    """Per category: matched, missing, extra and the share of the reference that was matched."""
    ref_parts = {p.id: p for p in reference.parts}
    prod_parts = {p.id: p for p in produced.parts}
    parts = _Category(list(ref_parts), list(prod_parts))
    _pair(parts, ref_parts, prod_parts, _part_keys)
    part_map = {r: p for r, (p, _) in parts.matched.items()}

    ref_ports = {q.id: (p.id, q) for p in reference.parts for q in p.ports}
    prod_ports = {q.id: (p.id, q) for p in produced.parts for q in p.ports}
    ports = _Category(list(ref_ports), list(prod_ports))
    for rid in ports.reference:
        owner, rport = ref_ports[rid]
        if owner not in part_map:
            continue
        candidates = [pid for pid in ports.produced
                      if prod_ports[pid][0] == part_map[owner] and pid not in ports.taken()]
        by_id = [pid for pid in candidates if pid == rid]
        by_role = [pid for pid in candidates if prod_ports[pid][1].role == rport.role]
        if by_id:
            ports.match(rid, by_id[0], "id")
        elif by_role:
            ports.match(rid, by_role[0], "alias")
    port_map = {r: p for r, (p, _) in ports.matched.items()}

    ref_conns = {c.id: c for c in reference.connections}
    prod_conns = {c.id: c for c in produced.connections}
    conns = _Category(list(ref_conns), list(prod_conns))
    prod_ends = {(c.from_port, c.to_port): c.id for c in produced.connections}
    for rid in conns.reference:
        c = ref_conns[rid]
        if rid in prod_conns:
            conns.match(rid, rid, "id")
            continue
        ends = (port_map.get(c.from_port), port_map.get(c.to_port))
        pid = prod_ends.get(ends)
        if pid is not None and pid not in conns.taken():
            conns.match(rid, pid, "alias")

    params = _parameters(produced, reference, part_map)
    states, transitions = _behaviour(produced, reference, part_map)
    return {"parts": parts.report(), "ports": ports.report(), "connections": conns.report(),
            "parameters": params.report(), "states": states.report(),
            "transitions": transitions.report()}


def _parameters(produced: SystemModel, reference: SystemModel,
                part_map: dict[str, str]) -> _Category:
    def effective(m: SystemModel) -> dict[str, Parameter]:
        return {p.id: p for p in m.parameters if p.status == "effective"}

    ref, prod = effective(reference), effective(produced)
    cat = _Category(list(ref), list(prod))
    by_owner_name = {(p.owner, p.name): p.id for p in prod.values()}
    for rid in cat.reference:
        r = ref[rid]
        owner = SYSTEM_OWNER if r.owner == SYSTEM_OWNER else part_map.get(r.owner)
        pid = rid if rid in prod else by_owner_name.get((owner, r.name))
        if pid is None:
            continue
        if _values_agree(r.value, prod[pid].value):
            cat.match(rid, pid, "id" if pid == rid else "alias")
        else:
            cat.mismatched.append({"reference": rid, "produced": pid,
                                   "reference_value": r.value, "produced_value": prod[pid].value})
    return cat


def _behaviour(produced: SystemModel, reference: SystemModel,
               part_map: dict[str, str]) -> tuple[_Category, _Category]:
    def qualified(m: SystemModel):
        states = {f"{sm.id}/{s.id}": (sm, s) for sm in m.state_machines for s in sm.states}
        trans = {f"{sm.id}/{t.id}": (sm, t) for sm in m.state_machines for t in sm.transitions}
        return states, trans

    ref_states, ref_trans = qualified(reference)
    prod_states, prod_trans = qualified(produced)
    machine_map = _machines(produced.state_machines, reference.state_machines, part_map)

    states = _Category(list(ref_states), list(prod_states))
    for rid in states.reference:
        rsm, rs = ref_states[rid]
        psm_id = machine_map.get(rsm.id)
        if psm_id is None:
            continue
        want = {alias_key(x) for x in (rs.id, rs.name, *rs.tags)}
        for pid in states.produced:
            psm, ps = prod_states[pid]
            if psm.id != psm_id or pid in states.taken():
                continue
            if ps.id == rs.id:
                states.match(rid, pid, "id")
                break
        else:
            for pid in states.produced:
                psm, ps = prod_states[pid]
                if (psm.id == psm_id and pid not in states.taken()
                        and want & {alias_key(x) for x in (ps.id, ps.name, *ps.tags)}):
                    states.match(rid, pid, "alias")
                    break
    state_map = {rid.split("/", 1)[1]: pid.split("/", 1)[1]
                 for rid, (pid, _) in states.matched.items()}

    transitions = _Category(list(ref_trans), list(prod_trans))
    for rid in transitions.reference:
        rsm, rt = ref_trans[rid]
        psm_id = machine_map.get(rsm.id)
        if psm_id is None:
            continue
        ends = (state_map.get(rt.from_), HISTORY if rt.to == HISTORY else state_map.get(rt.to))
        same_id = f"{psm_id}/{rt.id}"
        if same_id in prod_trans and same_id not in transitions.taken():
            transitions.match(rid, same_id, "id")
            continue
        for pid in transitions.produced:
            psm, pt = prod_trans[pid]
            if psm.id == psm_id and pid not in transitions.taken() and (pt.from_, pt.to) == ends:
                transitions.match(rid, pid, "alias")
                break
    return states, transitions


def _machines(produced: list[StateMachine], reference: list[StateMachine],
              part_map: dict[str, str]) -> dict[str, str]:
    """Reference machine id -> produced machine id: same id, else same (mapped) owner."""
    prod_ids = {sm.id for sm in produced}
    by_owner = {sm.owner: sm.id for sm in produced}
    out = {}
    for sm in reference:
        if sm.id in prod_ids:
            out[sm.id] = sm.id
        elif part_map.get(sm.owner) in by_owner:
            out[sm.id] = by_owner[part_map[sm.owner]]
    return out


# --- repeatability (FR-07 requirement 10) --------------------------------------------------

def topology(model: SystemModel) -> dict[str, dict[str, int]]:
    """Parts counted by kind and connections by the kinds of their two ends; no names."""
    kind_of_port = {q.id: p.kind for p in model.parts for q in p.ports}
    connections = Counter(
        f"{kind_of_port.get(c.from_port, '?')} -> {kind_of_port.get(c.to_port, '?')}"
        for c in model.connections)
    return {"parts_by_kind": dict(sorted(Counter(p.kind for p in model.parts).items())),
            "connections_by_kinds": dict(sorted(connections.items()))}


def repeatability(first: SystemModel, second: SystemModel) -> dict:
    """Identical when both topologies agree; differing part ids are listed but are not a failure."""
    a, b = topology(first), topology(second)
    differences = []
    for group in ("parts_by_kind", "connections_by_kinds"):
        for key in sorted(set(a[group]) | set(b[group])):
            x, y = a[group].get(key, 0), b[group].get(key, 0)
            if x != y:
                differences.append(f"{group} {key}: {x} vs {y}")
    ids_a, ids_b = {p.id for p in first.parts}, {p.id for p in second.parts}
    naming = [f"only in first: {i}" for i in sorted(ids_a - ids_b)]
    naming += [f"only in second: {i}" for i in sorted(ids_b - ids_a)]
    return {"identical": not differences, "differences": differences,
            "naming_differences": naming, "first": a, "second": b}
