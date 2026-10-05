# Purpose: pins the diagram the Modelica generator draws (OMEdit and other tools show nothing
# without placements): a deterministic layered layout of the IR parts, sources left of what they
# feed, no two parts on one spot, feedback loops routed without collisions; every instance has a
# Placement and every connect a Line; SpecAlive components and connectors carry icons whose
# ports follow the one left/right rule the lines are drawn to; and, with omc, the flattened
# models are byte-identical to before the diagrams, so the graphics changed no equation.
import json
import re
from pathlib import Path

import pytest

from _modelica_support import golden_model, requires_omc
from specalive.config import load_settings
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel
from specalive.generate import layout, modelica
from specalive.toolchain.process import run_tool

ROOT = Path(__file__).resolve().parent
COMPONENTS = ROOT.parent / "specalive" / "generate" / "templates" / "modelica" / "components"
SNAPSHOTS = ROOT / "fixtures" / "snapshots"
L2_GOLDEN = ROOT / "goldens" / "L2_co2.ir.json"


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


@pytest.fixture(scope="module")
def l2():
    return SystemModel.model_validate_json(L2_GOLDEN.read_text(encoding="utf-8"))


# --- the layout ------------------------------------------------------------------------------

def test_layout_is_deterministic_and_places_every_part_once(catalogue, l2):
    for model in (golden_model(), l2):
        first, second = layout.layout(model, catalogue), layout.layout(model, catalogue)
        assert first == second
        assert set(first.origins) == {p.id for p in model.parts}
        assert len(set(first.origins.values())) == len(first.origins)  # no two on one spot


def test_sources_sit_left_of_what_they_feed(catalogue):
    x = {pid: o[0] for pid, o in layout.layout(golden_model(), catalogue).origins.items()}
    assert x["src_101"] < x["xv_101"] < x["tk_101"] < x["xv_102"] < x["tk_102"] < x["xv_103"]
    assert x["xv_103"] < x["drn_101"]
    assert x["pb_start"] < x["plc_101"]


def test_the_l2_control_loop_reads_left_to_right(catalogue, l2):
    x = {pid: o[0] for pid, o in layout.layout(l2, catalogue).origins.items()}
    assert x["zon_201"] < x["sen_co2_201"] < x["gain_norm_201"] < x["ctl_co2_201"]
    assert x["ctl_co2_201"] < x["gain_air_201"]
    assert x["sch_occ_201"] < x["gain_peo_201"]


def test_every_connection_has_a_line_from_port_to_port(catalogue, l2):
    for model in (golden_model(), l2):
        lay = layout.layout(model, catalogue)
        assert set(lay.lines) == {c.id for c in model.connections}
        for c in model.connections:
            points = lay.lines[c.id]
            assert points[0] == lay.port_points[c.from_port]
            assert points[-1] == lay.port_points[c.to_port]
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                assert x1 == x2 or y1 == y2  # right-angle segments only


def test_ports_follow_one_rule_inputs_left_outputs_right():
    got = layout.icon_positions([("a", "in"), ("b", "out"), ("c", "in"), ("d", "out"),
                                 ("e", "out")])
    assert got["a"] == (-100, 50) and got["c"] == (-100, -50)
    assert got["b"][0] == got["d"][0] == got["e"][0] == 100
    assert [got[k][1] for k in "bde"] == sorted([got[k][1] for k in "bde"], reverse=True)
    assert layout.icon_positions([("only", "out")]) == {"only": (100, 0)}


def test_the_diagram_extent_holds_every_part_and_line(catalogue, l2):
    for model in (golden_model(), l2):
        lay = layout.layout(model, catalogue)
        (x1, y1), (x2, y2) = lay.extent
        points = [p for line in lay.lines.values() for p in line]
        points += [(x + dx, y + dy) for x, y in lay.origins.values()
                   for dx in (-10, 10) for dy in (-10, 10)]
        assert all(x1 <= x <= x2 and y1 <= y <= y2 for x, y in points)


# --- the generated text ----------------------------------------------------------------------

