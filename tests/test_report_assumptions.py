# Purpose: pins assumptions.md (FR-08 req 3) — assumptions with basis and affected elements;
# every conflict candidate with its source and rank, the winner and the rationale; questions with
# options, default and answer; rejected, missing and unresolved items from extract_report.json;
# unread sources from evidence.json; verification and generator defaults. Absent artefacts make
# their section NOT RUN with the reason (R-REP-3).
import json

import pytest

from specalive.report import artefacts, assumptions
from tests._report_support import build_run, golden_ir, read

QUESTION = {"id": "q_pulse", "text": "How long is a pushbutton pulse?",
            "options": ["1 s", "one scan"], "default_if_unanswered": "1 s",
            "affects": ["pb_start"], "answer": None}


@pytest.fixture(scope="module")
def golden_text(tmp_path_factory):
    run = build_run(tmp_path_factory.mktemp("asm") / "run")
    return assumptions.render_assumptions(artefacts.load_run(run))


def _section(text, heading):
    start = text.index(f"## {heading}")
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else None]


def test_assumptions_list_text_basis_and_affected_elements(golden_text):
    section = _section(golden_text, "Assumptions")
    for a in golden_ir()["assumptions"]:
        assert f"`{a['id']}`" in section and a["basis"] in section
    assert "`xv_101_nominal_flow`" in section


def test_every_conflict_candidate_with_rank_winner_and_rationale(golden_text):
    section = _section(golden_text, "Conflicts")
    conflict = next(c for c in golden_ir()["conflicts"] if c["id"] == "cf_tk_101_high_level")
    assert "`cf_tk_101_high_level`" in section
    for cand in conflict["candidates"]:
        assert cand["value"] in section and cand["source_id"] in section
    assert "URS-001 Rev A" in section
    assert "Winner: 0.80 m" in section
    assert conflict["rationale"][:60] in section


def test_questions_show_options_default_and_answer(tmp_path):
    ir = golden_ir()
    ir["questions"] = [QUESTION, {**QUESTION, "id": "q_answered", "answer": "one scan"}]
    run = build_run(tmp_path / "run", ir=ir)
    section = _section(assumptions.render_assumptions(artefacts.load_run(run)), "Questions")
    assert "`q_pulse`" in section and "1 s / one scan" in section
    assert "default if unanswered: 1 s" in section and "unanswered" in section
    assert "answer: one scan" in section


def test_extraction_sections_are_not_run_without_extract_report(golden_text):
    for heading in ("Rejected untraced elements", "Missing information", "Unresolved fragments"):
        section = _section(golden_text, heading)
        assert f"{artefacts.NOT_RUN} — " in section and "extract_report.json" in section
    assert "evidence.json" in _section(golden_text, "Sources not fully read")


def test_extraction_and_ingestion_records_are_listed(tmp_path):
    run = build_run(tmp_path / "run")
    report = {"discarded_fragments": [{"chunk_id": "c1", "kind": "parameter", "quote": "q",
                                       "reason": "quote not found in the chunk"}],
              "rejected_untraced": [{"kind": "part", "id": "ghost", "reason": "no trace"}],
              "unresolved": ["parameter x: owner 'Z' is not a part"],
              "missing_information": ["tank tk_9: no area in any source"]}
    (run / "extract_report.json").write_text(json.dumps(report), encoding="utf-8")
    evidence = {"root": str(tmp_path), "chunks": [], "sources": [
        {"id": "s1", "path": "a.pdf", "format": "pdf", "status": "read"},
        {"id": "s2", "path": "b.png", "format": "image", "status": "unread",
         "reason": "vision disabled"}]}
    (run / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    text = assumptions.render_assumptions(artefacts.load_run(run))
    assert "`ghost`" in _section(text, "Rejected untraced elements")
    assert "no area in any source" in _section(text, "Missing information")
    assert "owner 'Z'" in _section(text, "Unresolved fragments")
    assert "quote not found" in _section(text, "Discarded fragments")
    sources = _section(text, "Sources not fully read")
    assert "b.png" in sources and "vision disabled" in sources and "a.pdf" not in sources


def test_verification_and_generator_defaults_are_listed(tmp_path, monkeypatch):
    run = build_run(tmp_path / "run", monkeypatch)
    section = _section(assumptions.render_assumptions(artefacts.load_run(run)),
                       "Defaults declared by the pipeline")
    assert "continuous_fraction" in section
    assert "generator default" in section and "Interval" in section


def test_without_an_ir_every_ir_section_is_not_run(tmp_path):
    (tmp_path / "run").mkdir()
    text = assumptions.render_assumptions(artefacts.load_run(tmp_path / "run"))
    for heading in ("Assumptions", "Conflicts", "Questions"):
        assert f"{artefacts.NOT_RUN} — " in _section(text, heading)


def test_written_to_assumptions_md(tmp_path):
    run = build_run(tmp_path / "run")
    target = assumptions.write_assumptions(artefacts.load_run(run), tmp_path / "out")
    assert target.name == "assumptions.md" and read(target).startswith("# ")
