# Purpose: FR-06 acceptance and rules for the Modelica generator. The golden L1 IR is rendered and
# checked for one instance per part of the class the catalogue names, one connect() per
# connection, IR ids on both, parameters bound from effective and verification-only values,
# ASSUMPTION comments, the experiment annotation and a byte-exact snapshot; small IRs cover
# defaults, escaping, reserved names and error paths. omc runs are skipped when omc is absent.
import copy
import re
from collections import Counter
from pathlib import Path

import pytest

from specalive.config import load_settings
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel
from specalive.generate import modelica
from specalive.toolchain import omc
from tests._modelica_support import golden_model, plant_ir, plant_model, requires_omc

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "fixtures" / "snapshots" / "L1_tank.mo"
PKG = ROOT.parent / "specalive"
IR_TAG = re.compile(r'\[IR (\w+)\]";')


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


@pytest.fixture(scope="module")
def golden():
    return golden_model()


@pytest.fixture(scope="module")
def generated(golden, catalogue):
    return modelica.render_modelica(golden, catalogue)


@pytest.fixture(scope="module")
def text(generated):
    return generated.text


def system_section(text: str) -> str:
    start = text.index(f"  model {modelica.SYSTEM_CLASS} ")
    return text[start:text.index(f"  end {modelica.SYSTEM_CLASS};", start)]


def declaration(text: str, ir_id: str) -> str:
    lines = [line for line in system_section(text).splitlines()
             if line.rstrip().endswith(f'[IR {ir_id}]";') and "connect(" not in line
             and not line.lstrip().startswith("parameter ")]
    assert len(lines) == 1, (ir_id, lines)
    return lines[0].strip()


# --- acceptance on the golden IR ------------------------------------------------------------

def test_one_package_with_the_system_model(generated, golden):
    # Requirement 2: one package, compiled from one file with only MSL loaded.
    assert generated.package == golden.name
    assert generated.model_name == f"{golden.name}.{modelica.SYSTEM_CLASS}"
    assert generated.text.startswith("// ")
    assert f"\npackage {golden.name} " in generated.text
    assert generated.text.rstrip().endswith(f"end {golden.name};")
    assert "  package SpecAlive " in generated.text


def test_every_part_and_connection_appears_exactly_once_by_ir_id(golden, text):
    # Acceptance 3 / requirement 5.
    counts = Counter(IR_TAG.findall(system_section(text)))
    expected = [p.id for p in golden.parts] + [c.id for c in golden.connections]
    assert {eid: counts[eid] for eid in expected} == {eid: 1 for eid in expected}


def test_instances_are_the_classes_the_catalogue_names(golden, catalogue, text):
    # Requirement 3 / R-MO-3.
    for part in golden.parts:
        entry = catalogue.entry(part.kind)
        cls = declaration(text, part.id).split()[0]
        if entry.modelica.source == "generated":
            assert cls == "Controller_plc_101_sequence"
        else:
            assert cls == entry.modelica.class_, part.id


def test_parameters_are_bound_from_the_ir(text):
    assert declaration(text, "tk_101").startswith(
        "SpecAlive.Components.Tank tk_101(A = tk_101_area, h_start = tk_101_initial_level)")
    assert declaration(text, "xv_102").startswith(
        "SpecAlive.Components.OnOffValve xv_102(q_nominal = xv_102_nominal_flow)")
    assert declaration(text, "pb_start").startswith(
        "SpecAlive.Components.CommandButton pb_start(pressTimes = pb_start_press_times)")
    assert declaration(text, "lt_101").startswith("Modelica.Blocks.Routing.RealPassThrough lt_101 ")


def test_top_level_parameters_carry_value_unit_and_ir_id(text):
    system = system_section(text)
    assert 'parameter Real tk_101_area(unit = "m2") = 1.2 "tk_101 area [IR tk_101_area]";' in system
    assert 'parameter Real tk_101_high_level(unit = "m") = 0.8 ' in system
    assert ('parameter Real xv_101_nominal_flow(unit = "m3/s") = 0.006 '
            '"xv_101 nominal_flow [IR xv_101_nominal_flow]";') in system


