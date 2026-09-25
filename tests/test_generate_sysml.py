# Purpose: FR-05 acceptance and rules for the SysML v2 generator. The golden L1 IR is rendered and
# checked for the required element types, one `doc /* ir: <id>` per part, connection, active
# requirement and state machine, byte-identical output against a pinned snapshot, effective values
# only, and visible ASSUMPTION marks; small hand-built IRs cover escaping, regions, history, list
# values and the error paths. Validator runs are skipped with a reason when the Pilot is absent.
import copy
import json
import re
from collections import Counter
from pathlib import Path

import jinja2
import pytest
from pydantic import ValidationError

from specalive.config import load_settings
from specalive.core.catalogue import Catalogue, load_catalogue
from specalive.core.ir import SystemModel
from specalive.core.units import SI_UNITS
from specalive.generate import sysml
from specalive.toolchain import sysml_validate

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "goldens" / "L1_tank.ir.json"
SNAPSHOT = ROOT / "fixtures" / "snapshots" / "L1_tank.sysml"
FIXTURES = sorted((ROOT / "fixtures" / "sysml").glob("*.sysml"))
IR_ID = re.compile(r"doc /\* ir: (\S+)")


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


@pytest.fixture(scope="module")
def golden():
    return SystemModel.model_validate_json(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def text(golden, catalogue):
    return sysml.render_sysml(golden, catalogue)


# --- small hand-built IRs -------------------------------------------------------------------

TRACE = [{"source_id": "src_a", "locator": "line 1", "quote": "q"}]


def _port(pid, role, direction, domain, unit=None):
    return {"id": pid, "role": role, "direction": direction, "domain": domain, "unit": unit}


def _param(pid, owner, name, value, unit, status="effective"):
    return {"id": pid, "owner": owner, "name": name, "value": value, "unit": unit,
            "original": {"value": str(value), "unit": unit}, "status": status,
            "authority": "src_a", "trace": TRACE}


def small_ir() -> dict:
    return {
        "name": "small_plant",
        "description": "A tank filled through a valve by a controller.",
        "sources": [{"id": "src_a", "title": "Spec", "path": "a.txt", "role": "requirement_spec"}],
        "parts": [
            {"id": "tank_a", "kind": "tank", "name": "Tank A", "tags": ["T-A", "tankA"],
             "attributes": {"orientation": "vertical"},
             "ports": [_port("tank_a_inlet", "inlet", "in", "fluid", "m3/s"),
                       _port("tank_a_level_out", "level_out", "out", "signal_real", "m")],
             "trace": TRACE},
            {"id": "valve_a", "kind": "on_off_valve", "name": "Valve A",
             "ports": [_port("valve_a_outlet", "outlet", "out", "fluid", "m3/s"),
                       _port("valve_a_cmd_in", "cmd_in", "in", "signal_bool")],
             "trace": TRACE},
            {"id": "ctl_a", "kind": "sequence_controller", "name": "Controller",
             "ports": [_port("ctl_a_level", "level", "in", "signal_real", "m"),
                       _port("ctl_a_start", "start", "in", "signal_bool"),
                       _port("ctl_a_valve", "valve", "out", "signal_bool")],
             "assumption_ids": ["as_ctl"]},
            {"id": "state", "kind": "fluid_source", "name": "Keyword-named source",
             "ports": [_port("state_outlet", "outlet", "out", "fluid", "m3/s")],
             "trace": TRACE},
        ],
        "connections": [
            {"id": "c_feed", "from_port": "valve_a_outlet", "to_port": "tank_a_inlet",
             "medium_or_signal": "water", "trace": TRACE},
            {"id": "c_level", "from_port": "tank_a_level_out", "to_port": "ctl_a_level",
             "medium_or_signal": "level", "trace": TRACE},
            {"id": "c_cmd", "from_port": "ctl_a_valve", "to_port": "valve_a_cmd_in",
             "medium_or_signal": "command", "trace": TRACE},
        ],
        "parameters": [
            _param("tank_a_area", "tank_a", "area", 2.0, "m2"),
            _param("tank_a_high_level", "tank_a", "high_level", 0.5, "m"),
            _param("tank_a_high_level_old", "tank_a", "high_level", 0.4, "m", "superseded"),
            _param("ctl_a_wait", "ctl_a", "wait", 5.0, "s"),
            _param("system_marks", "system", "marks", [1.0, 2.0], "s"),
            _param("system_stop_time", "system", "stop_time", 60.0, "s", "verification_only"),
        ],
        "state_machines": [{
            "id": "ctl_a_seq", "owner": "ctl_a", "initial": "idle",
            "events": [{"id": "start_cmd", "port": "ctl_a_start", "edge": "rising"}],
            "timers": [{"id": "wait_timer", "duration": "ctl_a_wait"}],
            "states": [
                {"id": "idle", "name": "IDLE", "outputs": {"ctl_a_valve": False}},
                {"id": "fill", "name": "FILL", "tags": ["F1"],
                 "entry_actions": ["start_timer(wait_timer)"], "outputs": {"ctl_a_valve": True}},
                {"id": "paused", "name": "PAUSED", "outputs": {"ctl_a_valve": False}},
            ],
            "transitions": [
                {"id": "t_go", "from": "idle", "to": "fill", "trigger": "start_cmd",
                 "priority": 1},
                {"id": "t_pause", "from": "fill", "to": "paused", "trigger": "start_cmd",
                 "actions": ["save_history", "start_timer(wait_timer)"], "priority": 1},
                {"id": "t_high", "from": "fill", "to": "idle",
                 "guard": "ctl_a_level >= tank_a_high_level or timer_expired(wait_timer)",
                 "priority": 2},
                {"id": "t_resume", "from": "paused", "to": "history", "trigger": "start_cmd",
                 "priority": 1},
            ],
            "trace": TRACE,
        }],
        "requirements": [
            {"id": "req_a", "tags": ["R-A"], "text": "The tank shall fill. Comment close */ here.",
             "category": "functional", "status": "active",
             "satisfied_by": ["tank_a", "t_go", "fill", "tank_a_high_level",
                              "tank_a_high_level_old", "ctl_a_seq", "ctl_a_valve", "c_feed",
                              "system_marks"],
             "trace": TRACE},
            {"id": "req_old", "text": "Old requirement.", "category": "functional",
             "status": "superseded", "superseded_by": "req_a", "trace": TRACE},
        ],
        "assumptions": [{"id": "as_ctl", "text": "The controller is assumed to exist.",
                         "basis": "inferred", "affects": ["ctl_a"], "confidence": 0.6}],
    }


def parallel_ir() -> dict:
    ir = small_ir()
    ir["state_machines"] = [{
        "id": "ctl_a_par", "owner": "ctl_a", "initial": "a",
        "states": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}],
        "transitions": [{"id": "t_ab", "from": "a", "to": "b", "guard": "in_state(c)",
                         "priority": 1}],
        "regions": [{"id": "r_one", "name": "One", "states": ["a", "b"], "initial": "a"},
                    {"id": "r_two", "name": "Two", "states": ["c"], "initial": "c"}],
        "trace": TRACE,
    }]
    ir["requirements"][0]["satisfied_by"] = ["tank_a", "b", "t_ab"]
    return ir


