# Purpose: FR-06 requirements 8-9 and acceptance 2 for the controller generator. On the golden L1
# IR: one enumeration literal per state, the initial state as start value, transitions in IR
# priority order under one when-clause, event edges, timer start/freeze/restore, history resume,
# state-driven outputs and window-free invariants as asserts. Small IRs cover falling edges,
# entry actions, completion transitions and every refusal; omc simulates the pause/resume timer.
# Phase 9: a machine without history declares no history state and no remaining times.
import re
from pathlib import Path

import pytest

from specalive.core.catalogue import load_catalogue
from specalive.generate import controller, modelica
from tests._modelica_support import (
    golden_model,
    plant_ir,
    plant_model,
    requires_omc,
    simulate_values,
)

PKG = Path(__file__).resolve().parent.parent / "specalive"
L1_STATES = ["idle", "fill_t1", "wait_after_fill", "transfer_t1_t2", "wait_after_transfer",
             "drain_t2", "wait_after_drain", "paused", "shutdown"]


@pytest.fixture(scope="module")
def golden():
    return golden_model()


@pytest.fixture(scope="module")
def rendered(golden):
    sm = golden.state_machines[0]
    return controller.render_controller(sm, golden)


@pytest.fixture(scope="module")
def text(rendered):
    return rendered.text


def branch(text: str, state: str) -> str:
    """The body evaluated when the machine was in `state`."""
    m = re.search(rf"(?:if|elseif) pre\(state\) == State\.{state} then\n(.*?)(?=\n      elseif pre\(state\)|\n      end if;)",
                  text, re.S)
    assert m, state
    return m.group(1)


def render_plant(ir: dict) -> str:
    model = plant_model(ir)
    return controller.render_controller(model.state_machines[0], model).text


# --- the golden L1 controller -----------------------------------------------------------------

def test_class_name_and_ir_id(rendered, text):
    assert rendered.class_name == "Controller_plc_101_sequence"
    assert text.startswith("  model Controller_plc_101_sequence ")
    assert "[IR plc_101_sequence]" in text.splitlines()[0]
    assert text.rstrip().endswith("end Controller_plc_101_sequence;")


def test_nine_design_note_states_as_one_enumeration(text):
    # Acceptance 2 / requirement 8: one literal per IR state, in IR order, with its name.
    m = re.search(r"type State = enumeration\((.*?)\);", text, re.S)
    literals = re.findall(r"(\w+) \"(\w+)\"", m.group(1))
    assert [lit for lit, _ in literals] == L1_STATES
    assert dict(literals)["fill_t1"] == "FILL_T1"


def test_initial_state_is_the_start_value(text):
    assert "State state(start = State.idle, fixed = true)" in text
    assert "State history_state(start = State.idle, fixed = true)" in text


def test_connectors_come_from_the_owner_ports(text):
    assert 'SpecAlive.Interfaces.RealInput level1(unit = "m") "[IR plc_101_level1]" annotation(Placement(' in text
    assert 'SpecAlive.Interfaces.BooleanInput shut "[IR plc_101_shut]" annotation(Placement(' in text
    assert 'SpecAlive.Interfaces.BooleanOutput valve2 "[IR plc_101_valve2]" annotation(Placement(' in text


def test_machine_parameters_are_declared_without_values(rendered, text):
    assert 'parameter Real tk_101_high_level(unit = "m") "[IR tk_101_high_level]";' in text
    assert 'parameter Real plc_101_wait_after_fill(unit = "s") "[IR plc_101_wait_after_fill]";' in text
    assert rendered.parameters == sorted(rendered.parameters)
    assert "tk_101_high_level" in rendered.parameters and "tk_101_area" not in rendered.parameters


def test_one_when_clause_over_events_and_guards(text):
    m = re.search(r"when \{(.*?)\} then", text, re.S)
    conditions = [c.strip() for c in m.group(1).split(",\n")]
    assert conditions[:3] == ["edge(start)", "edge(stop)", "edge(shut)"]
    assert "pre(state) == State.fill_t1 and level1 >= tk_101_high_level" in conditions
    assert "pre(state) == State.wait_after_fill and time >= wait_after_fill_timer_deadline" \
        in conditions
    assert ("pre(state) == State.shutdown and level1 <= tk_101_low_level and "
            "level2 <= tk_102_low_level") in conditions
    assert len(conditions) == len(set(conditions))
    assert text.count("when {") == 1


def test_transitions_are_evaluated_in_priority_order(golden, text):
    sm = golden.state_machines[0]
    for state in L1_STATES:
        body = branch(text, state)
        expected = [t.id for t in sorted((t for t in sm.transitions if t.from_ == state),
                                         key=lambda t: t.priority)]
        assert re.findall(r"// IR (\w+):", body) == expected, state


def test_command_edges_and_guards_in_the_body(text):
    body = branch(text, "fill_t1")
    assert re.search(r"if edge\(shut\) then\n\s+// IR tr_fill_t1_shut", body)
    assert re.search(r"elseif edge\(stop\) then\n\s+// IR tr_fill_t1_stop", body)
    assert re.search(r"elseif level1 >= tk_101_high_level then\n\s+// IR tr_fill_t1_high", body)


