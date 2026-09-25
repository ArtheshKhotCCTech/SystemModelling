# Purpose: pins source classification (FR-03 requirements 9-10) — a source-index table,
# recognised by its columns and never by its sheet name, wins and is traced; otherwise header
# fields and title keywords by rule, then the format default, and the LLM only when every rule
# finds nothing; register sheets give their rows a role of their own.
import pytest
from pydantic import BaseModel

from specalive.ingest.classify import (
    ClassificationReply,
    classify,
    parse_header,
    parse_index_revision,
    role_from_keywords,
)
from specalive.ingest.evidence import EvidenceChunk, Source
from specalive.llm.client import LLMError


def src(id_, path, fmt, status="read"):
    return Source(id=id_, path=path, format=fmt, status=status,
                  reason=None if status == "read" else "test")


def chunk(source_id, text, locator="lines 1-1", kind="prose", fields=None):
    return EvidenceChunk(source_id=source_id, locator=locator, text=text, kind=kind,
                         fields=fields or {})


INDEX_HEADERS = ("Source ID", "Filename / Artifact", "Type", "Revision / Date", "Reliability")


def index_row(row, filename, type_, rev, rel, sheet="Anything_At_All"):
    values = (f"S-{row}", filename, type_, rev, rel)
    fields = dict(zip(INDEX_HEADERS, values))
    return chunk("src_reg", " | ".join(f"{k}: {v}" for k, v in fields.items()),
                 locator=f"sheet {sheet}, row {row}", kind="table_row", fields=fields)


# --- rules --------------------------------------------------------------------------------

@pytest.mark.parametrize("text, fmt, role", [
    ("PDF test procedure", "pdf", "verification_procedure"),
    ("Operating/test procedure", "docx", "verification_procedure"),
    ("Meeting notes", "markdown", "review_decision"),
    ("Design Review Minutes", "markdown", "review_decision"),
    ("PDF datasheet", "pdf", "datasheet"),
    ("PDF specification", "pdf", "requirement_spec"),
    ("Word design note", "docx", "design_note"),
    ("Technical note", "pdf", "design_note"),
    ("Email thread", "eml", "correspondence"),
    ("Engineer notes", "text", "informal_note"),
    ("Excel workbook", "xlsx", "register"),
    ("Simulation model", "modelica", "legacy_model"),
    ("Existing system model", "plantuml", "legacy_architecture"),
    ("CSV test data", "csv", "reference_data"),
    ("CAD/BIM-derived JSON", "json", "reference_data"),
    ("Engineering change record", "pdf", "change_record"),
])
def test_keyword_rules(text, fmt, role):
    assert role_from_keywords(text, fmt)[0] == role


def test_keyword_rules_find_nothing_in_a_generic_type():
    assert role_from_keywords("Word document", "docx") is None


def test_model_keyword_needs_a_model_format():
    assert role_from_keywords("Simulation model", "pdf") is None


def test_parse_header_label_on_same_line_and_next_line():
    h = parse_header("Some Title\nDocument\nABC-001\nRevision\nA\nDate\n15 Jan 2026\n"
                     "Status\nReleased - baseline\n1. Purpose")
    assert (h.document, h.revision, h.date, h.status) == (
        "ABC-001", "A", "2026-01-15", "Released - baseline")
    h = parse_header("**Date:** 2026-02-19  \n**Status:** Final / approved decisions")
    assert (h.date, h.status) == ("2026-02-19", "Final / approved decisions")
    h = parse_header("Document XY-IAQ-001 - Revision C - 2026-03-03")
    assert (h.document, h.revision, h.date) == ("XY-IAQ-001", "C", "2026-03-03")
    h = parse_header("Core Data Sheet - Rev B")
    assert h.revision == "B"


def test_parse_header_finds_nothing_in_plain_prose():
    h = parse_header("the pump starts when asked to and stops later")
    assert (h.document, h.revision, h.date, h.status) == (None, None, None, None)


@pytest.mark.parametrize("cell, rev, date", [
    ("Rev A / 2026-01-15", "A", "2026-01-15"),
    ("Rev C", "C", None),
    ("2026-02-19", None, "2026-02-19"),
    ("2026-02-16..03-12", None, "2026-02-16"),
    ("Archived 0.9 / 2026-03-05", "Archived 0.9", "2026-03-05"),
    ("Compiled", "Compiled", None),
])
def test_parse_index_revision(cell, rev, date):
    assert parse_index_revision(cell) == (rev, date)


# --- classify -----------------------------------------------------------------------------

def test_source_index_wins_and_is_traced():
    sources = [src("src_reg", "02/reg.xlsx", "xlsx"), src("src_tp", "08/tp9.pdf", "pdf")]
    chunks = [index_row(4, "tp9.pdf", "PDF test procedure", "Rev C / 2026-04-03", "High"),
              chunk("src_tp", "Spec for something\nRevision\nZ")]
    out, _ = classify(sources, chunks, llm=None)
    tp = next(s for s in out if s.id == "src_tp")
    assert tp.role == "verification_procedure"
    assert (tp.revision, tp.date, tp.reliability) == ("C", "2026-04-03", "high")
    assert tp.classified_by == "source_index"
    assert tp.classification_trace.source_id == "src_reg"
    assert tp.classification_trace.locator == "sheet Anything_At_All, row 4"


