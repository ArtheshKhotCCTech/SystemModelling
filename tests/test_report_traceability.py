# Purpose: pins traceability.md (FR-08 req 2) — one row per IR element with its primary source,
# locator, quote and confidence, grouped by element type and sorted by id; elements resting on
# an assumption flagged, inherited traces named, table cells escaped; NOT RUN without an IR.
import pytest

from specalive.report import artefacts, traceability
from tests._report_support import build_run, golden_ir, read


@pytest.fixture(scope="module")
def golden_run(tmp_path_factory):
    return build_run(tmp_path_factory.mktemp("trace") / "run")


def _rows(run_dir):
    return traceability.trace_rows(artefacts.load_run(run_dir).ir.data)


def test_one_row_per_element_grouped_by_type_and_sorted(golden_run):
    rows = _rows(golden_run)
    ir = golden_ir()
    ids = [r.id for r in rows]
    assert len(ids) == len(set(ids))
    expected = ({p["id"] for p in ir["parts"]}
                | {port["id"] for p in ir["parts"] for port in p["ports"]}
                | {c["id"] for c in ir["connections"]} | {p["id"] for p in ir["parameters"]}
                | {sm["id"] for sm in ir["state_machines"]}
                | {s["id"] for sm in ir["state_machines"] for s in sm["states"]}
                | {t["id"] for sm in ir["state_machines"] for t in sm["transitions"]}
                | {r["id"] for r in ir["requirements"]}
                | {a["id"] for a in ir["acceptance_criteria"]}
                | {a["id"] for a in ir["assumptions"]})
    assert expected <= set(ids)
    order = [g for g, _ in traceability.GROUPS]
    groups = [r.group for r in rows]
    assert groups == sorted(groups, key=order.index)
    for group in set(groups):
        in_group = [r.id for r in rows if r.group == group]
        assert in_group == sorted(in_group)


def test_a_traced_row_carries_source_locator_quote_and_confidence(golden_run):
    row = {r.id: r for r in _rows(golden_run)}["tk_101"]
    part = next(p for p in golden_ir()["parts"] if p["id"] == "tk_101")
    first = part["trace"][0]
    assert row.source.startswith(first["source_id"])
    assert row.locator.startswith(first["locator"])
    assert row.quote == first["quote"]
    assert row.confidence == f"{part['confidence']:g}"
    assert row.name == "Tank 1"


def test_assumed_and_inherited_rows_are_flagged(golden_run):
    rows = {r.id: r for r in _rows(golden_run)}
    assert "as_constant_flow" in rows["xv_101"].assumed
    assert rows["tk_101_inlet"].source.startswith("inherits tk_101")
    assert rows["idle"].source.startswith("inherits plc_101_sequence")


def test_an_assumption_only_element_says_so():
    ir = golden_ir()
    param = next(p for p in ir["parameters"] if p["id"] == "tk_101_area")
    param["trace"] = []
    param["assumption_ids"] = ["as_constant_flow"]
    from specalive.core.ir import SystemModel
    row = {r.id: r for r in traceability.trace_rows(SystemModel.model_validate(ir))}["tk_101_area"]
    assert row.source == traceability.ASSUMPTION_ONLY
    assert "as_constant_flow" in row.assumed


def test_markdown_escapes_cells_and_has_group_headings(golden_run, tmp_path):
    ir = golden_ir()
    ir["parts"][0]["trace"][0]["quote"] = "a | b\nc"
    run = build_run(tmp_path / "run", ir=ir)
    text = read(traceability.write_traceability(artefacts.load_run(run), tmp_path / "out"))
    assert "a \\| b c" in text
    for heading, _ in traceability.GROUPS:
        if heading != "Regions":
            assert f"## {heading}" in text
    assert "| Id | Name | Primary source | Locator | Quote | Confidence | Assumed |" in text


def test_without_an_ir_the_report_says_not_run(tmp_path):
    (tmp_path / "run").mkdir()
    text = traceability.render_traceability(artefacts.load_run(tmp_path / "run"))
    assert f"{artefacts.NOT_RUN} — " in text and "ir.json" in text


def test_output_is_deterministic(golden_run, tmp_path):
    a = read(traceability.write_traceability(artefacts.load_run(golden_run), tmp_path / "a"))
    b = read(traceability.write_traceability(artefacts.load_run(golden_run), tmp_path / "b"))
    assert a == b