def render(ir: dict, catalogue) -> str:
    return sysml.render_sysml(SystemModel.model_validate(ir), catalogue)


# --- acceptance on the golden IR ------------------------------------------------------------

def test_golden_has_the_required_element_types(text):
    # FR-05 acceptance 2: part def, port def, part usage, connection, attribute with unit,
    # requirement with satisfy, state def with transitions.
    assert re.search(r"^    part def Tank \{", text, re.M)
    assert re.search(r"^    port def FluidPort \{", text, re.M)
    assert re.search(r"^        part tk_101 : Tank \{", text, re.M)
    assert "connection if_hyd_01 connect src_101.outlet to xv_101.inlet" in text
    assert "attribute :>> area = 1.2 [m^2]" in text
    assert re.search(r"^    requirement urs_fun_001 \{", text, re.M)
    assert "satisfy urs_fun_001 by plc_101.plc_101_sequence_behaviour.tr_idle_start;" in text
    assert re.search(r"^    state def plc_101_sequence \{", text, re.M)
    assert "transition tr_idle_start first idle accept start_cmd then fill_t1" in text
    assert "private import ISQ::*;" in text and "private import SI::*;" in text


def test_every_ir_element_appears_exactly_once_by_id(golden, text):
    # FR-05 acceptance 3 / R-SYS-2.
    counts = Counter(IR_ID.findall(text))
    expected = ([p.id for p in golden.parts] + [c.id for c in golden.connections]
                + [r.id for r in golden.requirements if r.status == "active"]
                + [sm.id for sm in golden.state_machines])
    assert {eid: counts[eid] for eid in expected} == {eid: 1 for eid in expected}
    for r in golden.requirements:
        if r.status == "superseded":
            assert counts[r.id] == 0, r.id


