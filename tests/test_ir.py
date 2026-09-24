# Purpose: pins the IR contract of FR-02 on a small hand-built model — the shape of every
# record, the honesty rule (R-IR-2: no element without a trace or an assumption), every
# cross-reference resolving, SI-only parameter units (R-IR-4), a single effective value per
# parameter, and guards/actions being parsed expressions over IR ids (R-IR-6), never free text.
import copy

import pytest
from pydantic import ValidationError

from specalive.core.ir import (
    BoolOp,
    Call,
    Compare,
    ExpressionError,
    Name,
    Not,
    Number,
    SystemModel,
    expression_names,
    parse_action,
    parse_expression,
)

T = {"source_id": "spec", "locator": "p.1 §2", "quote": "The tank shall be filled."}


def minimal() -> dict:
    """A fresh, valid model; deep-copied so tests may mutate it freely."""
    return copy.deepcopy(_minimal())


def _minimal() -> dict:
    return {
        "name": "mini",
        "description": "Smallest model exercising every record.",
        "sources": [
            {"id": "spec", "title": "Spec", "path": "spec.txt", "role": "requirement_spec",
             "revision": "A", "date": "2026-01-15", "reliability": "high", "tags": ["SPEC-1"]},
            {"id": "cr_1", "title": "Change record", "path": None, "role": "change_record"},
        ],
        "parts": [
            {"id": "src", "kind": "fluid_source", "name": "Source", "tags": ["SRC"],
             "ports": [{"id": "src_outlet", "role": "outlet", "direction": "out",
                        "domain": "fluid", "unit": "m3/s"}],
             "trace": [T]},
            {"id": "tank", "kind": "tank", "name": "Tank", "tags": ["TK", "tank"],
             "attributes": {"orientation": "vertical"},
             "ports": [
                 {"id": "tank_inlet", "role": "inlet", "direction": "in", "domain": "fluid",
                  "unit": "m3/s"},
                 {"id": "tank_level_out", "role": "level_out", "direction": "out",
                  "domain": "signal_real", "unit": "m"},
             ],
             "trace": [T], "confidence": 0.9},
            {"id": "ctl", "kind": "sequence_controller", "name": "Controller",
             "ports": [
                 {"id": "ctl_level_in", "role": "level_in", "direction": "in",
                  "domain": "signal_real", "unit": "m"},
                 {"id": "ctl_start", "role": "start", "direction": "in",
                  "domain": "signal_bool"},
                 {"id": "ctl_valve", "role": "valve", "direction": "out",
                  "domain": "signal_bool"},
             ],
             "trace": [T]},
        ],
        "connections": [
            {"id": "c_fluid", "from_port": "src_outlet", "to_port": "tank_inlet",
             "medium_or_signal": "liquid", "trace": [T]},
            {"id": "c_level", "from_port": "tank_level_out", "to_port": "ctl_level_in",
             "medium_or_signal": "level", "trace": [T]},
        ],
        "parameters": [
            {"id": "tank_high", "owner": "tank", "name": "high_level", "value": 0.8, "unit": "m",
             "original": {"value": "0.80", "unit": "m"}, "status": "effective",
             "authority": "cr_1", "trace": [T]},
            {"id": "tank_high_spec", "owner": "tank", "name": "high_level", "value": 0.78,
             "unit": "m", "original": {"value": "0.78", "unit": "m"}, "status": "superseded",
             "authority": "spec", "trace": [T]},
            {"id": "ctl_wait", "owner": "ctl", "name": "wait", "value": 10, "unit": "s",
             "original": {"value": "10", "unit": "s"}, "status": "effective",
             "authority": "spec", "trace": [T]},
            {"id": "stop_time", "owner": "system", "name": "stop_time", "value": 900,
             "unit": "s", "original": {"value": "900", "unit": "s"},
             "status": "verification_only", "authority": "spec", "trace": [T]},
            {"id": "start_press_times", "owner": "ctl", "name": "press_times",
             "value": [20, 280], "unit": "s", "original": {"value": "20, 280", "unit": "s"},
             "status": "verification_only", "authority": "spec", "trace": [T]},
        ],
        "state_machines": [
            {"id": "sm", "owner": "ctl", "initial": "idle",
             "events": [{"id": "ev_start", "port": "ctl_start", "edge": "rising"}],
             "timers": [{"id": "t_wait", "duration": "ctl_wait"}],
             "states": [
                 {"id": "idle", "name": "IDLE", "outputs": {"ctl_valve": False}},
                 {"id": "fill", "name": "FILL", "tags": ["FILLING"],
                  "outputs": {"ctl_valve": True}},
                 {"id": "hold", "name": "HOLD", "outputs": {"ctl_valve": False}},
                 {"id": "paused", "name": "PAUSED", "outputs": {"ctl_valve": False}},
             ],
             "transitions": [
                 {"id": "tr_start", "from": "idle", "to": "fill", "trigger": "ev_start",
                  "priority": 1},
                 {"id": "tr_full", "from": "fill", "to": "hold",
                  "guard": "ctl_level_in >= tank_high", "actions": ["start_timer(t_wait)"],
                  "priority": 2},
                 {"id": "tr_done", "from": "hold", "to": "idle",
                  "guard": "timer_expired(t_wait)", "priority": 2},
                 {"id": "tr_pause", "from": "hold", "to": "paused", "trigger": "ev_start",
                  "actions": ["save_history"], "priority": 1},
                 {"id": "tr_resume", "from": "paused", "to": "history", "trigger": "ev_start",
                  "priority": 1},
             ],
             "trace": [T]},
        ],
        "requirements": [
            {"id": "req_old", "tags": ["REQ-0"], "text": "High level 0.78 m.",
             "category": "performance", "status": "superseded", "superseded_by": "req_new",
             "trace": [T]},
            {"id": "req_new", "tags": ["REQ-1"], "text": "High level 0.80 m.",
             "category": "performance", "status": "active",
             "satisfied_by": ["tank_high", "sm"], "trace": [T]},
        ],
        "acceptance_criteria": [
            {"id": "ac_1", "tags": ["AC-1"], "text": "Valve closed in the first 10 s.",
             "check": {"mode": "always", "condition": "not ctl_valve and in_state(idle)",
                       "start_s": 0, "end_s": 10},
             "trace": [T]},
            {"id": "ac_2", "tags": ["AC-2"], "text": "Fill follows the wait.",
             "check": None, "reason": "Timing relative to a state event.", "trace": [T]},
        ],
        "assumptions": [
            {"id": "as_1", "text": "Tank starts empty.", "basis": "default",
             "affects": ["tank"], "confidence": 0.5},
        ],
        "questions": [
            {"id": "q_1", "text": "Which high level?", "options": ["0.78 m", "0.80 m"],
             "default_if_unanswered": "0.80 m", "affects": ["tank_high"]},
        ],
        "conflicts": [
            {"id": "cf_1", "subject": {"element_id": "tank_high", "field": "value"},
             "candidates": [
                 {"value": "0.80 m", "source_id": "cr_1", "authority_rank": 1,
                  "element_id": "tank_high"},
                 {"value": "0.78 m", "source_id": "spec", "authority_rank": 3,
                  "element_id": "tank_high_spec"},
             ],
             "resolution": "0.80 m", "rationale": "Approved change outranks the baseline."},
        ],
    }


