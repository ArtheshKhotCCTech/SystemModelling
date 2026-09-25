# Purpose: FR-07 requirements 9-10 and acceptance 3-4 — structural coverage of a produced IR against
# a reference IR per category (matched by id, then by tag alias; parameters only when their
# effective values agree), and the repeatability verdict between two runs, where topology decides
# and naming differences alone do not (PRD §8.2). The golden IR is used as a reference here, in
# tests, which is the only place R-VER-5 allows it outside an explicit --golden.
from pathlib import Path

import pytest

from _modelica_support import golden_model, plant_ir, plant_model
from specalive.core.ir import SystemModel
from specalive.verify import coverage

HERE = Path(__file__).resolve().parent
CACHE = HERE / "fixtures" / "extract_cache"
L1 = next((p for p in (HERE.parent / "Testcases").glob("tank*/tank*") if p.is_dir()), None)
CATEGORIES = ("parts", "ports", "connections", "parameters", "states", "transitions")


def test_alias_key_ignores_case_and_punctuation():
    assert coverage.alias_key("TK-101") == coverage.alias_key("tk_101") == "tk101"


def test_acceptance_3_golden_against_itself_is_complete():
    golden = golden_model()
    cov = coverage.coverage(golden, golden)
    for category in CATEGORIES:
        assert cov[category]["percent"] == 100.0, (category, cov[category])
        assert cov[category]["missing"] == [] and cov[category]["extra"] == []


def test_acceptance_3_a_removed_part_lowers_the_part_share_and_is_listed():
    golden = golden_model()
    fewer = golden.model_copy(update={"parts": [p for p in golden.parts if p.id != "drn_101"]})
    cov = coverage.coverage(fewer, golden)
    assert cov["parts"]["percent"] < 100.0
    assert cov["parts"]["missing"] == ["drn_101"]
    assert "drn_101_inlet" in cov["ports"]["missing"]


def _renamed_plant() -> SystemModel:
    """The plant with every part id changed but its old id kept as a tag."""
    ir = plant_ir()
    rename = {p["id"]: f"{p['id']}_x" for p in ir["parts"]}
    port_rename = {}
    for p in ir["parts"]:
        p["tags"] = [p["id"]]
        for q in p["ports"]:
            new = q["id"].replace(p["id"], rename[p["id"]], 1)
            port_rename[q["id"]] = new
            q["id"] = new
        p["id"] = rename[p["id"]]
    for c in ir["connections"]:
        c["from_port"], c["to_port"] = port_rename[c["from_port"]], port_rename[c["to_port"]]
    for prm in ir["parameters"]:
        prm["owner"] = rename.get(prm["owner"], prm["owner"])
    for a in ir["assumptions"]:
        a["affects"] = [rename.get(x, x) for x in a["affects"]]
    sm = ir["state_machines"][0]
    sm["owner"] = rename[sm["owner"]]
    for e in sm["events"]:
        e["port"] = port_rename[e["port"]]
    for s in sm["states"]:
        s["outputs"] = {port_rename[k]: v for k, v in s["outputs"].items()}
    for t in sm["transitions"]:
        if t.get("guard"):
            t["guard"] = t["guard"].replace("ctl_level", port_rename["ctl_level"])
    for ac in ir["acceptance_criteria"]:
        cond = ac["check"]["condition"]
        for old in ("ctl_open_in", "ctl_open_out"):
            cond = cond.replace(old, port_rename[old])
        ac["check"]["condition"] = cond
    return SystemModel.model_validate(ir)


def test_matching_falls_back_to_tag_aliases():
    cov = coverage.coverage(_renamed_plant(), plant_model())
    for category in ("parts", "ports", "connections", "states", "transitions"):
        assert cov[category]["percent"] == 100.0, (category, cov[category])
    assert any(m["by"] == "alias" for m in cov["parts"]["matched"])


def test_parameter_with_a_different_effective_value_is_not_matched():
    ref = plant_model()
    ir = plant_ir()
    for p in ir["parameters"]:
        if p["id"] == "tank_high":
            p["value"] = 0.6
    cov = coverage.coverage(SystemModel.model_validate(ir), ref)
    assert cov["parameters"]["percent"] < 100.0
    [bad] = cov["parameters"]["mismatched"]
    assert bad["reference"] == "tank_high"
    assert (bad["reference_value"], bad["produced_value"]) == (0.5, 0.6)


def test_parameter_values_within_tolerance_match():
    ir = plant_ir()
    for p in ir["parameters"]:
        if p["id"] == "tank_high":
            p["value"] = 0.5 * (1 + 1e-9)
    cov = coverage.coverage(SystemModel.model_validate(ir), plant_model())
    assert cov["parameters"]["percent"] == 100.0


def test_extra_elements_are_listed():
    golden = golden_model()
    fewer = golden.model_copy(update={"parts": [p for p in golden.parts if p.id != "drn_101"]})
    cov = coverage.coverage(golden, fewer)
    assert cov["parts"]["extra"] == ["drn_101"] and cov["parts"]["percent"] == 100.0


# --- repeatability ---------------------------------------------------------------------------

def test_repeatability_of_identical_irs():
    verdict = coverage.repeatability(golden_model(), golden_model())
    assert verdict["identical"] is True and verdict["differences"] == []


def test_renaming_alone_is_not_a_repeatability_failure():
    verdict = coverage.repeatability(plant_model(), _renamed_plant())
    assert verdict["identical"] is True
    assert verdict["naming_differences"]


def test_a_topology_change_is_a_repeatability_failure():
    golden = golden_model()
    fewer = golden.model_copy(update={
        "parts": [p for p in golden.parts if p.id != "drn_101"],
        "connections": [c for c in golden.connections if c.to_port != "drn_101_inlet"]})
    verdict = coverage.repeatability(golden, fewer)
    assert verdict["identical"] is False
    assert any("fluid_sink" in d for d in verdict["differences"])


@pytest.mark.skipif(L1 is None or not any(CACHE.glob("*.json")),
                    reason="Testcases/ L1 bundle or recorded LLM responses not present")
def test_acceptance_4_two_cached_l1_runs_are_identical():
    from specalive.config import load_settings
    from specalive.extract.extract import run_extract
    from specalive.ingest.ingest import ingest
    from specalive.llm.client import LLMClient

    settings = load_settings({"SPECALIVE_CACHE_DIR": str(CACHE)})
    first = run_extract(ingest(L1, settings, llm=None), LLMClient(settings)).model
    second = run_extract(ingest(L1, settings, llm=None), LLMClient(settings)).model
    verdict = coverage.repeatability(first, second)
    assert verdict["identical"] is True, verdict["differences"]
