# Purpose: pins the ingest stage end to end on scratch bundles — every file becomes a Source with
# a status (R-ING-1), ids are deterministic from the path, chunks are ordered by source path then
# position (R-ING-5), a corrupt file is reported and the rest is still read (FR-03 acceptance 6),
# evidence.json is byte-identical across runs, and the evidence models reject dangling records.
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from specalive.config import load_settings
from specalive.ingest.evidence import EvidenceBundle, EvidenceChunk, Source
from specalive.ingest.ingest import InputNotFound, ingest, write_evidence

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


@pytest.fixture
def settings(tmp_path):
    return load_settings({"SPECALIVE_CACHE_DIR": str(tmp_path / "cache")})


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "b_notes").mkdir(parents=True)
    (root / "a_specs").mkdir()
    (root / "b_notes" / "shift.txt").write_text("FIELD NOTES\n\nPump ran fine.\n",
                                                encoding="utf-8")
    shutil.copy(FIXTURES / "two_pages.pdf", root / "a_specs" / "spec.pdf")
    shutil.copy(FIXTURES / "corrupt.pdf", root / "a_specs" / "broken.pdf")
    (root / "a_specs" / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    return root


def test_every_file_is_a_source_with_status(bundle, settings):
    b = ingest(bundle, settings, llm=None)
    assert [s.path for s in b.sources] == ["a_specs/broken.pdf", "a_specs/diagram.png",
                                          "a_specs/spec.pdf", "b_notes/shift.txt"]
    status = {s.path: s.status for s in b.sources}
    assert status == {"a_specs/broken.pdf": "unread", "a_specs/diagram.png": "unread",
                      "a_specs/spec.pdf": "read", "b_notes/shift.txt": "read"}
    assert all(s.reason for s in b.sources if s.status != "read")


def test_corrupt_file_does_not_stop_the_rest(bundle, settings):
    b = ingest(bundle, settings, llm=None)
    readable = {s.id for s in b.sources if s.status == "read"}
    assert readable == {c.source_id for c in b.chunks}


def test_source_ids_are_deterministic_from_the_path(bundle, settings):
    b = ingest(bundle, settings, llm=None)
    assert [s.id for s in b.sources] == ["src_a_specs_broken_pdf", "src_a_specs_diagram_png",
                                        "src_a_specs_spec_pdf", "src_b_notes_shift_txt"]


def test_chunks_are_ordered_by_source_path_then_position(bundle, settings):
    b = ingest(bundle, settings, llm=None)
    order = [s.id for s in b.sources]
    positions = [order.index(c.source_id) for c in b.chunks]
    assert positions == sorted(positions)
    pdf = [c for c in b.chunks if c.source_id == "src_a_specs_spec_pdf"]
    assert pdf[0].locator.startswith("page 1") and pdf[-1].locator.startswith("page 2")


def test_every_chunk_has_a_role(bundle, settings):
    b = ingest(bundle, settings, llm=None)
    assert all(c.role for c in b.chunks)
    assert all(s.role for s in b.sources)


def test_single_file_input(bundle, settings):
    b = ingest(bundle / "b_notes" / "shift.txt", settings, llm=None)
    assert [s.path for s in b.sources] == ["shift.txt"]
    assert b.root == str((bundle / "b_notes").resolve())


def test_missing_input_raises_input_not_found(tmp_path, settings):
    with pytest.raises(InputNotFound):
        ingest(tmp_path / "nope", settings, llm=None)


def test_evidence_json_is_byte_identical_across_runs(bundle, settings, tmp_path):
    first = write_evidence(ingest(bundle, settings, llm=None), tmp_path / "run1")
    second = write_evidence(ingest(bundle, settings, llm=None), tmp_path / "run2")
    assert first.name == "evidence.json"
    assert first.read_bytes() == second.read_bytes()


def test_evidence_json_round_trips(bundle, settings, tmp_path):
    b = ingest(bundle, settings, llm=None)
    path = write_evidence(b, tmp_path / "run")
    assert EvidenceBundle.model_validate_json(path.read_text(encoding="utf-8")) == b


def test_id_collision_between_paths_is_resolved_deterministically(tmp_path, settings):
    root = tmp_path / "b"
    root.mkdir()
    (root / "a-b.txt").write_text("one\n", encoding="utf-8")
    (root / "a_b.txt").write_text("two\n", encoding="utf-8")
    b = ingest(root, settings, llm=None)
    ids = [s.id for s in b.sources]
    assert len(set(ids)) == 2 and ids == [s.id for s in ingest(root, settings, llm=None).sources]


# --- evidence models ----------------------------------------------------------------------

def test_unread_source_needs_a_reason():
    with pytest.raises(ValidationError):
        Source(id="src_a", path="a.pdf", format="pdf", status="unread", reason=None)


def test_bundle_rejects_chunk_of_unknown_source():
    s = Source(id="src_a", path="a.txt", format="text", status="read")
    c = EvidenceChunk(source_id="src_zzz", locator="lines 1-1", text="x", kind="prose")
    with pytest.raises(ValidationError, match="src_zzz"):
        EvidenceBundle(root="/r", sources=[s], chunks=[c])


def test_bundle_rejects_duplicate_source_ids():
    s = Source(id="src_a", path="a.txt", format="text", status="read")
    with pytest.raises(ValidationError, match="src_a"):
        EvidenceBundle(root="/r", sources=[s, s], chunks=[])


def test_chunk_needs_text_and_locator():
    with pytest.raises(ValidationError):
        EvidenceChunk(source_id="src_a", locator="", text="x", kind="prose")
    with pytest.raises(ValidationError):
        EvidenceChunk(source_id="src_a", locator="l", text="", kind="prose")
