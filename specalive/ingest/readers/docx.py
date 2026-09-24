# Purpose: reads a Word document in body order, so a table stays under the heading it sits in.
# Each non-empty paragraph is a chunk located by paragraph number and current section; a table of
# three or more columns becomes one chunk per row keyed by its first-row headers, a two-column table
# one "key: value" chunk per row (document header tables are shaped this way). Page headers are
# read too; embedded images are counted and reported, since their content is not.
from __future__ import annotations

from pathlib import Path

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import (
    ReadContext,
    ReadResult,
    fields_text,
    row_fields,
)


def _section(heading: str | None) -> str:
    return f" (section '{heading}')" if heading else ""


def _row_cells(row) -> list[str]:
    cells: list[str] = []
    previous = None
    for cell in row.cells:
        # python-docx repeats a merged cell once per grid column it spans.
        if previous is not None and cell._tc is previous:
            continue
        previous = cell._tc
        cells.append(cell.text.strip())
    return cells


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    chunks: list[EvidenceChunk] = []
    heading: str | None = None
    title: str | None = (document.core_properties.title or "").strip() or None
    paragraph_no = table_no = 0

    for number, section in enumerate(document.sections, start=1):
        text = "\n".join(p.text.strip() for p in section.header.paragraphs if p.text.strip())
        if text:
            chunks.append(EvidenceChunk(source_id=source_id, text=text, kind="prose",
                                        locator=f"page header of section {number}"))

    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            paragraph_no += 1
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            if style.startswith("Title") and title is None:
                title = " ".join(text.split())
            if style.startswith(("Heading", "Title")):
                heading = " ".join(text.split())
            chunks.append(EvidenceChunk(source_id=source_id, text=text, kind="prose",
                                        locator=f"paragraph {paragraph_no}{_section(heading)}"))
        elif tag == "tbl":
            table_no += 1
            chunks += _table(Table(element, document), table_no, heading, source_id)

    if title is None:
        first = next((c.text for c in chunks if c.locator.startswith("paragraph")), None)
        title = " ".join(first.split()) if first else None
    images = len(document.inline_shapes)
    if images:
        return ReadResult("docx", "partial", f"{images} embedded image(s) not read", title,
                          chunks)
    return ReadResult("docx", "read", None, title, chunks)


def _table(table, table_no: int, heading: str | None, source_id: str) -> list[EvidenceChunk]:
    rows = [_row_cells(r) for r in table.rows]
    rows = [(i, r) for i, r in enumerate(rows, start=1) if any(r)]
    if not rows:
        return []
    width = max(len(r) for _, r in rows)
    where = _section(heading)
    chunks = []
    if width <= 2:
        for i, cells in rows:
            text = ": ".join(c for c in cells if c)
            chunks.append(EvidenceChunk(source_id=source_id, text=text, kind="table_row",
                                        locator=f"table {table_no}, row {i}{where}"))
        return chunks
    (_, headers), body = rows[0], rows[1:]
    for i, cells in body:
        fields = row_fields(headers, cells)
        chunks.append(EvidenceChunk(source_id=source_id, text=fields_text(fields),
                                    kind="table_row", fields=fields,
                                    locator=f"table {table_no}, row {i}{where}"))
    return chunks
