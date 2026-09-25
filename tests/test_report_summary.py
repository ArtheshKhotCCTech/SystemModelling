# Purpose: pins summary.md (FR-08 req 1, acceptance 2 and 4) — the sections in the required
# order, one status line per gate with numbers read from the artefacts (R-REP-4), open questions
# with their defaults, one line per conflict, the compile command, at most 60 lines even with many
# questions and conflicts, and NOT RUN with a reason when an artefact is missing (R-REP-3).
import json

import pytest

from specalive.report import artefacts, summary
from tests._report_support import COMPILE_COMMAND, build_run, golden_ir, read


@pytest.fixture(scope="module")
def verified_run(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    try:
        yield build_run(tmp_path_factory.mktemp("summary") / "run", mp)
    finally:
        mp.undo()


def _text(run_dir):
    return summary.render_summary(artefacts.load_run(run_dir))


def test_sections_come_in_the_required_order(verified_run):
    text = _text(verified_run)
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## Status", "## Counts", "## Open questions", "## Assumptions",
                        "## Conflicts resolved by precedence", "## Reproduce"]
    assert golden_ir()["description"][:60] in text.split("## Status")[0]


def test_one_minute_read_names_the_compile_command(verified_run):
    text = _text(verified_run)
    assert len(text.splitlines()) <= summary.MAX_LINES
    assert COMPILE_COMMAND in text


def test_gate_lines_take_their_numbers_from_the_artefacts(verified_run):
    text = _text(verified_run)
    verification = json.loads(read(verified_run / "verification.json"))
    counts = {s: sum(1 for c in verification["criteria"] if c["status"] == s)
              for s in ("PASS", "FAIL", "NOT CHECKED")}
    assert "- IR valid: PASS" in text
    assert "- SysML valid: ok" in text
    assert "- Modelica compiles: ok" in text
    assert "- Simulates: ok" in text
    assert (f"- Acceptance criteria: {counts['PASS']} PASS / {counts['FAIL']} FAIL / "
            f"{counts['NOT CHECKED']} NOT CHECKED") in text
    assert "- Reference trace: " in text
    assert "- Coverage: NOT RUN — no reference IR given (--golden)" in text


def test_counts_line_matches_the_ir(verified_run):
    ir = golden_ir()
    text = _text(verified_run)
    states = sum(len(sm["states"]) for sm in ir["state_machines"])
    assert (f"{len(ir['parts'])} parts, {len(ir['connections'])} connections, {states} states, "
            f"{len(ir['requirements'])} requirements") in text
    assert (f"{len(ir['assumptions'])} assumptions, 0 open questions, "
            f"{len(ir['conflicts'])} conflicts") in text


def test_a_conflict_is_one_line_naming_winner_and_losers(verified_run):
    text = _text(verified_run)
    assert ("- TK-101 high_level: 0.80 m (CR-004 Rev 1) over 0.78 m "
            "(URS-001 Rev A, SIM-LEGACY Rev 1.2)") in text


def test_many_questions_and_conflicts_still_fit_on_one_screen(tmp_path):
    ir = golden_ir()
    ir["questions"] = [{"id": f"q_{i:02d}", "text": f"Question {i}?", "options": ["a", "b"],
                        "default_if_unanswered": "a", "affects": [], "answer": None}
                       for i in range(30)]
    base = ir["conflicts"][0]
    ir["conflicts"] += [{**base, "id": f"cf_extra_{i:02d}"} for i in range(20)]
    ir["assumptions"] += [{**ir["assumptions"][0], "id": f"as_extra_{i:02d}"} for i in range(20)]
    run = build_run(tmp_path / "run", ir=ir)
    text = _text(run)
    assert len(text.splitlines()) <= summary.MAX_LINES
    assert "- `q_00`: Question 0? — default: a" in text
    assert "- … and 22 more open questions in assumptions.md" in text
    open_section = text.split("## Open questions")[1].split("## ")[0]
    assert open_section.count("- `q_") == summary.MAX_QUESTIONS


def test_questions_come_before_conflicts_and_unanswered_only(tmp_path):
    ir = golden_ir()
    ir["questions"] = [{"id": "q_a", "text": "Open?", "options": [], "answer": None,
                        "default_if_unanswered": None, "affects": []},
                       {"id": "q_b", "text": "Closed?", "options": [], "answer": "yes",
                        "default_if_unanswered": None, "affects": []}]
    text = _text(build_run(tmp_path / "run", ir=ir))
    assert "- `q_a`: Open? — default: none stated" in text
    assert "q_b" not in text


def test_without_verification_the_verification_lines_are_not_run(verified_run, tmp_path):
    import shutil
    run = tmp_path / "run"
    shutil.copytree(verified_run, run)
    (run / "verification.json").unlink()
    text = _text(run)
    assert "- Simulates: NOT RUN — verification.json not found" in text
    assert "- Acceptance criteria: NOT RUN — verification.json not found" in text
    assert "- Modelica compiles: ok" in text


def test_an_invalid_ir_fails_its_gate_with_the_error(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "ir.json").write_text('{"name": "x"}', encoding="utf-8")
    text = _text(run)
    assert "- IR valid: FAIL — " in text
    assert "NOT RUN" in text.split("## Counts")[1]


def test_an_empty_run_folder_still_gives_a_summary(tmp_path):
    (tmp_path / "run").mkdir()
    text = _text(tmp_path / "run")
    assert "- IR valid: NOT RUN — ir.json not found" in text
    assert "- Modelica compiles: NOT RUN — repair_log.json not found" in text


def test_written_to_summary_md_deterministically(verified_run, tmp_path):
    a = read(summary.write_summary(artefacts.load_run(verified_run), tmp_path / "a"))
    b = read(summary.write_summary(artefacts.load_run(verified_run), tmp_path / "b"))
    assert a == b
