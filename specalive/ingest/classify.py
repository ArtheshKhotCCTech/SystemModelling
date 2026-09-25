# Purpose: gives every source a role, revision, date and reliability, because phase 4's precedence
# ladder ranks document roles, not file names. Evidence is tried strongest first: a source-index
# table in the bundle (recognised by its columns, and cited as the trace), then the document's own
# title and header fields, then the file format's default, and the LLM only when every rule finds
# nothing. Register rows get a role of their own from their sheet's columns (change log, etc.).
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import get_args

from pydantic import BaseModel, ConfigDict

from specalive.core.ir import MAX_QUOTE, SourceRole, TraceLink
from specalive.ingest.evidence import EvidenceChunk, Reliability, Source
from specalive.ingest.readers._common import CompletionClient, iso_date

# Ordered: the first rule whose keyword appears wins. Keywords are generic document vocabulary.
KEYWORD_RULES: tuple[tuple[SourceRole, tuple[str, ...]], ...] = (
    ("change_record", ("change record", "change request", "change log", "engineering change",
                       "change notice")),
    ("review_decision", ("minutes", "meeting notes", "design review", "review record")),
    ("verification_procedure", ("test procedure", "verification procedure", "acceptance test",
                                "validation procedure", "commissioning", "runbook",
                                "operating procedure", "test plan")),
    ("datasheet", ("datasheet", "data sheet")),
    ("design_note", ("design note", "design document", "technical note", "design memo",
                     "modeling note", "modelling note", "design description")),
    ("register", ("workbook", "register")),
    ("requirement_spec", ("specification", "requirements")),
    ("correspondence", ("email", "e-mail", "correspondence", "mail thread")),
    ("informal_note", ("engineer notes", "notebook", "scratch", "field notes", "shift notes",
                       "loose notes", "notes")),
)
# "model" names a legacy model only when the file really is one.
MODEL_ROLES: dict[str, SourceRole] = {"modelica": "legacy_model",
                                      "plantuml": "legacy_architecture"}
LATE_RULES: tuple[tuple[SourceRole, tuple[str, ...]], ...] = (
    ("reference_data", ("csv", "dataset", "data set", "time series", "trend", "result",
                        "schedule", "export", "derived data", "derived json", "test data",
                        "simulation data", "measurement")),
)
FORMAT_DEFAULTS: dict[str, SourceRole] = {
    "eml": "correspondence", "modelica": "legacy_model", "plantuml": "legacy_architecture",
    "csv": "reference_data", "json": "reference_data", "xlsx": "register",
    "image": "other",  # there is no role for diagrams; the index still gives their reliability
}
RELIABILITY_BY_ROLE: dict[SourceRole, Reliability] = {
    "change_record": "high", "review_decision": "high", "requirement_spec": "high",
    "design_note": "high", "datasheet": "high", "verification_procedure": "high",
    "register": "medium", "reference_data": "medium", "legacy_model": "medium",
    "correspondence": "medium", "legacy_architecture": "low", "informal_note": "low",
}
# Formats whose opening text is a document title worth reading for keywords. Code, data and
# email subjects are not: "model" in Modelica source or "test" in a subject line names nothing.
TITLED_FORMATS = frozenset({"pdf", "docx", "markdown", "text", "xlsx"})
HEAD_CHARS = 1500
TITLE_CHARS = 300

CLASSIFY_PROMPT = (
    "You classify one engineering document from a project packet. Choose the role that best "
    "describes the whole document: " + ", ".join(get_args(SourceRole)) + ". Give its revision "
    "and date only if the text states them, otherwise null. Explain the choice in one sentence."
)


class ClassificationReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: SourceRole
    revision: str | None
    date: str | None
    reason: str


def role_from_keywords(text: str, fmt: str) -> tuple[SourceRole, str] | None:
    """The role named by `text` (an index type cell or a document title) and the keyword that
    named it; None when no rule matches."""
    lowered = text.lower()
    for role, words in KEYWORD_RULES:
        for word in words:
            if word in lowered:
                return role, word
    if "model" in lowered and fmt in MODEL_ROLES:
        return MODEL_ROLES[fmt], "model"
    if "architecture" in lowered and fmt == "plantuml":
        return "legacy_architecture", "architecture"
    for role, words in LATE_RULES:
        for word in words:
            if word in lowered:
                return role, word
    return None


