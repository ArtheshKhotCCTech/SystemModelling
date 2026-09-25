# Purpose: reads a PDF's text layer page by page with pypdf. Extracted text arrives one line (often
# one table cell) at a time with no blank lines, so a page is cut into chunks at numbered headings
# ("2. Setpoints") and id-led items ("AC-01 - ..."), under the size cap, each located by page and
# line. A page that fails is reported (partial); a file with no text layer at all is unread.
from __future__ import annotations

import logging
import re
from pathlib import Path

from specalive.ingest.readers._common import (
    Line,
    ReadContext,
    ReadResult,
    block_chunks,
    line_range,
    split_blocks,
    unread,
)

HEADING = re.compile(r"^\d+(?:\.\d+)*\.\s+[A-Z]")
ID_ITEM = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\s+[-–—:]\s")
BULLET = re.compile(r"^[•▪●*\-]\s")


def _starts_block(text: str) -> bool:
    return bool(HEADING.match(text) or ID_ITEM.match(text) or BULLET.match(text))


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    import pypdf

    # pypdf logs recoverable structure problems (a bad xref offset) as warnings; the text is
    # still read, so they are not worth a line on the terminal.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = pypdf.PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return unread("pdf", "encrypted PDF; no password available")
        pages = list(reader.pages)
    except Exception as exc:  # noqa: BLE001 — pypdf raises many types for a broken file
        return unread("pdf", f"not a readable PDF: {type(exc).__name__}: {exc}")

    chunks = []
    failed: list[str] = []
    empty = 0
    for number, page in enumerate(pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            failed.append(f"page {number} ({type(exc).__name__})")
            continue
        lines = [Line(i, t.strip()) for i, t in enumerate(raw.splitlines(), start=1)
                 if t.strip()]
        if not lines:
            empty += 1
            continue
        blocks = split_blocks(lines, _starts_block)
        chunks += block_chunks(source_id, blocks, "prose",
                               lambda a, b, n=number: f"page {n}, {line_range(a, b)}")

    title = _title(reader)
    if not chunks:
        reason = "no extractable text layer (scanned or image-only PDF?)" if not failed \
            else f"text extraction failed on {', '.join(failed)}"
        return unread("pdf", reason)
    problems = failed + ([f"{empty} page(s) without text"] if empty else [])
    if problems:
        return ReadResult("pdf", "partial", "; ".join(problems), title, chunks)
    return ReadResult("pdf", "read", None, title, chunks)


def _title(reader) -> str | None:
    try:
        title = (reader.metadata or {}).get("/Title")
    except Exception:  # noqa: BLE001
        return None
    title = str(title).strip() if title else ""
    return title if title and title.lower() not in ("(anonymous)", "untitled") else None
