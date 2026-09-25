# Purpose: FR-07 requirement 1 and acceptance 1 — which model a run folder delivers (the repaired
# file when the repair loop produced one, never an uncompiled model), omc's CSV result loaded as a
# trace, and the IR id -> result variable map built from the generator's `[IR id]` descriptions
# and the catalogue connectors, so verification states which model variable stands for which IR
# element. Real simulations run only when omc is installed.
import json

import pytest

from _modelica_support import golden_model, plant_model, requires_omc
from specalive.config import load_settings
from specalive.core.catalogue import load_catalogue
from specalive.generate import modelica
from specalive.toolchain import omc
from specalive.verify import simulate
from specalive.verify.simulate import ModelChoice, Trace, VerifyInputError


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


@pytest.fixture(scope="module")
def golden_generated(catalogue):
    return modelica.render_modelica(golden_model(), catalogue)


def _run_folder(tmp_path, status="ok", delivered="model.mo", model="P.System", files=("model.mo",)):
    for name in files:
        (tmp_path / name).write_text("package P end P;\n", encoding="utf-8")
    log = {"status": status, "model": model, "delivered": delivered, "command": None,
           "detail": "", "errors": [], "attempts": []}
    (tmp_path / "repair_log.json").write_text(json.dumps(log), encoding="utf-8")
    return tmp_path


# --- which model to simulate -----------------------------------------------------------------

def test_choose_model_takes_the_delivered_file_and_the_compiled_model_name(tmp_path):
    choice = simulate.choose_model(_run_folder(tmp_path))
    assert choice == ModelChoice(tmp_path / "model.mo", "P.System")


def test_choose_model_prefers_the_repaired_file(tmp_path):
    run = _run_folder(tmp_path, status="repaired", delivered="model.repaired.mo",
                      files=("model.mo", "model.repaired.mo"))
    assert simulate.choose_model(run).path == tmp_path / "model.repaired.mo"


def test_choose_model_without_a_compile_is_an_input_problem(tmp_path):
    (tmp_path / "model.mo").write_text("package P end P;\n", encoding="utf-8")
    with pytest.raises(VerifyInputError, match="specalive compile"):
        simulate.choose_model(tmp_path)


def test_choose_model_refuses_a_model_that_did_not_compile(tmp_path):
    with pytest.raises(VerifyInputError, match="did not compile"):
        simulate.choose_model(_run_folder(tmp_path, status="FAILED", delivered=None))


def test_choose_model_with_the_delivered_file_missing_is_an_input_problem(tmp_path):
    with pytest.raises(VerifyInputError, match="model.repaired.mo"):
        simulate.choose_model(_run_folder(tmp_path, status="repaired",
                                          delivered="model.repaired.mo"))


# --- the result trace ------------------------------------------------------------------------

def test_load_result_reads_omc_csv_with_event_rows(tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text('"time","tank.level","ctl.open"\n0,0.5,0\n10.0000001,0.6,0\n10.0000001,0.6,1\n'
                   "20,0.7,1\n", encoding="utf-8")
    trace = simulate.load_result(csv)
    assert trace.times == [0.0, 10.0000001, 10.0000001, 20.0]
    assert trace.values["ctl.open"] == [0.0, 0.0, 1.0, 1.0]
    assert trace.columns == ("tank.level", "ctl.open")


def test_load_result_of_an_empty_file_is_an_input_problem(tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text("", encoding="utf-8")
    with pytest.raises(VerifyInputError):
        simulate.load_result(csv)


# --- IR id -> model variable -----------------------------------------------------------------

def test_variable_map_on_the_golden_model(golden_generated, catalogue):
    vm = simulate.variable_map(golden_model(), catalogue, golden_generated.text,
                               golden_generated.model_name)
    assert vm.ports["tk_101_level_out"] == "tk_101.level"
    assert vm.ports["xv_101_cmd_in"] == "xv_101.open"
    assert vm.ports["lt_101_level_out"] == "lt_101.y"
    assert vm.ports["pb_start_cmd_out"] == "pb_start.y"
    assert vm.ports["plc_101_valve1"] == "plc_101.valve1"
    assert vm.ports["plc_101_level1"] == "plc_101.level1"
    state = vm.states["plc_101_sequence"]
    assert state.variable == "plc_101.state"
    assert state.states == tuple(s.id for s in golden_model().state_machines[0].states)


def test_variable_map_of_every_golden_port(golden_generated, catalogue):
    vm = simulate.variable_map(golden_model(), catalogue, golden_generated.text,
                               golden_generated.model_name)
    all_ports = {q.id for p in golden_model().parts for q in p.ports}
    assert set(vm.ports) == all_ports
    assert vm.notes == []


def test_variable_map_reports_what_it_cannot_find_instead_of_guessing(catalogue):
    vm = simulate.variable_map(plant_model(), catalogue, "package P\nend P;\n", "P.System")
    assert vm.ports == {} and vm.states == {}
    assert any("no instance" in note for note in vm.notes)


def test_trace_value_lookup_is_by_variable():
    trace = Trace([0.0, 1.0], {"a.b": [1.0, 2.0]})
    assert trace.columns == ("a.b",)
    assert trace.values["a.b"][1] == 2.0


# --- real simulations ------------------------------------------------------------------------

@requires_omc
def test_acceptance_1_simulates_an_msl_example_before_any_generated_model(tmp_path):
    # FR-07 acceptance 1. The ADR records why the Fluid ControlledTanks replaces the StateGraph one.
    sim = simulate.run_simulation(load_settings(), ModelChoice(None, omc.PROBE_MODEL), tmp_path)
    assert sim.status == omc.OK, sim.result.detail
    assert sim.result_csv == tmp_path / "sim" / "result.csv" and sim.result_csv.is_file()
    assert sim.trace is not None and sim.trace.times[-1] > 0
    assert sim.result.command and "simulate.mos" in sim.result.command


@requires_omc
def test_run_simulation_of_the_generated_golden_model(golden_generated, catalogue, tmp_path):
    mo = tmp_path / "model.mo"
    mo.write_text(golden_generated.text, encoding="utf-8")
    sim = simulate.run_simulation(load_settings(),
                                  ModelChoice(mo, golden_generated.model_name), tmp_path)
    assert sim.status == omc.OK, sim.result.detail
    assert sim.trace.times[-1] == pytest.approx(900.0)
    assert "plc_101.state" in sim.trace.values and "tk_101.level" in sim.trace.values
