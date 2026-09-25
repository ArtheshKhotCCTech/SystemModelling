# Purpose: FR-03 acceptance 1-5 on the four supplied bundles under Testcases/ — ingest completes,
# every file is a Source with a status (and a reason when not read), the L1 CR-004 row and email
# messages are located, the L1 roles are right, and evidence.json is byte-identical across runs.
# Case-specific values are allowed here: this is tests/, not specalive/.
from pathlib import Path

import pytest

from specalive.config import load_settings
from specalive.ingest.ingest import ingest, write_evidence

ROOT = Path(__file__).resolve().parent.parent / "Testcases"
BUNDLES = sorted(p for p in ROOT.glob("*/*") if p.is_dir()) if ROOT.is_dir() else []
L1 = next((b for b in BUNDLES if b.name.startswith("tank")), None)

pytestmark = pytest.mark.skipif(not BUNDLES, reason="Testcases/ bundles not present")


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    # No API key: classification must not reach the network in the test suite.
    return load_settings({"SPECALIVE_CACHE_DIR": str(tmp_path_factory.mktemp("cache"))})


@pytest.fixture(scope="module")
def evidence(settings):
    return {b.name: ingest(b, settings, llm=None) for b in BUNDLES}


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name)
def test_every_file_is_a_source(bundle, evidence):
    ev = evidence[bundle.name]
    files = sorted(p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file())
    assert [s.path for s in ev.sources] == files
    for s in ev.sources:
        assert s.status in ("read", "partial", "unread")
        assert s.status == "read" or s.reason, s.path


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name)
def test_only_images_are_unread_with_vision_off(bundle, evidence):
    unread = [s for s in evidence[bundle.name].sources if s.status == "unread"]
    assert all(s.format == "image" for s in unread), [(s.path, s.reason) for s in unread]


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name)
def test_every_source_is_classified_from_the_bundle_index(bundle, evidence):
    for s in evidence[bundle.name].sources:
        assert s.classification_trace is not None, s.path
        assert s.reliability in ("high", "medium", "low"), s.path


@pytest.mark.skipif(L1 is None, reason="L1 bundle not present")
def test_l1_cr004_row_is_located_by_sheet_and_row(evidence):
    ev = evidence[L1.name]
    row = next(c for c in ev.chunks
               if c.fields.get("Source") == "CR-004" and c.fields.get("Value") == "0.8")
    assert row.locator == "sheet Operating_Parameters, row 7"
    assert "Parameter: High level limit" in row.text and "Units: m" in row.text
    change = next(c for c in ev.chunks if c.fields.get("Record") == "CR-004")
    assert change.role == "change_record"
    assert "0.78 -> 0.80 m" in change.text


@pytest.mark.skipif(L1 is None, reason="L1 bundle not present")
def test_l1_email_thread_yields_messages(evidence):
    ev = evidence[L1.name]
    mail = next(s for s in ev.sources if s.format == "eml")
    msgs = [c for c in ev.chunks if c.source_id == mail.id and c.kind == "email_message"]
    assert len(msgs) >= 3
    assert "0.78" in msgs[-1].text  # the oldest message states the stale value
    assert msgs[0].text.startswith("From: s.patel@")


@pytest.mark.skipif(L1 is None, reason="L1 bundle not present")
@pytest.mark.parametrize("suffix, role", [
    ("07_legacy_tank_demo.mo", "legacy_model"),
    ("06_design_review_minutes.md", "review_decision"),
    ("09_test_procedure_TP17.pdf", "verification_procedure"),
    ("05_controls_email_thread.eml", "correspondence"),
    ("04_control_logic_design_notes.docx", "design_note"),
    ("01_customer_URS.pdf", "requirement_spec"),
    ("08_valve_datasheet.pdf", "datasheet"),
    ("12_operator_shift_notes.txt", "informal_note"),
    ("11_partial_legacy_architecture.puml", "legacy_architecture"),
    ("10_demo_run_900s.csv", "reference_data"),
])
def test_l1_roles(evidence, suffix, role):
    s = next(s for s in evidence[L1.name].sources if s.path.endswith(suffix))
    assert s.role == role


@pytest.mark.skipif(L1 is None, reason="L1 bundle not present")
def test_l1_evidence_is_byte_identical_across_runs(settings, tmp_path):
    a = write_evidence(ingest(L1, settings, llm=None), tmp_path / "a")
    b = write_evidence(ingest(L1, settings, llm=None), tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()
