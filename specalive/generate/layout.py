# Purpose: the diagram a Modelica tool draws for the generated System (OMEdit shows nothing
# without placements). A deterministic layered layout of the IR's parts: a depth-first walk from
# the parts nothing feeds breaks each feedback loop at the edge that closes it, the longest path
# then gives each part its column, and within a column parts follow the rows of what feeds them.
# Ports follow one rule, inputs on the left edge and outputs on the right, spread evenly; lines
# run in right-angle segments, a loop's closing line below the parts. Pure: no LLM, no tool.
from __future__ import annotations

import math
from dataclasses import dataclass

from specalive.core.catalogue import Catalogue
from specalive.core.ir import Part, SystemModel

COLUMN = 50       # diagram units between columns
ROW = 40          # between rows
HALF = 10         # a component's half width in the diagram
ICON = 100        # half width of a component's own icon coordinate system
MARGIN = 20
LOOP_GAP = 6      # vertical spacing of the lines that close loops below the parts
# Modelica's customary colours per domain (MSL connectors use the same).
COLOURS: dict[str, tuple[int, int, int]] = {
    "fluid": (0, 127, 255), "signal_real": (0, 0, 127), "signal_bool": (255, 0, 255),
    "event": (255, 0, 255), "thermal": (191, 0, 0), "electric": (0, 0, 255),
    "magnetic": (255, 127, 0),
}

Point = tuple[float, float]


@dataclass(frozen=True)
class Layout:
    origins: dict[str, tuple[int, int]]   # part id -> centre of its box in the diagram
    port_points: dict[str, Point]         # port id -> where its connector sits in the diagram
    lines: dict[str, list[Point]]         # connection id -> line points, from port to port
    colours: dict[str, tuple[int, int, int]]  # connection id -> line colour
    extent: tuple[tuple[int, int], tuple[int, int]]


def icon_positions(ports: list[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """Centre of each port in its component's icon coordinates: inputs (and in/out ports) on the
    left edge, outputs on the right, each side spread evenly top to bottom in the given order."""
    out: dict[str, tuple[int, int]] = {}
    for x, keys in ((-ICON, [k for k, d in ports if d != "out"]),
                    (ICON, [k for k, d in ports if d == "out"])):
        for i, key in enumerate(keys):
            out[key] = (x, round(ICON - 2 * ICON * (i + 0.5) / len(keys)))
    return out


def drawing_order(part: Part, catalogue: Catalogue) -> list[tuple[str, str]]:
    """(port id, direction) in the order the part's icon places them: the catalogue's port order
    for a kind with fixed ports, the IR's for one whose ports come from the model."""
    entry = catalogue.entry(part.kind)
    by_role = {p.role: p for p in part.ports}
    if entry.dynamic_ports:
        return [(p.id, p.direction) for p in part.ports]
    return [(by_role[r].id, by_role[r].direction) for r in entry.ports if r in by_role]


def _columns(ids: list[str],
             succ: dict[str, set[str]]) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Column per part and the loop-free edges the columns were drawn from."""
    feeds = {n for targets in succ.values() for n in targets}
    roots = [n for n in ids if n not in feeds] + [n for n in ids if n in feeds]
    state: dict[str, int] = {}
    dag: dict[str, set[str]] = {n: set() for n in ids}
    order: list[str] = []

    def visit(n: str) -> None:
        state[n] = 1
        for m in sorted(succ[n]):
            if state.get(m) == 1:  # closes a loop: drawn back, not a column step
                continue
            dag[n].add(m)
            if m not in state:
                visit(m)
        state[n] = 2
        order.append(n)

    for n in roots:
        if n not in state:
            visit(n)
    column = {n: 0 for n in ids}
    for n in reversed(order):  # reverse post-order is a topological order of the dag
        for m in dag[n]:
            column[m] = max(column[m], column[n] + 1)
    return column, dag


def layout(model: SystemModel, catalogue: Catalogue) -> Layout:
    ids = sorted(p.id for p in model.parts)
    owner = {q.id: p.id for p in model.parts for q in p.ports}
    succ: dict[str, set[str]] = {n: set() for n in ids}
    for c in model.connections:
        a, b = owner[c.from_port], owner[c.to_port]
        if a != b:
            succ[a].add(b)
    column, dag = _columns(ids, succ)
    preds: dict[str, list[str]] = {n: [] for n in ids}
    for a, targets in dag.items():
        for b in targets:
            preds[b].append(a)
    row: dict[str, float] = {}
    origins: dict[str, tuple[int, int]] = {}
    for col in range(max(column.values(), default=0) + 1):
        members = [n for n in ids if column[n] == col]
        members.sort(key=lambda n: (sum(row[p] for p in preds[n]) / len(preds[n])
                                    if preds[n] else math.inf, n))
        for r, n in enumerate(members):
            row[n] = r
            origins[n] = (col * COLUMN, round(((len(members) - 1) / 2 - r) * ROW))

    scale = HALF / ICON
    parts = {p.id: p for p in model.parts}
    port_points: dict[str, Point] = {}
    for pid, (x, y) in origins.items():
        for port_id, (px, py) in icon_positions(drawing_order(parts[pid], catalogue)).items():
            port_points[port_id] = (x + px * scale, y + py * scale)

    bottom = min((y for _, y in origins.values()), default=0) - HALF - MARGIN // 2
    domain = {q.id: q.domain for p in model.parts for q in p.ports}
    lines: dict[str, list[Point]] = {}
    loops = 0
    for c in sorted(model.connections, key=lambda c: c.id):
        (sx, sy), (dx, dy) = port_points[c.from_port], port_points[c.to_port]
        if dx > sx:
            mid = (sx + dx) / 2
            points = [(sx, sy), (dx, dy)] if sy == dy else [(sx, sy), (mid, sy), (mid, dy),
                                                            (dx, dy)]
        else:  # a loop's closing line, or two ports one above the other: route below
            low = bottom - LOOP_GAP * loops
            loops += 1
            points = [(sx, sy), (sx + 4, sy), (sx + 4, low), (dx - 4, low), (dx - 4, dy),
                      (dx, dy)]
        lines[c.id] = points
    colours = {c.id: COLOURS.get(domain[c.from_port], (0, 0, 0)) for c in model.connections}

    xs = [x for pts in lines.values() for x, _ in pts] + [x + s * HALF for x, _ in origins.values()
                                                         for s in (-1, 1)]
    ys = [y for pts in lines.values() for _, y in pts] + [y + s * HALF for _, y in origins.values()
                                                         for s in (-1, 1)]
    xs, ys = xs or [0.0], ys or [0.0]

    def down(v: float) -> int:
        return int(math.floor((v - MARGIN) / 10) * 10)

    def up(v: float) -> int:
        return int(math.ceil((v + MARGIN) / 10) * 10)

    extent = ((down(min(xs)), down(min(ys))), (up(max(xs)), up(max(ys))))
    return Layout(origins, port_points, lines, colours, extent)
