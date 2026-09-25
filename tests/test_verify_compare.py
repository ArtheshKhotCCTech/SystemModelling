# Purpose: FR-07 requirements 3-6 — the reference trace is found (ingestion's reference_data CSV
# or --reference), each reference column is mapped to an IR element by tag, port role and unit or
# listed NOT COMPARED with the reason, continuous signals are compared by error at the reference
# sample times, discrete signals and states by change times within a tolerance whose source is
# stated (R-VER-2, R-VER-3). Case-specific values are allowed here: this is tests/.
import json
from pathlib import Path

import pytest

from _modelica_support import golden_model, plant_ir, plant_model
from specalive.config import load_settings
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel
from specalive.generate import modelica
from specalive.verify import compare
from specalive.verify.compare import ColumnMapping, Reference
from specalive.verify.simulate import (StateVariable, Trace, VariableMap, VerifyInputError,
                                       variable_map)

HERE = Path(__file__).resolve().parent
L1 = next((p for p in (HERE.parent / "Testcases").glob("tank*/tank*") if p.is_dir()), None)
L1_REFERENCE = L1 / "09_datasets" / "10_demo_run_900s.csv" if L1 else None


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


def _varmap(model: SystemModel, catalogue):
    generated = modelica.render_modelica(model, catalogue)
    return variable_map(model, catalogue, generated.text, generated.model_name)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    lines = [",".join(header)] + [",".join(str(v) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- finding and reading the reference -------------------------------------------------------

def _evidence(run: Path, root: Path, sources: list[dict]) -> None:
    (run / "evidence.json").write_text(json.dumps({"root": str(root), "sources": sources,
                                                   "chunks": []}), encoding="utf-8")


def _source(sid, path, role="reference_data", fmt="csv"):
    return {"id": sid, "path": path, "format": fmt, "status": "read", "role": role}


def test_explicit_reference_wins(tmp_path):
    ref = _write_csv(tmp_path / "given.csv", ["time", "x"], [[0, 1]])
    path, how = compare.find_reference(tmp_path, ref)
    assert path == ref and "--reference" in how


def test_explicit_reference_that_does_not_exist_is_an_input_problem(tmp_path):
    with pytest.raises(VerifyInputError, match="missing.csv"):
        compare.find_reference(tmp_path, tmp_path / "missing.csv")


def test_reference_found_through_evidence_role(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "data").mkdir(parents=True)
    _write_csv(bundle / "data" / "run.csv", ["time", "x"], [[0, 1]])
    _evidence(tmp_path, bundle, [_source("src_a", "notes.txt", role="design_note", fmt="text"),
                                 _source("src_b", "data/run.csv")])
    path, how = compare.find_reference(tmp_path, None)
    assert path == bundle / "data" / "run.csv" and "reference_data" in how and "src_b" in how


def test_no_reference_is_a_reason_not_an_error(tmp_path):
    path, why = compare.find_reference(tmp_path, None)
    assert path is None and "--reference" in why


def test_several_reference_csvs_are_not_guessed_between(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in ("a.csv", "b.csv"):
        _write_csv(bundle / name, ["time", "x"], [[0, 1]])
    _evidence(tmp_path, bundle, [_source("src_a", "a.csv"), _source("src_b", "b.csv")])
    path, why = compare.find_reference(tmp_path, None)
    assert path is None and "a.csv" in why and "b.csv" in why


def test_load_reference_finds_the_time_column(tmp_path):
    ref = compare.load_reference(_write_csv(tmp_path / "r.csv", ["time_s", "level_m", "mode"],
                                            [[0, 0.1, "IDLE"], [1, 0.2, "RUN"]]))
    assert ref.time_column == "time_s" and ref.times == [0.0, 1.0]
    assert ref.columns == {"level_m": ["0.1", "0.2"], "mode": ["IDLE", "RUN"]}


def test_load_reference_without_a_time_column_is_an_input_problem(tmp_path):
    with pytest.raises(VerifyInputError, match="time"):
        compare.load_reference(_write_csv(tmp_path / "r.csv", ["a", "b"], [[0, 1]]))


# --- tolerances ------------------------------------------------------------------------------

def test_event_tolerance_comes_from_the_ir_when_stated():
    tol = compare.tolerances(golden_model(), load_settings({}))
    assert tol.event_time.value == 2.0
    assert "system_state_timing_tolerance" in tol.event_time.source
    assert not tol.event_time.declared_default


def test_event_tolerance_falls_back_to_a_declared_default():
    tol = compare.tolerances(plant_model(), load_settings({"SPECALIVE_EVENT_TOLERANCE": "0.5"}))
    assert tol.event_time.value == 0.5 and tol.event_time.declared_default
    assert "SPECALIVE_EVENT_TOLERANCE" in tol.event_time.source
    assert tol.continuous_fraction.value == 0.02 and tol.continuous_fraction.declared_default


# --- column mapping --------------------------------------------------------------------------

@pytest.mark.skipif(L1_REFERENCE is None or not L1_REFERENCE.is_file(),
                    reason="Testcases/ L1 bundle not present")
def test_l1_reference_columns_map_to_ir_elements(catalogue):
    ref = compare.load_reference(L1_REFERENCE)
    model = golden_model()
    got = {m.column: m for m in compare.map_columns(ref, model, _varmap(model, catalogue))}
    expected = {
        "cmd_start": ("pb_start_cmd_out", "pb_start.y", "discrete"),
        "cmd_stop": ("pb_stop_cmd_out", "pb_stop.y", "discrete"),
        "cmd_shut": ("pb_shut_cmd_out", "pb_shut.y", "discrete"),
        "tank1_level_m": ("tk_101_level_out", "tk_101.level", "continuous"),
        "tank2_level_m": ("tk_102_level_out", "tk_102.level", "continuous"),
        "valve1_open": ("xv_101_cmd_in", "xv_101.open", "discrete"),
        "valve2_open": ("xv_102_cmd_in", "xv_102.open", "discrete"),
        "valve3_open": ("xv_103_cmd_in", "xv_103.open", "discrete"),
        "controller_state": ("plc_101_sequence", "plc_101.state", "state"),
    }
    for column, (ir_id, variable, kind) in expected.items():
        m = got[column]
        assert (m.status, m.ir_id, m.variable, m.kind) == ("mapped", ir_id, variable, kind), m
        assert m.reason
    assert got["wait_remaining_s"].status == compare.NOT_COMPARED
    assert got["wait_remaining_s"].reason


def _ref(columns: dict[str, list], times=None) -> Reference:
    n = len(next(iter(columns.values())))
    return Reference(Path("r.csv"), "time", times or [float(i) for i in range(n)],
                     {k: [str(v) for v in vs] for k, vs in columns.items()})


def test_ambiguous_column_is_not_compared(catalogue):
    ir = plant_ir()
    for part in ir["parts"]:
        if part["id"] in ("v_in", "v_out"):
            part["tags"] = ["valve"]
    model = plant_model(ir)
    [m] = compare.map_columns(_ref({"valve_open": [0, 1]}), model, _varmap(model, catalogue))
    assert m.status == compare.NOT_COMPARED and "v_in" in m.reason and "v_out" in m.reason


def test_unit_mismatch_is_not_compared(catalogue):
    model = plant_model()
    [m] = compare.map_columns(_ref({"tank_level_s": [0, 1]}), model, _varmap(model, catalogue))
    assert m.status == compare.NOT_COMPARED and "unit" in m.reason


def test_column_naming_no_element_is_not_compared(catalogue):
    model = plant_model()
    [m] = compare.map_columns(_ref({"pump_speed": [0, 1]}), model, _varmap(model, catalogue))
    assert m.status == compare.NOT_COMPARED and m.variable is None


def test_state_column_is_recognised_by_its_values(catalogue):
    model = plant_model()
    [m] = compare.map_columns(_ref({"mode": ["IDLE", "FILLING", "HOLDING"]}), model,
                              _varmap(model, catalogue))
    assert (m.status, m.kind, m.ir_id, m.variable) == ("mapped", "state", "ctl_seq", "ctl.state")


# --- comparisons -----------------------------------------------------------------------------

def _tol(event=2.0, frac=0.02):
    return compare.Tolerances(compare.Tolerance(event, "s", "test", False),
                              compare.Tolerance(frac, "1", "test", True))


def _mapping(column, kind, variable, ir_id="x"):
    return ColumnMapping(column, "mapped", kind, ir_id, variable, "test")


def test_continuous_signal_errors_at_reference_sample_times():
    ref = _ref({"lvl": [0.0, 1.0, 2.0]})
    trace = Trace([0.0, 2.0], {"t.level": [0.0, 2.1]})  # linear, 1.05 at t=1
    [r] = compare.compare_signals(ref, trace, [_mapping("lvl", "continuous", "t.level")],
                                  plant_model(), VariableMap(), _tol(frac=0.1))
    assert r.status == compare.PASS
    assert r.numbers["max_abs_error"] == pytest.approx(0.1)
    assert r.numbers["at_time"] == pytest.approx(2.0)
    assert r.numbers["tolerance_abs"] == pytest.approx(0.2)
    assert r.numbers["samples"] == 3


def test_continuous_signal_outside_tolerance_fails():
    ref = _ref({"lvl": [0.0, 1.0, 2.0]})
    trace = Trace([0.0, 2.0], {"t.level": [0.0, 3.0]})
    [r] = compare.compare_signals(ref, trace, [_mapping("lvl", "continuous", "t.level")],
                                  plant_model(), VariableMap(), _tol())
    assert r.status == compare.FAIL and r.numbers["max_abs_error"] == pytest.approx(1.0)


def test_discrete_change_times_within_tolerance_pass():
    ref = _ref({"open": [0, 0, 1, 1, 1, 0, 0, 0]})  # rises at 2, falls at 5
    trace = Trace([0.0, 1.4, 1.4, 6.5, 6.5, 7.0],
                  {"v.open": [0.0, 0.0, 1.0, 1.0, 0.0, 0.0]})
    [r] = compare.compare_signals(ref, trace, [_mapping("open", "discrete", "v.open")],
                                  plant_model(), VariableMap(), _tol())
    assert r.status == compare.PASS
    assert r.numbers["reference_changes"] == 2 and r.numbers["model_changes"] == 2
    assert r.numbers["max_time_error"] == pytest.approx(1.5)
    assert r.numbers["tolerance_s"] == 2.0


def test_discrete_change_outside_tolerance_fails_naming_it():
    ref = _ref({"open": [0, 0, 1, 1, 1, 1, 1]})
    trace = Trace([0.0, 5.0, 5.0, 6.0], {"v.open": [0.0, 0.0, 1.0, 1.0]})
    [r] = compare.compare_signals(ref, trace, [_mapping("open", "discrete", "v.open")],
                                  plant_model(), VariableMap(), _tol())
    assert r.status == compare.FAIL and "2" in r.detail and "5" in r.detail


def test_missing_change_fails():
    ref = _ref({"open": [0, 1, 0, 1]})
    trace = Trace([0.0, 1.0, 1.0, 3.0], {"v.open": [0.0, 0.0, 1.0, 1.0]})
    [r] = compare.compare_signals(ref, trace, [_mapping("open", "discrete", "v.open")],
                                  plant_model(), VariableMap(), _tol())
    assert r.status == compare.FAIL
    assert (r.numbers["reference_changes"], r.numbers["model_changes"]) == (3, 1)


def test_states_compare_through_names_and_aliases():
    ir = plant_ir()
    ir["state_machines"][0]["states"][1]["tags"] = ["FILL"]
    model = plant_model(ir)
    ref = _ref({"mode": ["IDLE", "FILL", "FILL", "HOLDING"]})
    # enumeration index: 1 idle, 2 filling, 3 holding
    trace = Trace([0.0, 0.5, 0.5, 3.0, 3.0], {"ctl.state": [1.0, 1.0, 2.0, 2.0, 3.0]})
    vm = VariableMap(states={"ctl_seq": StateVariable(
        "ctl_seq", "ctl.state", ("idle", "filling", "holding", "draining", "paused"))})
    [r] = compare.compare_signals(ref, trace, [_mapping("mode", "state", "ctl.state", "ctl_seq")],
                                  model, vm, _tol())
    assert r.status == compare.PASS, r.detail
    assert [p["value"] for p in r.numbers["changes"]] == ["filling", "holding"]


def test_unmapped_column_is_not_compared_and_never_passes():
    ref = _ref({"x": [0, 1]})
    m = ColumnMapping("x", compare.NOT_COMPARED, None, None, None, "no element")
    [r] = compare.compare_signals(ref, Trace([0.0], {}), [m], plant_model(), VariableMap(),
                                  _tol())
    assert r.status == compare.NOT_COMPARED and r.detail == "no element"


def test_variable_missing_from_the_result_is_not_compared():
    ref = _ref({"lvl": [0.0, 1.0]})
    [r] = compare.compare_signals(ref, Trace([0.0, 1.0], {}),
                                  [_mapping("lvl", "continuous", "t.level")], plant_model(),
                                  VariableMap(), _tol())
    assert r.status == compare.NOT_COMPARED and "t.level" in r.detail