def test_timer_starts_freezes_and_restores(text):
    # Acceptance 2: pause freezes the remaining timer and a history return resumes it.
    assert "wait_after_fill_timer_deadline := time + plc_101_wait_after_fill;" \
        in branch(text, "fill_t1")
    stop = branch(text, "wait_after_fill")
    assert "history_state := State.wait_after_fill;" in stop
    assert "wait_after_fill_timer_remaining := wait_after_fill_timer_deadline - time;" in stop
    resume = branch(text, "paused")
    assert "state := history_state;" in resume
    assert ("if history_state == State.wait_after_fill then wait_after_fill_timer_deadline := "
            "time + wait_after_fill_timer_remaining; end if;") in resume
    assert "discrete Real wait_after_fill_timer_deadline(start = Modelica.Constants.inf, " \
           "fixed = true)" in text


def test_clear_history_resets_to_the_initial_state(text):
    assert "history_state := State.idle;" in branch(text, "fill_t1")


def test_timers_without_a_frozen_state_are_not_saved(text):
    # A pause from a state whose timer is not running saves the state only.
    assert "_remaining :=" not in branch(text, "fill_t1")


def test_outputs_are_functions_of_the_state(text):
    assert "valve1 = state == State.fill_t1;" in text
    assert "valve2 = state == State.transfer_t1_t2 or state == State.shutdown;" in text
    assert "valve3 = state == State.drain_t2 or state == State.shutdown;" in text


def test_window_free_invariant_is_an_assert_and_windowed_checks_are_not(rendered, text):
    assert ("assert(not (valve1 and valve2) and (not (valve2 and valve3) or "
            "state == State.shutdown), \"ac_08: ") in text
    assert rendered.asserted == ["ac_08"]
    assert "ac_02" not in text and "ac_06" not in text