def _find(items: list[dict], item_id: str) -> dict:
    return next(i for i in items if i["id"] == item_id)


def _fails(data: dict, *fragments: str) -> None:
    with pytest.raises(ValidationError) as exc:
        SystemModel.model_validate(data)
    text = str(exc.value)
    for fragment in fragments:
        assert fragment in text, text


# --- the valid model ----------------------------------------------------------------------

def test_minimal_model_validates():
    model = SystemModel.model_validate(minimal())
    assert [p.id for p in model.parts] == ["src", "tank", "ctl"]
    assert model.state_machines[0].transitions[0].from_ == "idle"


def test_json_round_trip_uses_from_key():
    model = SystemModel.model_validate(minimal())
    text = model.model_dump_json()
    assert '"from":"idle"' in text.replace(" ", "")
    again = SystemModel.model_validate_json(text)
    assert again == model


def test_unknown_field_is_rejected():
    data = minimal()
    data["parts"][0]["colour"] = "red"
    _fails(data, "colour")


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_confidence_is_bounded(value):
    data = minimal()
    data["parts"][0]["confidence"] = value
    _fails(data, "confidence")


# --- R-IR-2: trace or assumption ----------------------------------------------------------

@pytest.mark.parametrize(
    "collection,item_id",
    [
        ("parts", "tank"),
        ("connections", "c_fluid"),
        ("parameters", "ctl_wait"),
        ("state_machines", "sm"),
        ("requirements", "req_new"),
    ],
)
def test_element_without_trace_or_assumption_is_rejected(collection, item_id):
    data = minimal()
    _find(data[collection], item_id)["trace"] = []
    _fails(data, item_id, "trace")


