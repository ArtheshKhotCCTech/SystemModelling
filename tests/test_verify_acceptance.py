# Purpose: FR-07 requirements 7-8 and acceptance 5 — each IR acceptance criterion with a check is
# evaluated on the simulation result (value at a time, always / eventually over a window, "never
# simultaneously" written as an always), a criterion that cannot be checked is NOT CHECKED with
# the reason and never a pass (R-VER-1), and an interlock assert that stops the run is a FAIL of
# that criterion with the time and the assert message.
import pytest

from _modelica_support import plant_ir, plant_model, requires_omc
from specalive.config import load_settings
from specalive.core.catalogue import load_catalogue
from specalive.generate import modelica
from specalive.toolchain import omc
from specalive.verify import acceptance, simulate
from specalive.verify.simulate import ModelChoice, Trace


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


def _with_criteria(*criteria) -> dict:
    ir = plant_ir()
    ir["acceptance_criteria"] = list(criteria)
    return ir


def _crit(cid, mode, condition, start=None, end=None):
    return {"id": cid, "text": f"criterion {cid}",
            "check": {"mode": mode, "condition": condition, "start_s": start, "end_s": end}}


def _setup(ir, catalogue):
    model = plant_model(ir)
    generated = modelica.render_modelica(model, catalogue)
    vm = simulate.variable_map(model, catalogue, generated.text, generated.model_name)
    return model, vm


def _trace(vm, times, **series):
    """Series keyed by IR port id (or 'state' for the controller state index)."""
    values = {}
    for key, vals in series.items():
        variable = vm.states["ctl_seq"].variable if key == "state" else vm.ports[key]
        values[variable] = [float(v) for v in vals]
    return Trace(list(times), values)


def _one(results, cid):
    return next(r for r in results if r.id == cid)


NEVER_BOTH = _crit("ac_both", "always", "not (ctl_open_in and ctl_open_out)")


def test_always_holds(catalogue):
    model, vm = _setup(_with_criteria(NEVER_BOTH), catalogue)
    trace = _trace(vm, [0, 5, 10], ctl_open_in=[1, 0, 0], ctl_open_out=[0, 0, 1])
    r = _one(acceptance.evaluate_criteria(model, trace, vm), "ac_both")
    assert r.status == acceptance.PASS


def test_always_fails_at_the_first_violation(catalogue):
    model, vm = _setup(_with_criteria(NEVER_BOTH), catalogue)
    trace = _trace(vm, [0, 5, 7, 9], ctl_open_in=[1, 1, 1, 1], ctl_open_out=[0, 0, 1, 1])
    r = _one(acceptance.evaluate_criteria(model, trace, vm), "ac_both")
    assert r.status == acceptance.FAIL and r.time == 7.0 and "7" in r.detail


def test_window_starts_after_the_event_at_its_start_and_excludes_its_end(catalogue):
    model, vm = _setup(_with_criteria(_crit("ac_w", "always", "not ctl_open_in", 60, 80)),
                       catalogue)
    # open just before 60 (left limit), closed from 60 (right limit), reopens exactly at 80
    trace = _trace(vm, [0, 60.00000005, 60.00000005, 70, 80.00000005, 80.00000005, 90],
                   ctl_open_in=[1, 1, 0, 0, 0, 1, 1])
    assert _one(acceptance.evaluate_criteria(model, trace, vm), "ac_w").status == acceptance.PASS


def test_window_violation_inside_fails(catalogue):
    model, vm = _setup(_with_criteria(_crit("ac_w", "always", "not ctl_open_in", 60, 80)),
                       catalogue)
    trace = _trace(vm, [0, 60, 70, 70, 90], ctl_open_in=[0, 0, 0, 1, 1])
    r = _one(acceptance.evaluate_criteria(model, trace, vm), "ac_w")
    assert r.status == acceptance.FAIL and r.time == 70.0


def test_value_at_a_time_reads_the_state_after_events_at_that_time(catalogue):
    model, vm = _setup(_with_criteria(_crit("ac_at", "at", "in_state(filling)", 10)), catalogue)
    trace = _trace(vm, [0, 10.00000005, 10.00000005, 20], state=[1, 1, 2, 2])
    assert _one(acceptance.evaluate_criteria(model, trace, vm), "ac_at").status == acceptance.PASS
    trace = _trace(vm, [0, 10, 20], state=[1, 1, 1])
    r = _one(acceptance.evaluate_criteria(model, trace, vm), "ac_at")
    assert r.status == acceptance.FAIL and r.time == 10.0


def test_eventually_with_a_parameter_operand(catalogue):
    model, vm = _setup(_with_criteria(_crit("ac_ev", "eventually", "ctl_level >= tank_high")),
                       catalogue)
    trace = _trace(vm, [0, 30, 60], ctl_level=[0.0, 0.3, 0.5])
    r = _one(acceptance.evaluate_criteria(model, trace, vm), "ac_ev")
    assert r.status == acceptance.PASS and r.time == 60.0
    trace = _trace(vm, [0, 30, 60], ctl_level=[0.0, 0.3, 0.4])
    assert _one(acceptance.evaluate_criteria(model, trace, vm), "ac_ev").status == acceptance.FAIL