def test_generator_knows_no_command_names():
    # R-MO-7 / requirement 9: START, STOP and SHUT are IR events like any other.
    pattern = re.compile(r"\b(START|STOP|SHUT|shut)\b")
    files = [p for p in (PKG / "generate").rglob("*") if p.is_file()
             and p.suffix in (".py", ".j2", ".mo") and "sysml" not in p.name]
    hits = [f"{p.name}: {m.group(0)}" for p in files
            for m in pattern.finditer(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_rendering_is_deterministic(golden, text):
    assert controller.render_controller(golden.state_machines[0], golden).text == text


# --- small IRs --------------------------------------------------------------------------------

def test_falling_edge_event():
    ir = plant_ir()
    ir["state_machines"][0]["events"][0]["edge"] = "falling"
    out = render_plant(ir)
    assert "not go and pre(go)" in out and "edge(go)" not in out


def test_entry_actions_run_on_every_entry_and_timers_restore_on_history():
    ir = plant_ir()
    sm = ir["state_machines"][0]
    sm["states"][2]["entry_actions"] = ["start_timer(hold_timer)"]
    for t in sm["transitions"]:
        t["actions"] = [a for a in t.get("actions", []) if not a.startswith("start_timer")]
    out = render_plant(ir)
    assert "hold_timer_deadline := time + ctl_hold;" in branch(out, "filling")
    resume = branch(out, "paused")
    assert "hold_timer_deadline := time + ctl_hold;" not in resume
    assert ("if history_state == State.holding then hold_timer_deadline := time + "
            "hold_timer_remaining; end if;") in resume


def test_completion_transition_fires_when_its_state_is_entered():
    ir = plant_ir()
    sm = ir["state_machines"][0]
    sm["transitions"].append({"id": "t_auto", "from": "paused", "to": "idle", "priority": 5})
    out = render_plant(ir)
    assert "pre(state) == State.paused," in out or "pre(state) == State.paused}" in out
    assert re.search(r"elseif true then\n\s+// IR t_auto", branch(out, "paused"))


def test_in_state_guard_reads_the_previous_state():
    ir = plant_ir()
    ir["state_machines"][0]["transitions"][0]["guard"] = "not in_state(paused)"
    out = render_plant(ir)
    assert "if edge(go) and not pre(state) == State.paused then" in out


def test_parallel_regions_are_refused():
    ir = plant_ir()
    ir["state_machines"][0]["regions"] = [
        {"id": "r1", "name": "One", "states": ["idle", "filling"], "initial": "idle"},
        {"id": "r2", "name": "Two", "states": ["holding"], "initial": "holding"}]
    with pytest.raises(modelica.ModelicaGenerationError, match="regions"):
        render_plant(ir)


def test_equality_on_a_real_is_refused():
    ir = plant_ir()
    ir["state_machines"][0]["transitions"][2]["guard"] = "ctl_level == tank_high"
    with pytest.raises(modelica.ModelicaGenerationError, match=r"t_full.*=="):
        render_plant(ir)


def test_guard_reading_another_parts_port_is_refused():
    ir = plant_ir()
    ir["state_machines"][0]["transitions"][2]["guard"] = "tank_level_out >= tank_high"
    with pytest.raises(modelica.ModelicaGenerationError, match="tank_level_out"):
        render_plant(ir)


def test_guard_on_a_superseded_parameter_is_refused():
    ir = plant_ir()
    ir["state_machines"][0]["transitions"][2]["guard"] = "ctl_level >= tank_high_old"
    with pytest.raises(modelica.ModelicaGenerationError, match="tank_high_old"):
        render_plant(ir)


def test_real_output_needs_a_value_in_every_state():
    ir = plant_ir()
    ctl = next(p for p in ir["parts"] if p["id"] == "ctl")
    ctl["ports"].append({"id": "ctl_speed", "role": "speed", "direction": "out",
                         "domain": "signal_real", "unit": "1"})
    ir["state_machines"][0]["states"][1]["outputs"]["ctl_speed"] = 1.0
    with pytest.raises(modelica.ModelicaGenerationError, match=r"ctl_speed.*idle"):
        render_plant(ir)
    for s in ir["state_machines"][0]["states"]:
        s["outputs"].setdefault("ctl_speed", 0.0)
    out = render_plant(ir)
    assert "speed = if state == State.idle then 0.0 elseif state == State.filling then 1.0" in out


def test_internal_name_collision_is_refused():
    ir = plant_ir()
    ctl = next(p for p in ir["parts"] if p["id"] == "ctl")
    ctl["ports"][1]["role"] = "state"
    with pytest.raises(modelica.ModelicaGenerationError, match="state"):
        render_plant(ir)


def test_invariant_reading_outside_the_controller_is_not_asserted():
    ir = plant_ir()
    ir["acceptance_criteria"][0]["check"]["condition"] = "tank_level_out <= tank_high"
    model = plant_model(ir)
    rendered = controller.render_controller(model.state_machines[0], model)
    assert rendered.asserted == [] and "assert(" not in rendered.text
    result = modelica.render_modelica(model, load_catalogue())
    assert any("ac_never_both" in n and "not asserted" in n for n in result.notes)


# --- real omc: behaviour, not just text --------------------------------------------------------

@requires_omc
@pytest.mark.slow
def test_pause_freezes_and_resume_restores_the_timer():
    # go at 5 s fills to 0.5 m at 55 s; hold 10 s would end at 65 s, but halt at 60 s pauses
    # with 5 s left; go at 80 s resumes holding, so draining starts at 85 s and ends at 105 s.
    generated = modelica.render_modelica(plant_model(), load_catalogue())
    idle, filling, holding, draining, paused = 1, 2, 3, 4, 5
    probes = [("ctl.state", 50.0), ("ctl.state", 62.0), ("ctl.state", 83.0),
              ("ctl.state", 84.5), ("ctl.state", 86.0), ("ctl.state", 110.0),
              ("v_in.open", 62.0)]
    got = simulate_values(generated.text, generated.model_name, probes)
    assert got[("ctl.state", 50.0)] == filling
    assert got[("ctl.state", 62.0)] == paused
    assert got[("v_in.open", 62.0)] == 0
    assert got[("ctl.state", 83.0)] == holding
    assert got[("ctl.state", 84.5)] == holding
    assert got[("ctl.state", 86.0)] == draining
    assert got[("ctl.state", 110.0)] == idle


# --- timers that nothing freezes (phase 9) ----------------------------------------------------

def no_history_ir() -> dict:
    """The plant with no pause-with-history: halt just stops, and the hold timer is started by
    HOLDING's entry action, as a plain-text spec's controller often is."""
    ir = plant_ir()
    sm = ir["state_machines"][0]
    sm["states"][2]["entry_actions"] = ["start_timer(hold_timer)"]
    sm["transitions"] = [t for t in sm["transitions"] if t["to"] != "history"]
    for t in sm["transitions"]:
        t["actions"] = [a for a in t.get("actions", [])
                        if a not in ("save_history", "clear_history")
                        and not a.startswith("start_timer")]
    return ir


def test_a_timer_nothing_freezes_has_no_remaining_time():
    out = render_plant(no_history_ir())
    assert "hold_timer_deadline := time + ctl_hold;" in branch(out, "filling")
    assert "hold_timer_remaining" not in out  # never assigned, so never declared
    assert "history_state" not in out  # nothing saves, clears or returns to history


def test_a_frozen_timer_still_has_its_remaining_time(text):
    assert "discrete Real wait_after_fill_timer_remaining(start = 0, fixed = true)" in text


def test_a_timer_nothing_starts_is_a_constant_that_never_expires():
    # adversarial finding (contradiction spec): a discrete deadline no when-clause assigns does
    # not compile; a timer that is never started simply never expires
    ir = no_history_ir()
    ir["state_machines"][0]["states"][2]["entry_actions"] = []
    out = render_plant(ir)
    assert "discrete Real hold_timer_deadline" not in out
    assert "parameter Real hold_timer_deadline = Modelica.Constants.inf" in out
    assert "hold_timer_deadline :=" not in out
