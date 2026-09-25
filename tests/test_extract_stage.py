# Purpose: the extract stage end to end on a small scratch bundle with the LLM faked — a
# schema-valid IR with its conflict, assumptions and cited record; ir.json and extract_report.json
# written deterministically (acceptance 7: byte-identical on a repeat); and the CLI contract:
# -i / --text / --text-file, exit 2 for input problems and 3 for LLM infrastructure problems.
import json

import pytest

from _extract_support import FakeLLM, bundle, chunk, connection, empty_reply, param, part, source
from specalive import cli
from specalive.core.ir import SystemModel
from specalive.extract.extract import IR_FILE, REPORT_FILE, run_extract, write_ir
from specalive.ingest.ingest import write_evidence

ROW_TK = "Tag: TK-1 | Alias: tank1 | Type: Tank | Area (m2): 2"
ROW_XV = "Tag: XV-1 | Alias: valve1 | Type: On-off valve | Nominal Flow (m3/s): 0.01"
ROW_CR = "Record: CR-1 | Status: Approved | Summary: TK-1 high level 0.7 -> 0.8 m"
REQ = "REQ-1 The controller shall stop filling at a high level of 0.7 m."
FLOW = "SRC-1 supplies valve XV-1, which fills tank TK-1."


def scratch():
    return bundle(
        [source("src_reg", "register", fmt="xlsx", date="2026-04-01"),
         source("src_spec", "requirement_spec", fmt="pdf", document="SPEC-1",
                date="2026-01-01", title="Spec")],
        [chunk("src_reg", "sheet E, row 2", ROW_TK, kind="table_row"),
         chunk("src_reg", "sheet E, row 3", ROW_XV, kind="table_row"),
         chunk("src_reg", "sheet L, row 2", ROW_CR, kind="table_row", role="change_record"),
         chunk("src_spec", "p.1", REQ),
         chunk("src_spec", "p.2", FLOW)])


def reply_for(text):
    if "src_reg#0" in text:
        return empty_reply(
            system_name="Tank fill demo",
            parts=[part("src_reg#0", ROW_TK, "TK-1", "tank", aliases=["tank1"]),
                   part("src_reg#1", ROW_XV, "XV-1", "on_off_valve", aliases=["valve1"])],
            parameters=[param("src_reg#0", "Area (m2): 2", "TK-1", "area", "2", "m2"),
                        param("src_reg#1", "Nominal Flow (m3/s): 0.01", "XV-1", "nominal_flow",
                              "0.01", "m3/s"),
                        param("src_reg#2", "TK-1 high level 0.7 -> 0.8 m", "TK-1", "high_level",
                              "0.8", "m", cited="CR-1")],
            documents=[{"chunk_id": "src_reg#2", "quote": "Record: CR-1 | Status: Approved",
                        "tag": "CR-1", "title": "Change request CR-1", "role": "change_record",
                        "approved": True, "date": "2026-03-01", "revision": "1",
                        "file_name": None}])
    return empty_reply(
        parts=[part("src_spec#1", "SRC-1 supplies valve XV-1", "SRC-1", "fluid_source"),
               part("src_spec#1", "fills tank TK-1", "TK-1", "tank")],
        connections=[connection("src_spec#1", "SRC-1 supplies valve XV-1", "SRC-1", "XV-1"),
                     connection("src_spec#1", "XV-1, which fills tank TK-1", "XV-1", "TK-1")],
        parameters=[param("src_spec#0", "stop filling at a high level of 0.7 m", "TK-1",
                          "high_level", "0.7", "m")],
        requirements=[{"chunk_id": "src_spec#0", "quote": REQ, "tag": "REQ-1",
                       "text": "The controller shall stop filling at a high level of 0.7 m.",
                       "category": "functional", "status": "active", "superseded_by": None}])


def fake():
    return FakeLLM({"FragmentReply": reply_for})


