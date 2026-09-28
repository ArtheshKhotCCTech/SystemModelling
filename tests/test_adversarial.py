# Purpose: FR-09 acceptance 3 — each adversarial spec in tests/adversarial/ is run through
# `specalive run` from the recorded LLM responses (no key, so a missing recording is an
# infrastructure problem and the spec is skipped with that reason, never passed) and checked
# against the [test] items of tests/adversarial/EXPECTATIONS.md, written before the first run
# (R-CLI-4). Compile and validation items are checked only where omc and the validator ran.
# Case-specific tags and values are allowed here: this is tests/, not specalive/.
import json
from collections import Counter
from pathlib import Path

import pytest

from specalive import cli
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel
from specalive.repair.compile_loop import topology

HERE = Path(__file__).resolve().parent
SPECS = HERE / "adversarial"
CACHE = HERE / "fixtures" / "extract_cache"
_RUNS: dict[str, Path] = {}


@pytest.fixture
def run(tmp_path_factory, monkeypatch):
    """The run folder for a spec, run once per session; skips when it is not recorded."""
    def _run(spec: str) -> Path:
        if spec not in _RUNS:
            monkeypatch.setenv("SPECALIVE_CACHE_DIR", str(CACHE))
            # empty, not deleted: config.py also reads .env, and a set variable wins over it
            monkeypatch.setenv("OPENAI_API_KEY", "")
            out = tmp_path_factory.mktemp(Path(spec).stem)
            cli.main(["run", str(SPECS / spec), "-o", str(out)])
            _RUNS[spec] = out
        out = _RUNS[spec]
        stages = {s["name"]: s for s in _json(out, "run.json")["stages"]}
        if stages["extract"]["status"] == "infrastructure problem":
            pytest.skip(f"no recorded LLM responses for {spec} in {CACHE}; record them with a "
                        "live `specalive run` (see tests/adversarial/RESULTS.md)")
        return out
    return _run