def test_criterion_without_a_check_is_not_checked_with_its_reason(catalogue):
    ir = _with_criteria({"id": "ac_free", "text": "Operators are happy.", "check": None,
                         "reason": "not machine checkable"})
    model, vm = _setup(ir, catalogue)
    r = _one(acceptance.evaluate_criteria(model, _trace(vm, [0], state=[1]), vm), "ac_free")
    assert r.status == acceptance.NOT_CHECKED and r.detail == "not machine checkable"


def test_timer_reads_are_not_checked(catalogue):
    model, vm = _setup(_with_criteria(_crit("ac_t", "always", "not timer_expired(hold_timer)")),
                       catalogue)
    r = _one(acceptance.evaluate_criteria(model, _trace(vm, [0], state=[1]), vm), "ac_t")
    assert r.status == acceptance.NOT_CHECKED and "hold_timer" in r.detail


def test_operand_missing_from_the_result_is_not_checked(catalogue):
    model, vm = _setup(_with_criteria(NEVER_BOTH), catalogue)
    r = _one(acceptance.evaluate_criteria(model, _trace(vm, [0, 1], state=[1, 1]), vm), "ac_both")
    assert r.status == acceptance.NOT_CHECKED and "ctl_open_in" in r.detail


def test_no_simulation_means_nothing_is_checked(catalogue):
    model, vm = _setup(plant_ir(), catalogue)
    results = acceptance.evaluate_criteria(model, None, vm, not_run_reason="omc not found")
    assert results and all(r.status == acceptance.NOT_CHECKED for r in results)
    assert all("omc not found" in r.detail for r in results)


def test_window_past_the_end_of_the_run_is_not_checked(catalogue):
    model, vm = _setup(_with_criteria(_crit("ac_w", "always", "not ctl_open_in", 60, 500)),
                       catalogue)
    trace = _trace(vm, [0, 100, 200], ctl_open_in=[0, 0, 0])
    r = _one(acceptance.evaluate_criteria(model, trace, vm), "ac_w")
    assert r.status == acceptance.NOT_CHECKED and "200" in r.detail


def test_assert_stop_fails_its_criterion_and_leaves_later_windows_unchecked(catalogue):
    ir = _with_criteria(NEVER_BOTH, _crit("ac_late", "always", "not ctl_open_in", 100, 150),
                        _crit("ac_early", "always", "not ctl_open_out", 0, 20))
    model, vm = _setup(ir, catalogue)
    trace = _trace(vm, [0, 30, 42], ctl_open_in=[0, 1, 1], ctl_open_out=[0, 0, 1])
    stop = omc.AssertionStop(42.0, "ac_both: criterion ac_both")
    results = acceptance.evaluate_criteria(model, trace, vm, assertion=stop)
    both = _one(results, "ac_both")
    assert both.status == acceptance.FAIL and both.time == 42.0 and "ac_both" in both.detail
    assert _one(results, "ac_late").status == acceptance.NOT_CHECKED
    assert _one(results, "ac_early").status == acceptance.PASS


@requires_omc
def test_acceptance_5_a_violated_interlock_fails_with_its_name_and_time(catalogue, tmp_path):
    ir = plant_ir()
    for s in ir["state_machines"][0]["states"]:
        if s["id"] == "draining":
            s["outputs"] = {"ctl_open_out": True, "ctl_open_in": True}  # breaks ac_never_both
    for p in ir["parameters"]:
        if p["id"] == "pb_go_press_times":
            p["value"], p["original"]["value"] = [5.0], "5"
        if p["id"] == "pb_halt_press_times":
            p["value"], p["original"]["value"] = [500.0], "500"
    model = plant_model(ir)
    generated = modelica.render_modelica(model, catalogue)
    mo = tmp_path / "model.mo"
    mo.write_text(generated.text, encoding="utf-8")
    sim = simulate.run_simulation(load_settings(), ModelChoice(mo, generated.model_name), tmp_path)
    assert sim.status == omc.FAILED and sim.result.assertion is not None, sim.result.detail
    vm = simulate.variable_map(model, catalogue, generated.text, generated.model_name)
    results = acceptance.evaluate_criteria(model, sim.trace, vm, complete=False,
                                           assertion=sim.result.assertion)
    r = _one(results, "ac_never_both")
    # filled 0 -> 0.5 m at 0.01 m3/s over 1 m2 from 5 s, held 10 s: draining begins at 65 s
    assert r.status == acceptance.FAIL and r.time == pytest.approx(65.0, abs=0.1)
    assert "ac_never_both" in r.detail