def test_only_effective_and_verification_values_are_used(text):
    # Superseded values never reach the model; verification-only values are the test scenario.
    assert "_urs_001" not in text
    assert "0.78" not in text
    system = system_section(text)
    assert ('parameter Real pb_start_press_times[2](each unit = "s") = {20.0, 280.0} '
            '"pb_start press_times, verification only [IR pb_start_press_times]";') in system
    assert 'parameter Real pb_shut_press_times[1](each unit = "s") = {700.0} ' in system


def test_connections_use_the_catalogue_connectors(text):
    system = system_section(text)
    assert 'connect(src_101.outlet, xv_101.inlet) "liquid [IR if_hyd_01]";' in system
    assert 'connect(tk_101.level, lt_101.u) "level [IR tk_101_lt_101]";' in system
    assert 'connect(lt_101.y, plc_101.level1) "level measurement [IR if_ctl_01]";' in system
    assert 'connect(plc_101.valve3, xv_103.open) "open command [IR if_ctl_08]";' in system


def test_controller_instance_binds_the_parameters_its_machine_reads(text):
    decl = declaration(text, "plc_101")
    assert decl.startswith("Controller_plc_101_sequence plc_101(")
    for pid in ("plc_101_wait_after_drain", "plc_101_wait_after_fill",
                "plc_101_wait_after_transfer", "tk_101_high_level", "tk_101_low_level",
                "tk_102_low_level"):
        assert f"{pid} = {pid}" in decl


def test_assumed_elements_carry_assumption_comments(text):
    # Requirement 7.
    lines = system_section(text).splitlines()

    def comments_before(ir_id):
        i = next(n for n, line in enumerate(lines) if line.rstrip().endswith(f'[IR {ir_id}]";'))
        above = []
        while lines[i - 1].strip().startswith("//"):
            i -= 1
            above.append(lines[i].strip())
        return above

    assert any(c.startswith("// ASSUMPTION as_constant_flow: Each valve passes")
               for c in comments_before("xv_101_nominal_flow"))
    assert any(c.startswith("// ASSUMPTION as_constant_flow:") for c in comments_before("xv_101"))
    assert any(c.startswith("// ASSUMPTION as_momentary_pulse:") for c in comments_before("pb_start"))
    assert comments_before("tk_101") == []


def test_experiment_comes_from_the_verification_stop_time(generated, text):
    # Requirement 6: StopTime from the IR; the interval has no IR value, so it is a declared
    # generator default, visible in the model and in the notes.
    assert "annotation(experiment(StopTime = 900.0, Interval = 1.8));" in text
    assert "// ASSUMPTION (generator default): no output interval in the IR" in text
    assert len(generated.notes) == 1 and "Interval" in generated.notes[0]


def test_only_used_component_classes_are_emitted(text):
    for cls in ("Tank", "OnOffValve", "CommandButton", "FluidSource", "FluidSink"):
        assert f"      model {cls}" in text
    assert "Controller_plc_101_sequence" in text


def test_generation_is_byte_identical_and_matches_the_snapshot(golden, catalogue, text):
    # Acceptance 4 / FR-11 item 16.
    assert modelica.render_modelica(golden, catalogue).text == text
    assert text == SNAPSHOT.read_text(encoding="utf-8")


def test_write_modelica_writes_model_mo(golden, catalogue, tmp_path, text):
    path, result = modelica.write_modelica(golden, catalogue, tmp_path)
    assert path == tmp_path / modelica.MODEL_FILE
    assert path.read_bytes() == text.encode("utf-8") and result.text == text


# --- small IRs --------------------------------------------------------------------------------