@pytest.mark.parametrize("which", ["l1", "l2"])
def test_every_instance_is_placed_and_every_connect_drawn(catalogue, l2, which):
    model = golden_model() if which == "l1" else l2
    text = modelica.render_modelica(model, catalogue).text
    system = text[text.index("  model System"):]
    instances = [ln for ln in system.splitlines() if "[IR " in ln and "parameter" not in ln
                 and "connect(" not in ln]
    connects = [ln for ln in system.splitlines() if ln.strip().startswith("connect(")]
    assert len(instances) == len(model.parts) and len(connects) == len(model.connections)
    assert all("annotation(Placement(transformation(origin = {" in ln for ln in instances)
    assert all("annotation(Line(points = {{" in ln for ln in connects)
    assert re.search(r"annotation\(Diagram\(coordinateSystem\(extent = \{\{-?\d+, -?\d+\}, "
                     r"\{-?\d+, -?\d+\}\}\)\), experiment\(", system)


def test_the_controller_has_an_icon_and_placed_ports(catalogue):
    text = modelica.render_modelica(golden_model(), catalogue).text
    ctl = text[text.index("  model Controller_"):text.index("  model System")]
    assert "annotation(Icon(" in ctl
    ports = [ln for ln in ctl.splitlines() if re.match(r"\s+SpecAlive\.Interfaces\.\w+ \w+", ln)]
    assert ports and all("iconTransformation(extent = " in ln for ln in ports)


# --- the component package -------------------------------------------------------------------

_PLACED = re.compile(r"SpecAlive\.Interfaces\.\w+ (\w+)\b.*iconTransformation\(extent = "
                     r"\{\{(-?\d+), (-?\d+)\}, \{(-?\d+), (-?\d+)\}\}\)")


def test_specalive_components_have_icons_and_ports_where_the_lines_end(catalogue):
    for kind in catalogue.kinds:
        entry = catalogue.entry(kind)
        if entry.modelica.source != "specalive":
            continue
        name = entry.modelica.class_.rsplit(".", 1)[1]
        text = (COMPONENTS / f"{name}.mo").read_text(encoding="utf-8")
        assert "annotation(Icon(" in text, name
        want = layout.icon_positions([(entry.modelica.connectors[role], spec.direction)
                                      for role, spec in entry.ports.items()])
        got = {m.group(1): ((int(m.group(2)) + int(m.group(4))) // 2,
                            (int(m.group(3)) + int(m.group(5))) // 2)
               for m in _PLACED.finditer(text)}
        assert got == {k: (round(x), round(y)) for k, (x, y) in want.items()}, name


def test_custom_connectors_have_icons():
    text = (COMPONENTS / "Interfaces.mo").read_text(encoding="utf-8")
    for connector in ("VolumeFlowInput", "VolumeFlowOutput", "AirFlowInput", "AirFlowOutput"):
        start = text.index(f"connector {connector}")
        following = text.find("\nconnector ", start + 1)
        own = text[start:following if following != -1 else len(text)]
        assert "annotation(Icon(" in own, connector


# --- the graphics change no equation (omc) -------------------------------------------------------

def _flatten(text: str, model_name: str, tmp_path: Path) -> str:
    settings = load_settings()
    (tmp_path / "model.mo").write_text(text, encoding="utf-8", newline="\n")
    (tmp_path / "flat.mos").write_text(
        f'loadModel(Modelica, {{"{settings.msl_version}"}});\nloadFile("model.mo");\n'
        f'writeFile("flat.mo", instantiateModel({model_name}));\ngetErrorString();\n',
        encoding="utf-8")
    run_tool([settings.omc_path, "flat.mos"], timeout=settings.omc_timeout_s, cwd=tmp_path)
    return (tmp_path / "flat.mo").read_text(encoding="utf-8")


@requires_omc
@pytest.mark.slow
@pytest.mark.parametrize("which, snapshot", [("l1", "L1_tank.flat.mo"), ("l2", "L2_co2.flat.mo")])
def test_the_flattened_model_is_unchanged_by_the_diagram(catalogue, l2, which, snapshot,
                                                         tmp_path):
    generated = modelica.render_modelica(golden_model() if which == "l1" else l2, catalogue)
    flat = _flatten(generated.text, generated.model_name, tmp_path)
    assert flat == (SNAPSHOTS / snapshot).read_text(encoding="utf-8")