def test_index_is_recognised_by_columns_not_sheet_name():
    fields = {"Name": "tp9.pdf", "Kind": "PDF test procedure"}
    not_index = chunk("src_reg", "x", locator="sheet Source_Index, row 4", kind="table_row",
                      fields=fields)
    sources = [src("src_reg", "reg.xlsx", "xlsx"), src("src_tp", "tp9.pdf", "pdf")]
    out, _ = classify(sources, [not_index, chunk("src_tp", "nothing to see")], llm=None)
    assert next(s for s in out if s.id == "src_tp").classified_by != "source_index"


def test_generic_index_type_falls_back_to_document_title_but_keeps_index_fields():
    sources = [src("src_reg", "reg.xlsx", "xlsx"), src("src_dn", "note.docx", "docx")]
    chunks = [index_row(7, "note.docx", "Word document", "Rev B / 2026-02-20", "High"),
              chunk("src_dn", "CONTROL LOGIC DESIGN NOTE"), chunk("src_dn", "Document: CDS-2")]
    out, _ = classify(sources, chunks, llm=None)
    dn = next(s for s in out if s.id == "src_dn")
    assert dn.role == "design_note" and dn.classified_by == "content"
    assert (dn.revision, dn.reliability, dn.document) == ("B", "high", "CDS-2")
    assert dn.classification_trace.locator == "sheet Anything_At_All, row 7"


def test_without_index_header_and_title_rules_classify():
    sources = [src("src_ds", "ds.pdf", "pdf")]
    chunks = [chunk("src_ds", "Supplier Datasheet - VX-1 Valve\nRevision\nB\nDate\n05 Feb 2026")]
    out, _ = classify(sources, chunks, llm=None)
    ds = out[0]
    assert (ds.role, ds.revision, ds.date, ds.classified_by) == (
        "datasheet", "B", "2026-02-05", "content")
    assert ds.reliability == "high"  # defaulted from the role, and said so
    assert "reliability" in ds.classification_basis


def test_format_default_when_no_keyword_matches():
    out, _ = classify([src("src_mo", "plant.mo", "modelica")],
                      [chunk("src_mo", "model Plant\nend Plant;", kind="code")], llm=None)
    assert (out[0].role, out[0].classified_by) == ("legacy_model", "format")


def test_unread_source_is_still_classified_from_the_index():
    sources = [src("src_reg", "reg.xlsx", "xlsx"), src("src_img", "d.png", "image", "unread")]
    chunks = [index_row(6, "d.png", "Engineering diagram", "Provided reference", "Medium")]
    out, _ = classify(sources, chunks, llm=None)
    img = next(s for s in out if s.id == "src_img")
    assert img.reliability == "medium" and img.classification_trace is not None


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.inputs = reply, error, []

    def complete(self, *, prompt, input_text, schema):
        self.inputs.append(input_text)
        if self.error:
            raise self.error
        return schema.model_validate(self.reply)


def test_llm_is_asked_only_when_rules_find_nothing():
    llm = FakeLLM({"role": "design_note", "revision": "2", "date": None,
                   "reason": "describes design intent"})
    sources = [src("src_ds", "ds.pdf", "pdf"), src("src_x", "x.txt", "text")]
    chunks = [chunk("src_ds", "Supplier Datasheet"), chunk("src_x", "pump starts, pump stops")]
    out, _ = classify(sources, chunks, llm=llm)
    assert len(llm.inputs) == 1 and "pump starts" in llm.inputs[0]
    x = next(s for s in out if s.id == "src_x")
    assert (x.role, x.revision, x.classified_by) == ("design_note", "2", "llm")
    assert "describes design intent" in x.classification_basis


def test_llm_failure_or_absence_gives_other_with_reason():
    sources = [src("src_x", "x.txt", "text")]
    chunks = [chunk("src_x", "pump starts, pump stops")]
    for llm in (None, FakeLLM(error=LLMError("no key"))):
        out, _ = classify(sources, chunks, llm=llm)
        assert (out[0].role, out[0].classified_by) == ("other", "none")
        assert out[0].classification_basis


def test_classification_reply_schema_is_strict_compatible():
    from specalive.llm.client import strict_json_schema
    schema = strict_json_schema(ClassificationReply)
    assert set(schema["required"]) == {"role", "revision", "date", "reason"}
    assert issubclass(ClassificationReply, BaseModel)


# --- chunk roles --------------------------------------------------------------------------

def test_register_sheets_give_chunks_their_own_role():
    sources = [src("src_reg", "reg.xlsx", "xlsx")]
    change = chunk("src_reg", "…", "sheet A, row 4", "table_row",
                   {"Record": "CR-9", "Change Summary": "x", "Approved By": "Board"})
    req = chunk("src_reg", "…", "sheet B, row 4", "table_row",
                {"Req ID": "R-1", "Requirement Text": "shall"})
    ver = chunk("src_reg", "…", "sheet C, row 4", "table_row",
                {"Test ID": "T-1", "Requirement(s)": "R-1", "Acceptance Criterion": "ok"})
    other = chunk("src_reg", "…", "sheet D, row 4", "table_row", {"Tag": "P-1", "Type": "pump"})
    title = chunk("src_reg", "Register", "sheet A, row 1")
    _, out = classify(sources, [change, req, ver, other, title], llm=None)
    assert [c.role for c in out] == ["change_record", "requirement_spec",
                                    "verification_procedure", "register", "register"]


def test_every_chunk_gets_its_source_role():
    sources = [src("src_mail", "t.eml", "eml")]
    _, out = classify(sources, [chunk("src_mail", "From: a\n\nhi", kind="email_message")],
                      llm=None)
    assert out[0].role == "correspondence"
