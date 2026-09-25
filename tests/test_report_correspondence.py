# Purpose: pins the IR <-> SysML <-> Modelica correspondence table (FR-08 req 4, task B6) — every
# golden L1 element found in both generated files by its IR id comment, nothing MISSING; a
# connection deleted from the .mo or an id comment dropped from the .sysml shows as MISSING in
# that layer (acceptance 3); by-design absences are N/A with a reason, and a missing model file
# makes its column NOT RUN (R-REP-2, R-REP-3).
import shutil

import pytest

from specalive.core.catalogue import load_catalogue
from specalive.report import artefacts, correspondence
from tests._report_support import build_run, golden_ir, read


@pytest.fixture(scope="module")
def golden_run(tmp_path_factory):
    return build_run(tmp_path_factory.mktemp("corr") / "run")


def _rows(run_dir):
    table = correspondence.correspond(artefacts.load_run(run_dir), load_catalogue())
    return table, {r.ir_id: r for r in table.rows}


def _copy(golden_run, tmp_path):
    target = tmp_path / "run"
    shutil.copytree(golden_run, target)
    return target


def test_golden_l1_has_no_missing_rows(golden_run):
    table, rows = _rows(golden_run)
    missing = [r for r in table.rows if r.status.startswith(correspondence.MISSING)]
    assert missing == []
    ir = golden_ir()
    expected = ({p["id"] for p in ir["parts"]} | {c["id"] for c in ir["connections"]}
                | {s["id"] for sm in ir["state_machines"] for s in sm["states"]}
                | {t["id"] for sm in ir["state_machines"] for t in sm["transitions"]}
                | {r["id"] for r in ir["requirements"]} | {p["id"] for p in ir["parameters"]})
    assert expected <= set(rows)


def test_rows_name_the_element_in_each_layer(golden_run):
    _, rows = _rows(golden_run)
    assert rows["tk_101"].sysml == "two_tank_sequence::system::tk_101"
    assert rows["tk_101"].modelica == "System.tk_101"
    assert rows["tk_101"].status == correspondence.OK
    assert rows["if_hyd_01"].modelica == "connect(src_101.outlet, xv_101.inlet)"
    assert rows["if_hyd_01"].sysml == "two_tank_sequence::system::if_hyd_01"
    assert rows["idle"].sysml == "two_tank_sequence::plc_101_sequence::idle"
    assert rows["idle"].modelica == "Controller_plc_101_sequence.State.idle"
    assert rows["tr_idle_start"].sysml.endswith("::plc_101_sequence::tr_idle_start")
    assert "Controller_plc_101_sequence" in rows["tr_idle_start"].modelica
    assert rows["plc_101_sequence"].modelica == "Controller_plc_101_sequence"
    assert rows["tk_101_area"].modelica == "System.tk_101_area"
    assert rows["tk_101_area"].sysml == "two_tank_sequence::system::tk_101::area"


def test_ports_resolve_through_their_part(golden_run):
    _, rows = _rows(golden_run)
    assert rows["tk_101_inlet"].sysml == "two_tank_sequence::system::tk_101::inlet"
    assert rows["tk_101_inlet"].modelica == "System.tk_101.inlet"
    assert rows["plc_101_level1"].sysml == "two_tank_sequence::system::plc_101::plc_101_level1"
    assert rows["plc_101_level1"].modelica == "System.plc_101.level1"
    assert rows["tk_101_inlet"].status == correspondence.OK


def test_by_design_absences_are_not_applicable_with_a_reason(golden_run):
    _, rows = _rows(golden_run)
    req = rows["urs_ctl_001"]
    assert req.sysml.endswith("::urs_ctl_001")
    assert req.modelica.startswith(correspondence.NA) and "requirement" in req.modelica
    superseded = rows["tk_101_high_level_urs_001"]
    assert superseded.sysml.startswith(correspondence.NA)
    assert superseded.modelica.startswith(correspondence.NA)
    assert "superseded" in superseded.modelica
    verification_only = rows["pb_start_press_times"]
    assert verification_only.sysml.startswith(correspondence.NA)
    assert verification_only.modelica == "System.pb_start_press_times"
    assert all(not r.status.startswith(correspondence.MISSING) for r in rows.values())