# --- header fields ------------------------------------------------------------------------

@dataclass(frozen=True)
class Header:
    document: str | None = None
    revision: str | None = None
    date: str | None = None
    status: str | None = None


_DOCUMENT = re.compile(r"\b(?:[Ss]upplier[ \t]+)?[Dd]ocument(?:[ \t]+(?:[Nn]o\.?|[Nn]umber|ID))?"
                       r"[ \t]*[:#]?[ \t]*\n?[ \t]*([A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)+)\b")
_REVISION = re.compile(r"\b(?:Revision|Rev\.?)[ \t]*[:\-]?[ \t]*\n?[ \t]*"
                       r"([A-Z0-9][A-Za-z0-9.]{0,7})")
_DATE_LABEL = re.compile(r"\bDate\b[ \t]*[:\-]?[ \t]*\n?([^\n]{0,40})")
_STATUS = re.compile(r"(?m)^[ \t]*(?:[Dd]ocument[ \t]+)?[Ss]tatus[ \t]*:?[ \t]*([^\n]*)$")


def parse_header(text: str) -> Header:
    """Document number, revision, date and status as a document states them near its top, in
    either "Label: value" or label-then-value-on-the-next-line form."""
    text = text.replace("**", "").replace("__", "")
    doc = _DOCUMENT.search(text)
    rev = _REVISION.search(text)
    labelled = _DATE_LABEL.search(text)
    date = (iso_date(labelled[1]) if labelled else None) or iso_date(text)
    status = None
    match = _STATUS.search(text)
    if match:
        status = match[1].strip()
        if not status:
            rest = text[match.end():].lstrip("\n").split("\n", 1)[0].strip()
            status = rest or None
    return Header(document=doc[1] if doc else None,
                  revision=rev[1].rstrip(".") if rev else None,
                  date=date, status=status[:120] if status else None)


def parse_index_revision(cell: str) -> tuple[str | None, str | None]:
    """Split an index "Revision / Date" cell such as "Rev A / 2026-01-15" into (revision, date)."""
    revisions: list[str] = []
    date: str | None = None
    for part in (p.strip() for p in cell.split("/")):
        if not part:
            continue
        found = iso_date(part)
        if found:
            date = date or found
            continue
        revisions.append(re.sub(r"^(?:Revision|Rev)\.?\s+", "", part))
    return (" / ".join(revisions) or None), date


# --- the source index ---------------------------------------------------------------------

@dataclass(frozen=True)
class IndexRow:
    chunk: EvidenceChunk
    type: str
    revision: str | None
    reliability: str | None


def _column(fields: dict[str, str], *needles: str) -> str | None:
    return next((k for k in fields if any(n in k.lower() for n in needles)), None)


def find_source_index(chunks: list[EvidenceChunk]) -> dict[str, IndexRow]:
    """Rows of any table that lists files with their type and reliability, keyed by file name."""
    rows: dict[str, IndexRow] = {}
    for c in chunks:
        if c.kind != "table_row" or not c.fields:
            continue
        file_col = _column(c.fields, "file", "artifact")
        type_col = _column(c.fields, "type")
        rel_col = _column(c.fields, "reliab")
        if not (file_col and type_col and rel_col):
            continue
        rev_col = _column(c.fields, "rev")
        name = PurePosixPath(c.fields[file_col].replace("\\", "/")).name.lower()
        rows.setdefault(name, IndexRow(chunk=c, type=c.fields[type_col],
                                       revision=c.fields.get(rev_col) if rev_col else None,
                                       reliability=c.fields[rel_col]))
    return rows


def _trace(chunk: EvidenceChunk) -> TraceLink:
    return TraceLink(source_id=chunk.source_id, locator=chunk.locator,
                     quote=chunk.text[:MAX_QUOTE])


def _head(source_chunks: list[EvidenceChunk], limit: int) -> str:
    parts: list[str] = []
    size = 0
    for c in source_chunks:
        if c.fields:  # spreadsheet-style rows describe data, not the document
            continue
        parts.append(c.text)
        size += len(c.text) + 1
        if size >= limit:
            break
    return "\n".join(parts)[:limit]


# --- classify -----------------------------------------------------------------------------