def test_scratch_bundle_gives_a_schema_valid_traced_ir():
    result = run_extract(scratch(), fake())
    m = result.model
    SystemModel.model_validate(m.model_dump(by_alias=True))
    assert m.name == "tank_fill_demo"  # folded to an identifier the generators can use
    assert [p.id for p in m.parts] == ["src_1", "tk_1", "xv_1"]
    assert {(c.from_port, c.to_port) for c in m.connections} == {
        ("src_1_outlet", "xv_1_inlet"), ("xv_1_outlet", "tk_1_inlet")}
    eff = {p.id: p for p in m.parameters}
    assert eff["tk_1_high_level"].value == 0.8 and eff["tk_1_high_level"].authority == "cr_1"
    assert eff["tk_1_high_level_spec_1"].status == "superseded"
    assert [c.id for c in m.conflicts] == ["cf_tk_1_high_level"]
    assert any(s.id == "cr_1" and s.path is None for s in m.sources)
    assert eff["tk_1_initial_level"].assumption_ids  # catalogue default, declared
    assert [r.id for r in m.requirements] == ["req_1"]
    assert result.report.discarded_fragments == []
    assert any("CR-1" in item for item in result.report.missing_information)


def test_ir_json_is_sorted_and_byte_identical_on_a_repeat(tmp_path):
    a = write_ir(run_extract(scratch(), fake()), tmp_path / "a")
    b = write_ir(run_extract(scratch(), fake()), tmp_path / "b")
    assert a.name == IR_FILE
    assert a.read_bytes() == b.read_bytes()
    data = json.loads(a.read_text(encoding="utf-8"))
    for group in ("parts", "parameters", "sources", "conflicts"):
        ids = [x["id"] for x in data[group]]
        assert ids == sorted(ids)
    report = json.loads((tmp_path / "a" / REPORT_FILE).read_text(encoding="utf-8"))
    assert set(report) >= {"discarded_fragments", "rejected_untraced", "missing_information"}


# --- CLI -----------------------------------------------------------------------------------

@pytest.fixture
def no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: cli.Settings(cache_dir=tmp_path / "c"))


def test_cli_extract_reads_evidence_and_writes_ir(tmp_path, no_key, monkeypatch, capsys):
    out = tmp_path / "run"
    write_evidence(scratch(), out)
    monkeypatch.setattr(cli, "LLMClient", lambda settings: fake())
    assert cli.main(["extract", "-o", str(out)]) == 0
    assert (out / IR_FILE).is_file() and (out / REPORT_FILE).is_file()
    printed = capsys.readouterr().out
    assert "3 part(s)" in printed and "1 conflict(s)" in printed


def test_cli_extract_explicit_input(tmp_path, no_key, monkeypatch):
    ev = tmp_path / "ev"
    write_evidence(scratch(), ev)
    monkeypatch.setattr(cli, "LLMClient", lambda settings: fake())
    out = tmp_path / "o"
    assert cli.main(["extract", "-i", str(ev / "evidence.json"), "-o", str(out)]) == 0
    assert (out / IR_FILE).is_file()


def test_cli_extract_missing_or_bad_input_is_an_input_problem(tmp_path, no_key, capsys):
    assert cli.main(["extract", "-o", str(tmp_path / "none")]) == 2
    assert "input problem" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cli.main(["extract", "-i", str(bad), "-o", str(tmp_path / "o")]) == 2
    assert cli.main(["extract", "--text-file", str(tmp_path / "missing.txt")]) == 2
    assert cli.main(["extract", "--text", "   "]) == 2


def test_cli_extract_without_key_or_cache_is_an_infrastructure_problem(tmp_path, no_key, capsys):
    code = cli.main(["extract", "--text", "A tank TK-1 is filled by valve XV-1.", "-o",
                     str(tmp_path / "t")])
    assert code == 3
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_cli_extract_text_file_uses_the_text_path(tmp_path, no_key, monkeypatch):
    spec = tmp_path / "spec.txt"
    spec.write_text("A tank TK-1 is filled.\n", encoding="utf-8")
    llm = FakeLLM({"FragmentReply": [empty_reply(parts=[
        part("src_spec_txt#0", "A tank TK-1", "TK-1", "tank")])]})
    monkeypatch.setattr(cli, "LLMClient", lambda settings: llm)
    out = tmp_path / "o"
    assert cli.main(["extract", "--text-file", str(spec), "-o", str(out)]) == 0
    data = json.loads((out / IR_FILE).read_text(encoding="utf-8"))
    assert [p["id"] for p in data["parts"]] == ["tk_1"]
    roles = {s["id"]: s["role"] for s in data["sources"]}
    assert roles["src_spec_txt"] == "requirement_spec"