def test_small_plant_renders_with_escaped_strings(catalogue):
    out = modelica.render_modelica(plant_model(), catalogue).text
    assert 'SpecAlive.Components.Tank tank(A = tank_area, h_start = tank_initial_level) ' \
           '"Tank \\"A\\" [IR tank]";' in out
    assert "tank_high_old" not in out
    assert "model CommandButton" in out


def test_unused_component_classes_are_left_out(catalogue):
    ir = plant_ir()
    ir["parts"] = [p for p in ir["parts"] if p["kind"] != "fluid_sink"]
    ir["connections"] = [c for c in ir["connections"] if c["id"] != "c4"]
    out = modelica.render_modelica(plant_model(ir), catalogue).text
    assert "model FluidSink" not in out and "model FluidSource" in out


def test_catalogue_default_is_used_with_a_declared_assumption(catalogue):
    ir = plant_ir()
    ir["parameters"] = [p for p in ir["parameters"] if p["id"] != "tank_initial_level"]
    result = modelica.render_modelica(plant_model(ir), catalogue)
    decl = next(line for line in result.text.splitlines() if line.strip().startswith(
        "SpecAlive.Components.Tank tank("))
    assert "h_start = 0.0" in decl
    assert "// ASSUMPTION (catalogue default tank.initial_level): No initial level" in result.text
    assert any("tank.initial_level" in n for n in result.notes)


def test_missing_required_parameter_is_a_generation_error(catalogue):
    ir = plant_ir()
    ir["parameters"] = [p for p in ir["parameters"] if p["id"] != "tank_area"]
    with pytest.raises(modelica.ModelicaGenerationError, match=r"tank.*area"):
        modelica.render_modelica(plant_model(ir), catalogue)


def test_superseded_value_alone_does_not_satisfy_a_required_parameter(catalogue):
    ir = plant_ir()
    for p in ir["parameters"]:
        if p["id"] == "tank_area":
            p["status"] = "superseded"
    with pytest.raises(modelica.ModelicaGenerationError, match="area"):
        modelica.render_modelica(plant_model(ir), catalogue)


def test_unmapped_port_role_is_an_error_naming_part_and_role(catalogue):
    # Requirement 4: never a guess.
    ir = plant_ir()
    tank = next(p for p in ir["parts"] if p["id"] == "tank")
    tank["ports"].append({"id": "tank_overflow", "role": "overflow", "direction": "out",
                          "domain": "fluid", "unit": "m3/s"})
    ir["connections"].append({"id": "c_over", "from_port": "tank_overflow",
                              "to_port": "drain_inlet", "medium_or_signal": "water",
                              "trace": ir["connections"][0]["trace"]})
    with pytest.raises(modelica.ModelicaGenerationError, match=r"'tank'.*'overflow'"):
        modelica.render_modelica(plant_model(ir), catalogue)


def test_unknown_kind_is_a_generation_error(catalogue):
    ir = plant_ir()
    ir["parts"][0]["kind"] = "pump"
    with pytest.raises(modelica.ModelicaGenerationError, match="pump"):
        modelica.render_modelica(plant_model(ir), catalogue)


def test_reserved_word_ids_become_legal_modelica_names(catalogue):
    ir = copy.deepcopy(plant_ir())
    old, new = "drain", "end"
    for p in ir["parts"]:
        if p["id"] == old:
            p["id"] = new
            p["ports"][0]["id"] = "end_inlet"
    for c in ir["connections"]:
        if c["to_port"] == "drain_inlet":
            c["to_port"] = "end_inlet"
    out = modelica.render_modelica(SystemModel.model_validate(ir), catalogue).text
    assert 'SpecAlive.Components.FluidSink end_ "Drain [IR end]";' in out
    assert "connect(v_out.outlet, end_.inlet)" in out