def _classify_one(source: Source, own: list[EvidenceChunk], index: dict[str, IndexRow],
                  llm: CompletionClient | None) -> Source:
    update: dict = {}
    basis: list[str] = []
    role: SourceRole | None = None
    method = "none"

    row = index.get(PurePosixPath(source.path).name.lower())
    if row is not None:
        update["classification_trace"] = _trace(row.chunk)
        if row.revision:
            update["revision"], update["date"] = parse_index_revision(row.revision)
        reliability = (row.reliability or "").strip().lower()
        if reliability in ("high", "medium", "low"):
            update["reliability"] = reliability
        found = role_from_keywords(row.type, source.format)
        if found:
            role, method = found[0], "source_index"
            basis.append(f"source index {row.chunk.locator}: type '{row.type}' "
                         f"matched '{found[1]}'")
        else:
            basis.append(f"source index {row.chunk.locator}: type '{row.type}' names no role")

    head = _head(own, HEAD_CHARS)
    # Only documents have a header block; "Rev C" in an email body cites another document.
    header = parse_header(head) if source.format in TITLED_FORMATS else Header()
    for key, value in (("document", header.document), ("doc_status", header.status),
                       ("revision", header.revision), ("date", header.date)):
        if value and not update.get(key):
            update[key] = value

    if role is None and source.format in TITLED_FORMATS:
        # The title alone first: header lines ("Released after design review") name other
        # documents as often as their own.
        for where, text in (("title", source.title), ("opening text", head[:TITLE_CHARS])):
            found = role_from_keywords(text or "", source.format)
            if found:
                role, method = found[0], "content"
                basis.append(f"document {where} contains '{found[1]}'")
                break
    if role is None and source.format in FORMAT_DEFAULTS:
        role, method = FORMAT_DEFAULTS[source.format], "format"
        basis.append(f"{source.format} files default to {role}")
    if role is None:
        role, method, note, llm_update = _ask_llm(source, head, llm)
        basis.append(note)
        for key, value in llm_update.items():
            if value and not update.get(key):
                update[key] = value

    if not update.get("reliability") and role in RELIABILITY_BY_ROLE:
        update["reliability"] = RELIABILITY_BY_ROLE[role]
        basis.append("reliability defaulted from role")
    update.update(role=role, classified_by=method, classification_basis="; ".join(basis))
    return source.model_copy(update=update)


def _ask_llm(source: Source, head: str, llm: CompletionClient | None
             ) -> tuple[SourceRole, str, str, dict]:
    if not head.strip():
        return "other", "none", "no rule matched and there is no text to classify", {}
    if llm is None:
        return "other", "none", "no rule matched and no LLM is available", {}
    from specalive.llm.client import LLMError

    try:
        reply = llm.complete(prompt=CLASSIFY_PROMPT, schema=ClassificationReply,
                             input_text=f"File name: {PurePosixPath(source.path).name}\n"
                                        f"Format: {source.format}\n\n{head}")
    except LLMError as exc:
        return "other", "none", f"no rule matched and the LLM call failed: {exc}", {}
    return reply.role, "llm", f"LLM: {reply.reason}", {
        "revision": reply.revision, "date": iso_date(reply.date) if reply.date else None}


def sheet_role(fields: dict[str, str]) -> SourceRole | None:
    """The role a table's rows carry, read from its column headers."""
    keys = [k.lower().rstrip("'") for k in fields]
    if any("file" in k for k in keys) and any("reliab" in k for k in keys):
        return None
    if any("change summary" in k for k in keys) or (
            "record" in keys and any("summary" in k for k in keys)):
        return "change_record"
    if "test id" in keys or any("acceptance criteri" in k for k in keys):
        return "verification_procedure"
    if any(k in ("req id", "requirement id") for k in keys):
        return "requirement_spec"
    return None


def classify(sources: list[Source], chunks: list[EvidenceChunk],
             llm: CompletionClient | None) -> tuple[list[Source], list[EvidenceChunk]]:
    index = find_source_index(chunks)
    by_source: dict[str, list[EvidenceChunk]] = {}
    for c in chunks:
        by_source.setdefault(c.source_id, []).append(c)
    classified = [_classify_one(s, by_source.get(s.id, []), index, llm) for s in sources]
    roles = {s.id: s.role for s in classified}
    labelled = [c.model_copy(update={"role": (sheet_role(c.fields) if c.fields else None)
                                     or roles.get(c.source_id, "other")}) for c in chunks]
    return classified, labelled
