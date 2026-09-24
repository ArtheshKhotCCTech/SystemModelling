# Purpose: FR-02 acceptance for the hand-written L1 golden IR — it validates, losing a trace or a
# port reference fails with the element named, the committed JSON Schema matches ir.py, every
# kind and port role is in the catalogue, core imports without openai, and the golden holds the
# effective L1 values, the nine states, the TP-17 criteria and the three conflicts. Quotes from
# plain-text sources are checked verbatim against the bundle.
import copy
import email
import json
import subprocess
import sys
from email import policy
from pathlib import Path

import pytest
from pydantic import ValidationError

from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel, json_schema_text

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "goldens" / "L1_tank.ir.json"
SCHEMA = ROOT / "docs" / "ir.schema.json"
BUNDLE = ROOT / "Testcases" / "tank_sysmlv2_full_dataset" / "tank_sysmlv2_full_dataset"
TEXT_SUFFIXES = {".md", ".txt", ".mo", ".puml", ".csv", ".eml"}


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def model(data) -> SystemModel:
    return SystemModel.model_validate(data)


def _params(model: SystemModel) -> dict:
    return {p.id: p for p in model.parameters}


# --- acceptance 1-5 ------------------------------------------------------------------------

def test_golden_validates(model):
    assert model.name


def test_part_without_trace_fails_naming_the_part(data):
    broken = copy.deepcopy(data)
    broken["parts"][0]["trace"] = []
    broken["parts"][0]["assumption_ids"] = []
    with pytest.raises(ValidationError) as exc:
        SystemModel.model_validate(broken)
    assert broken["parts"][0]["id"] in str(exc.value)


def test_dangling_port_reference_fails_naming_the_connection(data):
    broken = copy.deepcopy(data)
    broken["connections"][0]["to_port"] = "no_such_port"
    with pytest.raises(ValidationError) as exc:
        SystemModel.model_validate(broken)
    assert broken["connections"][0]["id"] in str(exc.value)
    assert "no_such_port" in str(exc.value)


def test_committed_json_schema_matches_ir():
    assert SCHEMA.read_text(encoding="utf-8") == json_schema_text()


def test_every_kind_and_role_is_in_the_catalogue(model):
    assert load_catalogue().check_model(model) == []