@pytest.mark.parametrize(
    "collection,item_id",
    [("parts", "tank"), ("connections", "c_fluid"), ("parameters", "ctl_wait"),
     ("state_machines", "sm"), ("requirements", "req_new")],
)
def test_assumption_replaces_trace(collection, item_id):
    data = minimal()
    item = _find(data[collection], item_id)
    item["trace"] = []
    item["assumption_ids"] = ["as_1"]
    SystemModel.model_validate(data)


def test_port_inherits_part_trace():
    data = minimal()
    assert "trace" not in data["parts"][1]["ports"][0]
    SystemModel.model_validate(data)


def test_port_of_untraced_part_needs_own_trace_or_the_part_fails():
    data = minimal()
    data["parts"][1]["trace"] = []
    _fails(data, "tank")


def test_unknown_assumption_id_is_rejected():
    data = minimal()
    data["parts"][1]["assumption_ids"] = ["as_missing"]
    _fails(data, "as_missing")


@pytest.mark.parametrize("quote", ["", "x" * 301])
def test_quote_must_be_non_empty_and_short(quote):
    data = minimal()
    data["parts"][1]["trace"] = [{**T, "quote": quote}]
    _fails(data, "quote")


# --- cross-references ---------------------------------------------------------------------

def test_dangling_connection_port_is_rejected():
    data = minimal()
    data["connections"][0]["to_port"] = "tank_nowhere"
    _fails(data, "c_fluid", "tank_nowhere")


def test_connection_domains_must_match():
    data = minimal()
    data["connections"][0]["to_port"] = "ctl_level_in"
    _fails(data, "c_fluid", "domain")


def test_connection_cannot_start_at_an_input_port():
    data = minimal()
    data["connections"][0]["from_port"] = "tank_inlet"
    data["connections"][0]["to_port"] = "tank_inlet"
    _fails(data, "c_fluid", "direction")


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda d: d["parameters"][0].update(owner="ghost"), "ghost"),
        (lambda d: d["parameters"][0].update(authority="ghost_src"), "ghost_src"),
        (lambda d: d["parts"][1]["trace"][0].update(source_id="ghost_src"), "ghost_src"),
        (lambda d: d["assumptions"][0].update(affects=["ghost"]), "ghost"),
        (lambda d: d["questions"][0].update(affects=["ghost"]), "ghost"),
        (lambda d: d["requirements"][1].update(satisfied_by=["ghost"]), "ghost"),
        (lambda d: d["requirements"][0].update(superseded_by="ghost"), "ghost"),
        (lambda d: d["state_machines"][0].update(owner="ghost"), "ghost"),
        (lambda d: d["state_machines"][0].update(initial="ghost"), "ghost"),
        (lambda d: d["state_machines"][0]["transitions"][0].update(to="ghost"), "ghost"),
        (lambda d: d["state_machines"][0]["transitions"][0].update(trigger="ghost"), "ghost"),
        (lambda d: d["state_machines"][0]["events"][0].update(port="ghost"), "ghost"),
        (lambda d: d["state_machines"][0]["timers"][0].update(duration="ghost"), "ghost"),
        (lambda d: d["state_machines"][0]["states"][0].update(outputs={"ghost": False}),
         "ghost"),
        (lambda d: d["conflicts"][0]["subject"].update(element_id="ghost"), "ghost"),
        (lambda d: d["conflicts"][0]["candidates"][0].update(source_id="ghost_src"),
         "ghost_src"),
        (lambda d: d["conflicts"][0]["candidates"][0].update(element_id="ghost"), "ghost"),
    ],
)
def test_dangling_reference_is_rejected(mutate, fragment):
    data = minimal()
    mutate(data)
    _fails(data, fragment)


def test_state_output_must_be_an_output_port():
    data = minimal()
    data["state_machines"][0]["states"][0]["outputs"] = {"ctl_start": False}
    _fails(data, "ctl_start")


def test_duplicate_id_across_collections_is_rejected():
    data = minimal()
    data["connections"][0]["id"] = "tank"
    _fails(data, "tank", "duplicate")


@pytest.mark.parametrize("bad", ["TK-101", "Tank", "1tank", "tank level"])
def test_illegal_id_is_rejected(bad):
    data = minimal()
    data["assumptions"][0]["id"] = bad
    _fails(data, bad)


# --- parameters ---------------------------------------------------------------------------

def test_parameter_unit_must_be_si():
    data = minimal()
    data["parameters"][0]["unit"] = "mm"
    _fails(data, "tank_high", "mm")


