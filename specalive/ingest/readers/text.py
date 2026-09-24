# Purpose: reads plain text and Markdown. Plain text is split into blank-line paragraphs located by
# line range. Markdown keeps its structure: headings, each list item, each paragraph and each
# pipe-table row (paired with the table's header) is its own chunk, located by line and the
# heading it sits under; `**bold**` markers are left as written so quotes stay verbatim.
from __future__ import annotations

import re
from pathlib import Path

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import (
    Line,
    ReadContext,
    ReadResult,
    block_chunks,
    capped,
    fields_text,
    line_range,
    paragraphs,
    row_fields,
)

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def load_lines(path: Path) -> list[Line]:
    text = path.read_bytes().decode("utf-8", errors="replace")
    return [Line(i, t.rstrip()) for i, t in enumerate(text.splitlines(), start=1)]


def read_text(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    lines = load_lines(path)
    blocks = [part for para in paragraphs(lines) for part in capped(para)]
    chunks = block_chunks(source_id, blocks, "prose")
    if not chunks:
        return ReadResult("text", "unread", "file is empty")
    return ReadResult("text", "read", None, chunks[0].text.splitlines()[0].strip(), chunks)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def read_markdown(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    lines = load_lines(path)
    chunks: list[EvidenceChunk] = []
    heading: str | None = None
    title: str | None = None
    block: list[Line] = []
    table_header: list[str] | None = None

    def where(a: int, b: int) -> str:
        return f"section '{heading}', {line_range(a, b)}" if heading else line_range(a, b)

    def flush() -> None:
        nonlocal block
        if block:
            chunks.extend(block_chunks(source_id, capped(block), "prose", where))
        block = []

    for i, line in enumerate(lines):
        text = line.text
        match = HEADING.match(text)
        if match:
            flush()
            table_header = None
            heading = match[2]
            title = title or (heading if len(match[1]) == 1 else None)
            chunks.append(EvidenceChunk(source_id=source_id, text=text, kind="prose",
                                        locator=where(line.number, line.number)))
            continue
        if TABLE_ROW.match(text):
            flush()
            nxt = lines[i + 1].text if i + 1 < len(lines) else ""
            if table_header is None and TABLE_RULE.match(nxt):
                table_header = _cells(text)
            elif not TABLE_RULE.match(text):
                fields = row_fields(table_header or [], _cells(text))
                if fields:
                    chunks.append(EvidenceChunk(source_id=source_id, text=fields_text(fields),
                                                kind="table_row", fields=fields,
                                                locator=where(line.number, line.number)))
            continue
        table_header = None
        if not text.strip():
            flush()
        elif LIST_ITEM.match(text):
            flush()
            block = [line]
        else:
            block.append(line)
    flush()
    if not chunks:
        return ReadResult("markdown", "unread", "file is empty")
    return ReadResult("markdown", "read", None, title, chunks)