def test_generation_is_byte_identical_and_matches_the_snapshot(golden, catalogue, text):
    # FR-05 acceptance 4 / FR-11 item 16.
    assert sysml.render_sysml(golden, catalogue) == text
    assert text == SNAPSHOT.read_text(encoding="utf-8")


def test_only_effective_values_become_model_values(text):
    # R-SYS-3: the 0.78 m / 10 s losers and the verification-only press times are not values.
    assert "attribute :>> high_level = 0.8 [m]" in text
    assert "attribute :>> wait_after_transfer = 12.0 [s]" in text
    assert "attribute :>> wait_after_drain = 8.0 [s]" in text
    assert "0.78" not in text
    assert "_urs_001" not in text
    assert "press_times =" not in text and "stop_time =" not in text


def test_verification_only_satisfiers_are_listed_as_not_modelled(text):
    block = text[text.index("requirement urs_tst_002 {"):]
    block = block[:block.index("}")]
    assert "not modelled" in block and "pb_start_press_times (verification_only" in block
    assert "satisfy urs_tst_002 by" not in text


def test_assumed_elements_are_marked(text):
    # R-SYS-4: the valves and their nominal flows carry the constant-flow assumption.
    assert text.count("ASSUMPTION as_constant_flow:") == 6
    block = text[text.index("part xv_101 : OnOffValve {"):]
    assert block.index("ASSUMPTION as_constant_flow:") < block.index("}")


def test_doc_carries_primary_source_and_locator(text):
    block = text[text.index("part tk_101 : Tank {"):]
    assert "source: urs_001 @ p.1 §2" in block[:block.index("*/")]
    assert "tags: TK-101, tank1, T1" in block[:block.index("*/")]


def test_controller_ports_are_named_by_ir_id_on_the_usage(text):
    # A role such as `start` would clash with the `start` every part inherits.
    assert "port plc_101_start : ~BoolSignal" in text
    assert "port plc_101_valve1 : BoolSignal" in text
    assert "connection if_ctl_03 connect pb_start.cmd_out to plc_101.plc_101_start" in text


def test_guards_timers_and_history_are_rendered(text):
    assert ("transition tr_fill_t1_high first fill_t1 if plc_101_level1 >= tk_101_high_level "
            "do action : start_timer { in timer = wait_after_fill_timer; } then wait_after_fill"
            in text)
    assert "if timer_expired(wait_after_fill_timer) then transfer_t1_t2" in text
    assert "transition tr_paused_start first paused accept start_cmd then history" in text
    assert "state history {" in text
    assert "in :>> tk_101_high_level = tk_101.high_level;" in text
    assert "in :>> plc_101_level1 = plc_101.plc_101_level1.value;" in text
    assert "out :>> plc_101_valve1 = plc_101.plc_101_valve1.value;" in text
    assert "attribute :>> wait_after_fill_timer = plc_101.wait_after_fill;" in text