def test_experiment_defaults_without_a_stop_time(catalogue):
    ir = plant_ir()
    ir["parameters"] = [p for p in ir["parameters"] if p["id"] != "system_stop_time"]
    result = modelica.render_modelica(plant_model(ir), catalogue)
    assert "annotation(experiment(StopTime = 1.0, Interval = 0.002));" in result.text
    assert len(result.notes) == 2


def test_output_interval_parameter_sets_the_interval(catalogue):
    ir = plant_ir()
    ir["parameters"].append({**ir["parameters"][-1], "id": "system_output_interval",
                             "name": "output_interval", "value": 0.5})
    result = modelica.render_modelica(plant_model(ir), catalogue)
    assert "annotation(experiment(StopTime = 200.0, Interval = 0.5));" in result.text
    assert result.notes == []


# --- rules ------------------------------------------------------------------------------------

CASE_VALUES = re.compile(r"TK-10|XV-10|RM-201|\bB[1-7]\b|0\.78|0\.80|_sysmlv2_|tk_10|xv_10|plc_101")


def test_no_case_specific_values_in_generate_or_repair():
    # Acceptance 6, including the templates, which test_rules.py does not read.
    files = [p for d in ("generate", "repair") for p in (PKG / d).rglob("*")
             if p.is_file() and p.suffix in (".py", ".j2", ".mo")]
    assert files
    hits = [f"{p.relative_to(PKG)}: {m.group(0)}" for p in files
            for m in CASE_VALUES.finditer(p.read_text(encoding="utf-8"))]
    assert hits == []


# --- real omc ---------------------------------------------------------------------------------

@requires_omc
@pytest.mark.slow
def test_golden_model_compiles_with_zero_errors(generated, tmp_path):
    # Acceptance 1 / R-MO-1: the hard gate.
    mo = tmp_path / modelica.MODEL_FILE
    mo.write_text(generated.text, encoding="utf-8", newline="\n")
    result = omc.compile_model(load_settings(), mo, generated.model_name, tmp_path / "build")
    assert result.ok, [m.text for m in result.messages]
    assert result.errors == []


@requires_omc
@pytest.mark.slow
def test_small_plant_compiles(catalogue, tmp_path):
    generated = modelica.render_modelica(plant_model(), catalogue)
    mo = tmp_path / modelica.MODEL_FILE
    mo.write_text(generated.text, encoding="utf-8", newline="\n")
    result = omc.compile_model(load_settings(), mo, generated.model_name, tmp_path / "build")
    assert result.ok, [m.text for m in result.messages]


@requires_omc
@pytest.mark.slow
def test_every_button_press_gives_one_pulse(generated):
    # Found in phase 7: a `time >= pressTimes[i]` test inside a for loop is not tracked as an
    # event for every index by omc 1.27.1, so presses between output points were lost. L1's
    # START at 20 s and 280 s and STOP at 220 s must each give one 1 s pulse.
    from tests._modelica_support import simulate_values

    probes = [("pb_start.y", 19.5), ("pb_start.y", 20.5), ("pb_start.y", 21.5),
              ("pb_start.y", 280.5), ("pb_start.y", 281.5), ("pb_stop.y", 220.5),
              ("pb_stop.y", 221.5), ("pb_stop.y", 650.5), ("pb_shut.y", 700.5),
              ("pb_shut.y", 890.0)]
    got = simulate_values(generated.text, generated.model_name, probes)
    assert [got[p] for p in probes] == [0, 1, 0, 1, 0, 1, 0, 1, 1, 0]


@requires_omc
@pytest.mark.slow
def test_a_button_with_no_presses_stays_released(catalogue):
    ir = plant_ir()
    ir["parameters"] = [p for p in ir["parameters"] if p["id"] != "pb_halt_press_times"]
    generated = modelica.render_modelica(SystemModel.model_validate(ir), catalogue)
    from tests._modelica_support import simulate_values

    got = simulate_values(generated.text, generated.model_name,
                          [("pb_halt.y", 0.0), ("pb_halt.y", 100.0)])
    assert set(got.values()) == {0}
