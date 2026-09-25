# Purpose: FR-04 acceptance 1-5 and 7 on the L1 Tank bundle, and acceptance 6's text spec, served
# offline from the recorded LLM responses in tests/fixtures/extract_cache/ (no key: a missing entry
# fails loudly, meaning the fixtures must be re-recorded after a prompt change). Structural
# coverage against the golden IR is computed here, in tests/, until phase 7's coverage.py lands.
# Case-specific values are allowed here: this is tests/, not specalive/.
import json
from pathlib import Path

import pytest

from specalive.config import load_settings
from specalive.core.ir import SystemModel
from specalive.extract.extract import extract_text, run_extract, write_ir
from specalive.extract.merge import name_key
from specalive.ingest.ingest import ingest
from specalive.llm.client import LLMClient

HERE = Path(__file__).resolve().parent
CACHE = HERE / "fixtures" / "extract_cache"
GOLDEN = HERE / "goldens" / "L1_tank.ir.json"
L1 = next((p for p in (HERE.parent / "Testcases").glob("tank*/tank*") if p.is_dir()), None)
TEXT_SPEC = HERE / "adversarial" / "one_paragraph_spec.txt"

pytestmark = [
    pytest.mark.skipif(L1 is None, reason="Testcases/ L1 bundle not present"),
    pytest.mark.skipif(not any(CACHE.glob("*.json")),
                       reason="no recorded LLM responses in tests/fixtures/extract_cache/"),
]


@pytest.fixture(scope="module")
def settings():
    return load_settings({"SPECALIVE_CACHE_DIR": str(CACHE)})


@pytest.fixture(scope="module")
def evidence(settings):
    return ingest(L1, settings, llm=None)


@pytest.fixture(scope="module")
def result(evidence, settings):
    return run_extract(evidence, LLMClient(settings))


@pytest.fixture(scope="module")
def model(result):
    return result.model


def coverage(model: SystemModel) -> dict[str, float]:
    golden = SystemModel.model_validate_json(GOLDEN.read_text(encoding="utf-8"))

    def share(ref, got):
        return len(ref & got) / len(ref)

    return {
        "parts": share({p.id for p in golden.parts}, {p.id for p in model.parts}),
        "ports": share({q.id for p in golden.parts for q in p.ports},
                       {q.id for p in model.parts for q in p.ports}),
        "connections": share({(c.from_port, c.to_port) for c in golden.connections},
                             {(c.from_port, c.to_port) for c in model.connections}),
    }


def _part_with(model, *names):
    keys = {name_key(n) for n in names}
    return next((p for p in model.parts if keys <= {name_key(t) for t in p.tags}), None)


def test_acceptance_1_ir_validates_against_the_schema(model):
    SystemModel.model_validate(json.loads(model.model_dump_json(by_alias=True)))


@pytest.mark.parametrize("owner_tags, value, loser", [
    (("TK-101", "T1"), 0.80, "0.78"),
])
def test_acceptance_2_t1_high_level(model, owner_tags, value, loser):
    tank = _part_with(model, *owner_tags)
    assert tank is not None
    eff = [p for p in model.parameters if p.owner == tank.id and p.status == "effective"
           and p.value == pytest.approx(value)]
    assert eff, "no effective 0.80 m parameter on T1"
    conflicts = [c for c in model.conflicts if c.subject.element_id in {p.id for p in eff}]
    assert conflicts and any(loser in cand.value for c in conflicts for cand in c.candidates)


@pytest.mark.parametrize("value, loser", [(12.0, "10"), (8.0, "10")])
def test_acceptance_2_changed_waits(model, value, loser):
    ids = {p.id: p for p in model.parameters}
    hits = [c for c in model.conflicts
            if c.subject.element_id in ids
            and ids[c.subject.element_id].status == "effective"
            and ids[c.subject.element_id].unit == "s"
            and ids[c.subject.element_id].value == pytest.approx(value)]
    assert hits, f"no conflict resolved to {value} s"
    assert any(cand.value.startswith(loser) for c in hits for cand in c.candidates)
    sources = {s.id: s for s in model.sources}
    assert all(sources[cand.source_id] for c in hits for cand in c.candidates)


def test_acceptance_3_shut_is_a_controlled_drain_command_traced_to_the_review(model):
    shut = _part_with(model, "SHUT")
    assert shut is not None and shut.kind == "command_button"
    roles = {s.id: s.role for s in model.sources}
    assert any(roles[t.source_id] == "review_decision" for t in shut.trace)
    assert not any("emergency" in str(v).lower() and "not" not in str(v).lower()
                   for v in shut.attributes.values())


def test_acceptance_4_aliases_are_one_part(model):
    assert _part_with(model, "tank1", "TK-101", "T1") is not None
    assert _part_with(model, "valve1", "XV-101", "V1") is not None


def test_acceptance_5_structural_coverage_at_least_80_percent(model):
    cov = coverage(model)
    print("coverage vs golden:", {k: f"{v:.0%}" for k, v in cov.items()})
    assert all(v >= 0.8 for v in cov.values()), cov


def test_acceptance_7_repeat_run_gives_identical_ir(result, evidence, settings, tmp_path):
    again = run_extract(evidence, LLMClient(settings))
    a = write_ir(result, tmp_path / "a").read_bytes()
    b = write_ir(again, tmp_path / "b").read_bytes()
    assert a == b


def test_acceptance_6_text_spec_gives_a_valid_ir(settings):
    result = extract_text(TEXT_SPEC.read_text(encoding="utf-8"), LLMClient(settings),
                          name=TEXT_SPEC.name)
    SystemModel.model_validate(json.loads(result.model.model_dump_json(by_alias=True)))
    assert result.model.parts