def test_generate_layer_imports_no_llm():
    # FR-05 acceptance 5.
    pattern = re.compile(r"specalive\.llm|from \.\.llm|import llm")
    pkg = ROOT.parent / "specalive" / "generate"
    hits = [p.name for p in pkg.rglob("*") if p.is_file() and p.suffix in (".py", ".j2")
            and pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == []


# --- small IRs ------------------------------------------------------------------------------

def test_keyword_names_are_quoted(catalogue):
    out = render(small_ir(), catalogue)
    assert "part 'state' : FluidSource {" in out
    assert "doc /* ir: state" in out


def test_assumption_only_element_is_marked_and_says_it_has_no_source(catalogue):
    out = render(small_ir(), catalogue)
    block = out[out.index("part ctl_a : SequenceController {"):]
    doc = block[:block.index("*/")]
    assert "ASSUMPTION as_ctl: The controller is assumed to exist." in doc
    assert "source: none" in doc


def test_comment_terminator_in_text_cannot_close_the_doc(catalogue):
    out = render(small_ir(), catalogue)
    assert "Comment close * / here." in out
    assert "close */ here" not in out


def test_list_values_and_system_parameters(catalogue):
    out = render(small_ir(), catalogue)
    assert "attribute marks : TimeValue[*] = (1.0 [s], 2.0 [s])" in out
    assert "stop_time" not in out


def test_superseded_requirement_and_parameter_are_not_emitted(catalogue):
    out = render(small_ir(), catalogue)
    assert "req_old" not in out
    assert "= 0.4 [m]" not in out
    assert "tank_a_high_level_old (superseded" in out


def test_multi_action_effect_and_entry_outputs(catalogue):
    out = render(small_ir(), catalogue)
    assert ("do action { action : save_history; action : start_timer { in timer = wait_timer; } }"
            in out)
    assert "assign ctl_a_valve := true;" in out
    assert "perform action : start_timer { in timer = wait_timer; }" in out
    assert "if ctl_a_level >= tank_a_high_level or timer_expired(wait_timer) then idle" in out


def test_regions_become_a_parallel_state_def(catalogue):
    out = render(parallel_ir(), catalogue)
    assert "state def ctl_a_par parallel {" in out
    assert "state r_one {" in out and "state r_two {" in out
    assert "if in_state(r_two.c) then b" in out
    assert "satisfy req_a by ctl_a.ctl_a_par_behaviour.r_one.b;" in out


def test_every_si_unit_has_a_sysml_type():
    # A new SI unit in core/units.py needs a validated fixture line before it can be emitted.
    assert set(sysml.UNIT_TYPES) == set(SI_UNITS)


def test_unmapped_unit_is_an_error_not_a_guess(catalogue, monkeypatch):
    monkeypatch.delitem(sysml.UNIT_TYPES, "m2")
    with pytest.raises(sysml.SysmlGenerationError, match="m2"):
        render(small_ir(), catalogue)


def test_unknown_kind_is_an_error(catalogue):
    ir = small_ir()
    ir["parts"][3]["kind"] = "no_such_kind"
    with pytest.raises(sysml.SysmlGenerationError, match="no_such_kind"):
        render(ir, catalogue)


def test_catalogue_port_def_must_agree_with_its_domain(catalogue):
    entries = {kind: catalogue.entry(kind) for kind in catalogue.kinds}
    tank = entries["tank"].model_copy(deep=True)
    tank.sysml.ports["level_out"] = "FluidPort"
    entries["tank"] = tank
    with pytest.raises(sysml.SysmlGenerationError, match="level_out"):
        render(small_ir(), Catalogue(entries))


def test_dangling_port_fails_at_ir_validation_before_any_template(tmp_path):
    # FR-05 acceptance 6.
    ir = small_ir()
    ir["connections"][0]["to_port"] = "tank_a_nowhere"
    with pytest.raises(ValidationError, match="tank_a_nowhere"):
        SystemModel.model_validate(ir)
    path = tmp_path / "ir.json"
    path.write_text(json.dumps(ir), encoding="utf-8")
    with pytest.raises(sysml.IRError, match="tank_a_nowhere"):
        sysml.load_ir(path)


def test_templates_use_strict_undefined():
    env = sysml.environment()
    assert env.undefined is jinja2.StrictUndefined
    with pytest.raises(jinja2.UndefinedError):
        env.from_string("{{ part.missing }}").render(part={})


def test_write_sysml_writes_model_file(golden, catalogue, text, tmp_path):
    target = sysml.write_sysml(golden, catalogue, tmp_path)
    assert target == tmp_path / sysml.MODEL_FILE
    assert target.read_bytes() == text.encode("utf-8")


def test_small_ir_is_not_mutated(catalogue):
    ir = small_ir()
    before = copy.deepcopy(ir)
    render(ir, catalogue)
    assert ir == before


# --- the validator is the authority (R-SYS-5) -----------------------------------------------

requires_validator = pytest.mark.skipif(
    sysml_validate.find_jar(load_settings()) is None,
    reason="SysML v2 Pilot Implementation not found at SPECALIVE_SYSML_VALIDATOR")


@requires_validator
@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_every_construct_fixture_validates_cleanly(fixture):
    v = sysml_validate.validate_file(load_settings(), fixture)
    assert v.ok and not v.warnings, (v.detail, v.issues)


@requires_validator
@pytest.mark.slow
def test_golden_model_validates_with_zero_errors(text):
    # FR-05 acceptance 1.
    v = sysml_validate.validate_text(load_settings(), text)
    assert v.ok and not v.errors and not v.warnings, (v.detail, v.issues)


@requires_validator
@pytest.mark.slow
@pytest.mark.parametrize("build", [small_ir, parallel_ir], ids=["small", "parallel"])
def test_small_models_validate_with_zero_errors(build, catalogue):
    v = sysml_validate.validate_text(load_settings(), render(build(), catalogue))
    assert v.ok and not v.errors and not v.warnings, (v.detail, v.issues)