def test_core_ir_imports_without_openai():
    r = subprocess.run(
        [sys.executable, "-c", "import specalive.core.ir, sys; print('openai' in sys.modules)"],
        capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


# --- requirement 19: effective values, states, interlocks, criteria --------------------------

def test_part_inventory(model):
    by_kind: dict[str, int] = {}
    for part in model.parts:
        by_kind[part.kind] = by_kind.get(part.kind, 0) + 1
    assert by_kind == {"tank": 2, "on_off_valve": 3, "level_sensor": 2, "command_button": 3,
                       "sequence_controller": 1, "fluid_source": 1, "fluid_sink": 1}


def test_parts_carry_their_aliases(model):
    tags = {p.id: set(p.tags) for p in model.parts}
    assert {"TK-101", "tank1", "T1"} <= tags["tk_101"]
    assert {"XV-102", "valve2", "V2"} <= tags["xv_102"]
    assert {"PLC-101", "tankController"} <= tags["plc_101"]


@pytest.mark.parametrize(
    "param_id,value,unit",
    [
        ("tk_101_high_level", 0.80, "m"),
        ("tk_101_low_level", 0.05, "m"),
        ("tk_102_low_level", 0.05, "m"),
        ("plc_101_wait_after_fill", 10, "s"),
        ("plc_101_wait_after_transfer", 12, "s"),
        ("plc_101_wait_after_drain", 8, "s"),
        ("tk_101_area", 1.2, "m2"),
        ("tk_102_area", 1.4, "m2"),
        ("xv_101_nominal_flow", 0.006, "m3/s"),
        ("xv_102_nominal_flow", 0.0045, "m3/s"),
        ("xv_103_nominal_flow", 0.005, "m3/s"),
    ],
)
def test_effective_values(model, param_id, value, unit):
    p = _params(model)[param_id]
    assert p.status == "effective"
    assert p.value == pytest.approx(value)
    assert p.unit == unit


@pytest.mark.parametrize(
    "param_id,value",
    [("tk_101_high_level_urs_001", 0.78),
     ("plc_101_wait_after_transfer_urs_001", 10),
     ("plc_101_wait_after_drain_urs_001", 10)],
)
def test_superseded_values_are_kept(model, param_id, value):
    p = _params(model)[param_id]
    assert p.status == "superseded"
    assert p.value == pytest.approx(value)


def test_command_schedule_is_verification_only(model):
    params = _params(model)
    assert params["pb_start_press_times"].value == [20, 280]
    assert params["pb_stop_press_times"].value == [220, 650]
    assert params["pb_shut_press_times"].value == [700]
    assert params["system_stop_time"].value == 900
    for pid in ("pb_start_press_times", "pb_stop_press_times", "pb_shut_press_times",
                "system_stop_time"):
        assert params[pid].status == "verification_only"


def test_nine_controller_states_with_valve_patterns(model):
    (sm,) = model.state_machines
    patterns = {s.name: tuple(s.outputs[f"plc_101_valve{i}"] for i in (1, 2, 3))
                for s in sm.states}
    assert patterns == {
        "IDLE": (False, False, False),
        "FILL_T1": (True, False, False),
        "WAIT_AFTER_FILL": (False, False, False),
        "TRANSFER_T1_T2": (False, True, False),
        "WAIT_AFTER_TRANSFER": (False, False, False),
        "DRAIN_T2": (False, False, True),
        "WAIT_AFTER_DRAIN": (False, False, False),
        "PAUSED": (False, False, False),
        "SHUTDOWN": (False, True, True),
    }
    assert sm.initial == "idle"


def test_command_priority_shut_stop_start(model):
    (sm,) = model.state_machines
    events = {e.id: e for e in sm.events}
    for state in ("fill_t1", "wait_after_fill", "transfer_t1_t2", "wait_after_transfer",
                  "drain_t2", "wait_after_drain"):
        outgoing = {events[t.trigger].port: t for t in sm.transitions
                    if t.from_ == state and t.trigger}
        assert outgoing["plc_101_shut"].priority < outgoing["plc_101_stop"].priority
        assert outgoing["plc_101_stop"].to == "paused"
        assert "save_history" in outgoing["plc_101_stop"].actions
        assert outgoing["plc_101_shut"].to == "shutdown"
        assert "plc_101_start" not in outgoing  # START while running is ignored


def test_shutdown_ignores_commands_and_needs_both_tanks_low(model):
    (sm,) = model.state_machines
    out = [t for t in sm.transitions if t.from_ == "shutdown"]
    assert len(out) == 1 and out[0].trigger is None and out[0].to == "idle"
    assert "tk_101_low_level" in out[0].guard and "tk_102_low_level" in out[0].guard


def test_resume_goes_to_history(model):
    (sm,) = model.state_machines
    resume = [t for t in sm.transitions if t.from_ == "paused" and t.to == "history"]
    assert len(resume) == 1


def test_legacy_state_names_are_aliases(model):
    (sm,) = model.state_machines
    tags = {s.id: set(s.tags) for s in sm.states}
    assert tags["wait_after_fill"] == {"HOLD1"}
    assert tags["wait_after_transfer"] == {"HOLD2"}
    assert tags["wait_after_drain"] == {"HOLD3"}
    assert tags["fill_t1"] == {"FILL"}


def test_tp17_acceptance_criteria(model):
    acs = {a.tags[0]: a for a in model.acceptance_criteria}
    assert set(acs) == {f"AC-0{i}" for i in range(1, 9)}
    for ac in acs.values():
        assert ac.check is not None or ac.reason


def test_interlock_requirements_present(model):
    reqs = {r.tags[0]: r for r in model.requirements}
    assert reqs["URS-SAF-003"].status == "active"
    assert reqs["URS-SAF-005"].status == "active"


def test_superseded_requirements_point_to_replacements(model):
    reqs = {r.id: r for r in model.requirements}
    assert reqs["urs_per_001"].superseded_by == "urs_per_002"
    assert reqs["urs_fun_006"].superseded_by == "urs_per_005"
    assert reqs["urs_fun_008"].superseded_by == "urs_per_006"


# --- requirement 20: conflicts ---------------------------------------------------------------

@pytest.mark.parametrize(
    "subject,winner,loser",
    [("tk_101_high_level", "0.80 m", "0.78 m"),
     ("plc_101_wait_after_transfer", "12 s", "10 s"),
     ("plc_101_wait_after_drain", "8 s", "10 s")],
)
def test_conflicts_recorded(model, subject, winner, loser):
    (conflict,) = [c for c in model.conflicts if c.subject.element_id == subject]
    assert conflict.resolution == winner
    values = [c.value for c in conflict.candidates]
    assert winner in values and loser in values
    best = min(conflict.candidates, key=lambda c: c.authority_rank)
    assert best.value == winner and best.source_id == "cr_004"
    assert conflict.rationale


# --- honesty: quotes are verbatim ----------------------------------------------------------

def _source_text(path: Path) -> str:
    if path.suffix == ".eml":
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        headers = "\n".join(f"{k}: {v}" for k, v in msg.items())
        return headers + "\n" + msg.get_body().get_content()
    return path.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_plain_text_quotes_are_verbatim(model, data):
    paths = {s.id: s.path for s in model.sources if s.path}
    checked = 0
    missing = []
    for link in _all_trace_links(data):
        path = paths.get(link["source_id"])
        if not path or Path(path).suffix not in TEXT_SUFFIXES:
            continue
        text = _squash(_source_text(BUNDLE / path))
        checked += 1
        if _squash(link["quote"]) not in text:
            missing.append(f'{link["source_id"]} {link["locator"]}: {link["quote"]!r}')
    assert checked > 0
    assert missing == []


def _all_trace_links(node):
    if isinstance(node, dict):
        if {"source_id", "locator", "quote"} <= node.keys():
            yield node
        for value in node.values():
            yield from _all_trace_links(value)
    elif isinstance(node, list):
        for value in node:
            yield from _all_trace_links(value)