def _json(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def _model(out: Path) -> SystemModel:
    return SystemModel.model_validate_json((out / "ir.json").read_text(encoding="utf-8"))


def _kinds(model: SystemModel) -> Counter:
    return Counter(p.kind for p in model.parts)


def _tags(model: SystemModel) -> set[str]:
    return {t.upper() for p in model.parts for t in p.tags}


def _compiled_if_run(out: Path) -> None:
    if not (out / "repair_log.json").is_file():
        stages = {s["name"]: s for s in _json(out, "run.json")["stages"]}
        pytest.fail(f"no Modelica compile: generate {stages['generate']['status']}: "
                    f"{stages['generate']['detail']}")
    log = _json(out, "repair_log.json")
    if log["status"] == "NOT RUN":
        pytest.skip(f"omc did not run: {log.get('detail')}")
    assert log["status"] in ("ok", "repaired"), log.get("errors")


def _modelica_uses_only_ir_parts(out: Path, model: SystemModel) -> None:
    catalogue = load_catalogue()
    ids = {p.id for p in model.parts}
    assert all(p.kind in catalogue for p in model.parts)
    instances = topology((out / "model.mo").read_text(encoding="utf-8")).instances
    assert {ir_id for _, ir_id in instances} <= ids, instances


# --- one_paragraph_spec.txt -------------------------------------------------------------------

def test_one_paragraph_spec_parts(run):
    model = _model(run("one_paragraph_spec.txt"))
    kinds = _kinds(model)
    assert kinds["tank"] == 1 and kinds["on_off_valve"] == 2
    for kind in ("level_sensor", "sequence_controller", "fluid_source", "fluid_sink"):
        assert kinds[kind] >= 1, kind


def test_one_paragraph_spec_compiles_and_validates(run):
    out = run("one_paragraph_spec.txt")
    validation = _json(out, "sysml_validation.json")
    if validation["status"] != "NOT RUN":
        assert validation["ok"], validation["errors"]
    _compiled_if_run(out)


def test_one_paragraph_spec_has_no_conflict(run):
    assert _model(run("one_paragraph_spec.txt")).conflicts == []


# --- heated_tank_thermostat.txt ---------------------------------------------------------------

def test_heated_tank_keeps_the_catalogued_parts(run):
    model = _model(run("heated_tank_thermostat.txt"))
    kinds = _kinds(model)
    assert kinds["tank"] == 1 and kinds["on_off_valve"] == 2
    assert kinds["level_sensor"] >= 1 and kinds["sequence_controller"] >= 1
    assert {"HT-5", "FV-51", "DV-52", "LT-5", "PLC-5"} <= _tags(model)


def test_heater_and_thermostat_are_questions_not_parts(run):
    out = run("heated_tank_thermostat.txt")
    model = _model(out)
    assert not {"EH-5", "TC-5"} & _tags(model)
    said = " ".join(q.text for q in model.questions) + " " + " ".join(
        _json(out, "extract_report.json").get("unresolved", []))
    for tag in ("EH-5", "TC-5"):
        assert tag in said, f"{tag} is neither asked about nor reported unresolved"


def test_heated_tank_invents_no_component_and_compiles(run):
    out = run("heated_tank_thermostat.txt")
    _modelica_uses_only_ir_parts(out, _model(out))
    _compiled_if_run(out)


# --- contradiction_no_precedence.txt ----------------------------------------------------------

def _high_level_question(model: SystemModel):
    return next((q for q in model.questions
                 if "high" in q.text.lower() and any("1.0" in o or o.strip() == "1" for o in q.options)
                 and any("1.3" in o for o in q.options)), None)


def test_contradiction_becomes_a_question_with_both_values(run):
    model = _model(run("contradiction_no_precedence.txt"))
    assert _high_level_question(model) is not None, [q.text for q in model.questions]


def test_contradiction_is_not_silently_resolved(run):
    model = _model(run("contradiction_no_precedence.txt"))
    question = _high_level_question(model)
    assert question is not None
    effective = [p for p in model.parameters
                 if "high" in p.name and p.status == "effective" and p.value in (1.0, 1.3)]
    for p in effective:
        assert (p.id in question.affects or p.assumption_ids
                or question.default_if_unanswered), p.id


# --- missing_units_and_ics.txt ----------------------------------------------------------------

def _assumed(model: SystemModel, element_id: str) -> bool:
    p = next(x for x in model.parameters if x.id == element_id)
    return bool(p.assumption_ids) or any(element_id in a.affects for a in model.assumptions)


def test_unitless_values_are_assumed_or_asked(run):
    model = _model(run("missing_units_and_ics.txt"))
    asked = {e for q in model.questions for e in q.affects}
    for p in model.parameters:
        if p.original.unit.strip() in ("", "1", "-"):
            assert _assumed(model, p.id) or p.id in asked, p.id


def test_initial_level_is_a_declared_default(run):
    model = _model(run("missing_units_and_ics.txt"))
    initial = [p for p in model.parameters if "initial" in p.name]
    assert initial, [p.id for p in model.parameters]
    assert all(_assumed(model, p.id) for p in initial)


def test_outlet_flow_is_asked_or_assumed(run):
    model = _model(run("missing_units_and_ics.txt"))
    outlet = next((p for p in model.parts if "OV-72" in {t.upper() for t in p.tags}), None)
    assert outlet is not None
    flows = [p for p in model.parameters if p.owner == outlet.id and "flow" in p.name]
    asked = any(outlet.id in q.affects or "OV-72" in q.text for q in model.questions)
    assert asked or (flows and all(_assumed(model, p.id) for p in flows))


def test_missing_units_model_compiles_with_assumption_marks_or_fails_honestly(run):
    out = run("missing_units_and_ics.txt")
    data = _json(out, "run.json")
    assert (out / "report" / "summary.md").is_file()
    if (out / "model.mo").is_file():
        assert "ASSUMPTION" in (out / "model.mo").read_text(encoding="utf-8")
        _compiled_if_run(out)
    else:
        assert data["exit_code"] in (cli.EXIT_FAILED, cli.EXIT_INPUT)
