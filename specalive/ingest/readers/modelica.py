# Purpose: reads a Modelica file as code. Blank-line-separated blocks (capped in size) become
# `code` chunks located by line range, with every comment kept: legacy models state their own
# staleness there ("archived", "predates"), and phase 4 needs that as much as the parameters.
from __future__ import annotations

from pathlib import Path

from specalive.ingest.evidence import SourceFormat
from specalive.ingest.readers._common import (
    ReadContext,
    ReadResult,
    block_chunks,
    capped,
    paragraphs,
)
from specalive.ingest.readers.text import load_lines


def read_code(path: Path, source_id: str, fmt: SourceFormat) -> ReadResult:
    blocks = [part for para in paragraphs(load_lines(path)) for part in capped(para)]
    chunks = block_chunks(source_id, blocks, "code")
    if not chunks:
        return ReadResult(fmt, "unread", "file is empty")
    return ReadResult(fmt, "read", None, None, chunks)


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    return read_code(path, source_id, "modelica")
