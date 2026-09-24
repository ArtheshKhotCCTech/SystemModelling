# Purpose: what every reader shares — the ReadContext it is given, the ReadResult it returns, and
# the helpers that keep chunks small and quotable: splitting located lines into chunks at
# boundaries (headings, id-led items, blank lines) under a size cap, rendering a table row with its
# headers, and parsing the date formats found in document headers and email threads.
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from specalive.config import Settings
from specalive.ingest.evidence import ChunkKind, EvidenceChunk, SourceFormat, SourceStatus

# A chunk should be one paragraph, one table row, one message or one code block. Anything longer
# is split at line boundaries so a quote can be found and checked.
MAX_CHUNK_CHARS = 900


class CompletionClient(Protocol):
    """The part of llm.client.LLMClient readers and the classifier use."""

    def complete(self, *, prompt: str, input_text: str, schema: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class ReadContext:
    settings: Settings
    llm: CompletionClient | None


@dataclass(frozen=True)
class ReadResult:
    format: SourceFormat
    status: SourceStatus
    reason: str | None = None
    title: str | None = None
    chunks: list[EvidenceChunk] = field(default_factory=list)


def unread(fmt: SourceFormat, reason: str) -> ReadResult:
    return ReadResult(format=fmt, status="unread", reason=reason)


@dataclass(frozen=True)
class Line:
    number: int  # 1-based position in the source (or page)
    text: str


def line_range(first: int, last: int) -> str:
    return f"line {first}" if first == last else f"lines {first}-{last}"


def split_blocks(lines: Sequence[Line], starts_block: Callable[[str], bool],
                 max_chars: int = MAX_CHUNK_CHARS) -> list[list[Line]]:
    """Group consecutive lines into blocks: a new block starts where `starts_block` says so, and a
    block is cut before it would pass `max_chars`."""
    blocks: list[list[Line]] = []
    current: list[Line] = []
    size = 0
    for line in lines:
        if current and (starts_block(line.text) or size + len(line.text) + 1 > max_chars):
            blocks.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line.text) + 1
    if current:
        blocks.append(current)
    return blocks


def paragraphs(lines: Sequence[Line]) -> list[list[Line]]:
    """Runs of non-blank lines separated by blank lines."""
    out: list[list[Line]] = []
    current: list[Line] = []
    for line in lines:
        if line.text.strip():
            current.append(line)
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def block_chunks(source_id: str, blocks: Sequence[Sequence[Line]], kind: ChunkKind,
                 locate: Callable[[int, int], str] = line_range) -> list[EvidenceChunk]:
    chunks = []
    for block in blocks:
        text = "\n".join(line.text for line in block).strip("\n")
        if text.strip():
            chunks.append(EvidenceChunk(source_id=source_id, text=text, kind=kind,
                                        locator=locate(block[0].number, block[-1].number)))
    return chunks


def capped(block: Sequence[Line], max_chars: int = MAX_CHUNK_CHARS) -> list[list[Line]]:
    return split_blocks(block, lambda _: False, max_chars)


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() \
            else value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def row_fields(headers: Sequence[str], values: Sequence[str]) -> dict[str, str]:
    """Header -> value for the non-empty cells; an unnamed column is named by its position."""
    fields: dict[str, str] = {}
    for i, value in enumerate(values):
        if not value:
            continue
        name = headers[i] if i < len(headers) and headers[i] else f"column {i + 1}"
        while name in fields:
            name += "'"
        fields[name] = value
    return fields


def fields_text(fields: dict[str, str]) -> str:
    return " | ".join(f"{k}: {v}" for k, v in fields.items())


# --- dates ------------------------------------------------------------------------------------

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|" \
          "june|july|august|september|october|november|december"
DATE_RE = re.compile(
    rf"\b(\d{{4}}-\d{{2}}-\d{{2}})\b"
    rf"|\b(\d{{1,2}}[ -](?:{_MONTHS})\.?[ -]\d{{4}})\b"
    rf"|\b((?:{_MONTHS})\.? \d{{1,2}},? \d{{4}})\b", re.IGNORECASE)
_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%b %d, %Y",
                 "%B %d, %Y", "%b %d %Y", "%B %d %Y")


def iso_date(text: str) -> str | None:
    """The first date written in `text`, as YYYY-MM-DD; None when there is none."""
    for match in DATE_RE.finditer(text):
        raw = next(g for g in match.groups() if g).replace(".", "")
        raw = re.sub(r"(?i)\bsept\b", "Sep", raw)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
    return None


_MAIL_FORMATS = ("%A, %B %d, %Y %H:%M", "%A, %B %d, %Y %I:%M %p", "%B %d, %Y %H:%M",
                 "%d %B %Y %H:%M", "%Y-%m-%d %H:%M")


def parse_mail_date(text: str) -> datetime | None:
    """A message timestamp from an RFC 2822 Date header or a quoted 'Sent:' line; naive times are
    taken as UTC so every result compares."""
    text = text.strip()
    if not text:
        return None
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        for fmt in _MAIL_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        day = iso_date(text)
        parsed = datetime.fromisoformat(day) if day else None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
