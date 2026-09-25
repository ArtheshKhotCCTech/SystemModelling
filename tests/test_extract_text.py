# Purpose: pins the plain-text input path (FR-04 requirement 17, R-EXT-8): a pasted paragraph or a
# text file becomes a one-source evidence bundle with role requirement_spec, chunked like any text
# file, and runs through the very same run_extract as a bundle.
from _extract_support import FakeLLM, empty_reply, part
from specalive.extract import extract as extract_module
from specalive.extract.text_input import text_bundle

SPEC = ("A single open tank TK-5 is filled through on/off valve XV-5 from a supply.\n\n"
        "The tank cross-section is 0.5 m2.")


def test_text_becomes_a_one_source_requirement_spec_bundle():
    b = text_bundle(SPEC)
    assert len(b.sources) == 1
    s = b.sources[0]
    assert (s.id, s.role, s.status, s.format) == ("src_text", "requirement_spec", "read", "text")
    assert [c.text for c in b.chunks] == SPEC.split("\n\n")
    assert [c.locator for c in b.chunks] == ["line 1", "line 3"]
    assert all(c.source_id == "src_text" for c in b.chunks)


def test_text_file_name_names_the_source():
    b = text_bundle(SPEC, name="spec.txt")
    assert b.sources[0].id == "src_spec_txt" and b.sources[0].path == "spec.txt"


def test_text_runs_through_the_same_extract_as_a_bundle(monkeypatch):
    seen = []
    real = extract_module.run_extract

    def spy(bundle, llm, catalogue=None):
        seen.append(bundle)
        return real(bundle, llm, catalogue)

    monkeypatch.setattr(extract_module, "run_extract", spy)
    llm = FakeLLM({"FragmentReply": [empty_reply(parts=[
        part("src_text#0", "open tank TK-5", "TK-5", "tank")])]})
    result = extract_module.extract_text(SPEC, llm)
    assert len(seen) == 1 and seen[0].sources[0].role == "requirement_spec"
    assert [p.id for p in result.model.parts] == ["tk_5"]