def test_only_one_effective_value_per_owner_and_name():
    data = minimal()
    data["parameters"][1]["status"] = "effective"
    _fails(data, "high_level", "effective")


def test_superseded_value_is_kept():
    model = SystemModel.model_validate(minimal())
    statuses = {p.id: p.status for p in model.parameters}
    assert statuses["tank_high_spec"] == "superseded"


# --- requirements and acceptance criteria -------------------------------------------------

def test_active_requirement_cannot_be_superseded_by_another():
    data = minimal()
    data["requirements"][0]["status"] = "active"
    _fails(data, "req_old", "superseded_by")


def test_criterion_without_check_needs_a_reason():
    data = minimal()
    data["acceptance_criteria"][1]["reason"] = None
    _fails(data, "ac_2", "reason")


def test_at_check_needs_a_time():
    data = minimal()
    data["acceptance_criteria"][0]["check"] = {"mode": "at", "condition": "not ctl_valve"}
    _fails(data, "ac_1", "start_s")


def test_check_window_must_be_ordered():
    data = minimal()
    data["acceptance_criteria"][0]["check"].update(start_s=20, end_s=10)
    _fails(data, "ac_1")


def test_check_condition_unknown_state_is_rejected():
    data = minimal()
    data["acceptance_criteria"][0]["check"]["condition"] = "in_state(ghost)"
    _fails(data, "ghost")


# --- state machines -----------------------------------------------------------------------

def test_guard_with_unknown_identifier_is_rejected():
    data = minimal()
    data["state_machines"][0]["transitions"][1]["guard"] = "ctl_level_in >= ghost_level"
    _fails(data, "tr_full", "ghost_level")


def test_guard_with_bad_syntax_is_rejected():
    data = minimal()
    data["state_machines"][0]["transitions"][1]["guard"] = "level is high"
    _fails(data, "tr_full")


def test_timer_expired_of_unknown_timer_is_rejected():
    data = minimal()
    data["state_machines"][0]["transitions"][2]["guard"] = "timer_expired(t_ghost)"
    _fails(data, "t_ghost")


def test_unknown_action_verb_is_rejected():
    data = minimal()
    data["state_machines"][0]["transitions"][1]["actions"] = ["open_everything"]
    _fails(data, "open_everything")


def test_history_target_needs_a_saving_transition():
    data = minimal()
    data["state_machines"][0]["transitions"][3]["actions"] = []
    _fails(data, "history", "save_history")


def test_priorities_are_unique_per_source_state():
    data = minimal()
    data["state_machines"][0]["transitions"][3]["priority"] = 2
    _fails(data, "hold", "priority")


def test_region_with_unknown_state_is_rejected():
    data = minimal()
    data["state_machines"][0]["regions"] = [
        {"id": "r_main", "name": "main", "states": ["idle", "ghost"], "initial": "idle"}]
    _fails(data, "ghost")


# --- expression language ------------------------------------------------------------------

def test_parse_comparison():
    assert parse_expression("lt_101 >= tk_high") == Compare(">=", Name("lt_101"), Name("tk_high"))


def test_precedence_not_and_or():
    expr = parse_expression("not a or b and c <= 0.05")
    assert expr == BoolOp("or", Not(Name("a")),
                          BoolOp("and", Name("b"), Compare("<=", Name("c"), Number(0.05))))


def test_parentheses_and_calls():
    expr = parse_expression("(timer_expired(t1) and in_state(idle))")
    assert expr == BoolOp("and", Call("timer_expired", "t1"), Call("in_state", "idle"))


def test_expression_names_excludes_call_arguments():
    expr = parse_expression("a >= b and timer_expired(t1) or not c")
    assert expression_names(expr) == {"a", "b", "c"}


@pytest.mark.parametrize(
    "text",
    ["", "a >=", "a >= b >= c", "a and", "(a", "a)", "timer_expired()", "a = b",
     "a >= 'b'", "unknown_fn(a)", "a b"],
)
def test_bad_expressions_raise(text):
    with pytest.raises(ExpressionError):
        parse_expression(text)


def test_parse_actions():
    assert parse_action("start_timer(t1)").verb == "start_timer"
    assert parse_action("start_timer(t1)").args == ("t1",)
    assert parse_action("save_history").args == ()


@pytest.mark.parametrize("text", ["start_timer", "save_history(x)", "explode(x)", "a := 1"])
def test_bad_actions_raise(text):
    with pytest.raises(ExpressionError):
        parse_action(text)


def test_minimal_is_not_mutated_by_validation():
    data = minimal()
    before = copy.deepcopy(data)
    SystemModel.model_validate(data)
    assert data == before