def test_asserted_acceptance_criterion_is_found_in_the_controller(golden_run):
    _, rows = _rows(golden_run)
    assert "assert" in rows["ac_08"].modelica
    assert rows["ac_02"].modelica.startswith(correspondence.NA)


def test_a_deleted_connect_is_missing_in_the_modelica_column(golden_run, tmp_path):
    run = _copy(golden_run, tmp_path)
    mo = run / "model.mo"
    lines = [line for line in read(mo).splitlines() if "[IR if_hyd_03]" not in line]
    mo.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, rows = _rows(run)
    row = rows["if_hyd_03"]
    assert row.modelica == correspondence.MISSING
    assert row.status == f"{correspondence.MISSING} (Modelica)"
    assert row.sysml.endswith("::if_hyd_03")
    assert rows["if_hyd_02"].status == correspondence.OK


def test_a_dropped_sysml_id_comment_is_missing_in_the_sysml_column(golden_run, tmp_path):
    run = _copy(golden_run, tmp_path)
    path = run / "model.sysml"
    path.write_text(read(path).replace("doc /* ir: if_ctl_01\n", "doc /* removed\n"),
                    encoding="utf-8")
    _, rows = _rows(run)
    assert rows["if_ctl_01"].status == f"{correspondence.MISSING} (SysML)"
    assert rows["if_ctl_01"].modelica.startswith("connect(")


def test_a_missing_model_file_makes_its_column_not_run(golden_run, tmp_path):
    run = _copy(golden_run, tmp_path)
    (run / "model.sysml").unlink()
    table, rows = _rows(run)
    assert table.sysml_reason and "model.sysml" in table.sysml_reason
    assert rows["tk_101"].sysml == artefacts.NOT_RUN
    assert rows["tk_101"].status == f"{artefacts.NOT_RUN} (SysML)"
    text = correspondence.render_correspondence(artefacts.load_run(run), load_catalogue())
    assert f"SysML: {artefacts.NOT_RUN} — " in text


def test_markdown_lists_rules_and_every_row_deterministically(golden_run, tmp_path):
    run = artefacts.load_run(golden_run)
    first = correspondence.write_correspondence(run, load_catalogue(), tmp_path)
    text = read(first)
    assert first.name == "correspondence.md"
    assert "| IR id | Type | SysML element | Modelica element | Status |" in text
    assert "N/A" in text and "MISSING" in text  # the rules explain both
    assert "`tk_101`" in text
    assert "0 MISSING" in text
    again = correspondence.write_correspondence(artefacts.load_run(golden_run),
                                                load_catalogue(), tmp_path)
    assert read(again) == text


def test_sysml_scanner_qualifies_nested_names_and_skips_inline_blocks():
    text = """package p {
    part def T {
        port inlet : ~F;
    }
    state def m {
        doc /* ir: m
         * braces { in comments } are ignored
         */
        state a {
            doc /* ir: a */
        }
        transition t1 first a do action : start_timer { in timer = x; } then a {
            doc /* ir: t1 */
        }
    }
    part system {
        part tk : T {
            doc /* ir: tk */
            attribute :>> area = 1.0 [m^2] {
                doc /* ir: tk_area */
            }
        }
    }
}
"""
    scan = correspondence.scan_sysml(text)
    assert scan.elements == {"m": "p::m", "a": "p::m::a", "t1": "p::m::t1", "tk": "p::system::tk",
                             "tk_area": "p::system::tk::area"}
    assert scan.usages["tk"] == ("p::system::tk", "T")
    assert scan.def_ports["T"] == {"inlet"}


def test_the_table_comes_from_the_files_not_the_generator(golden_run, tmp_path):
    run = _copy(golden_run, tmp_path)
    (run / "model.mo").write_text("package x\nend x;\n", encoding="utf-8")
    table, rows = _rows(run)
    assert rows["tk_101"].status == f"{correspondence.MISSING} (Modelica)"
    assert table.counts()[correspondence.MISSING] > 0
