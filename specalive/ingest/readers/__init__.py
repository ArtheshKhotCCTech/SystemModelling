# Purpose: the reader registry. detect_format() picks a format from the file extension and, when
# the extension is missing or unknown, from the content (magic bytes, then leading text);
# read_source() runs that format's reader and turns any exception into an `unread` result with
# the reason, so one broken file never stops a bundle and nothing is silently dropped (R-ING-1).
from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

from specalive.ingest.evidence import SourceFormat
from specalive.ingest.readers import (
    csv_,
    docx,
    eml,
    image,
    json_,
    modelica,
    pdf,
    puml,
    text,
    xlsx,
)
from specalive.ingest.readers._common import ReadContext, ReadResult, unread

__all__ = ["ReadContext", "ReadResult", "detect_format", "read_source"]

Reader = Callable[[Path, str, ReadContext], ReadResult]

EXTENSIONS: dict[str, SourceFormat] = {
    ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".eml": "eml",
    ".txt": "text", ".text": "text", ".log": "text", ".md": "markdown", ".markdown": "markdown",
    ".mo": "modelica", ".puml": "plantuml", ".plantuml": "plantuml", ".pu": "plantuml",
    ".json": "json", ".csv": "csv", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".bmp": "image", ".webp": "image",
}

READERS: dict[SourceFormat, Reader] = {
    "pdf": pdf.read, "docx": docx.read, "xlsx": xlsx.read, "eml": eml.read,
    "text": text.read_text, "markdown": text.read_markdown, "modelica": modelica.read,
    "plantuml": puml.read, "json": json_.read, "csv": csv_.read, "image": image.read,
}

_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")
_MAIL_HEADERS = ("from:", "to:", "subject:", "date:", "received:", "return-path:",
                 "message-id:", "mime-version:")


def _sniff(path: Path) -> SourceFormat:
    head = path.read_bytes()[:4096]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(_IMAGE_MAGIC) or head[8:12] == b"WEBP":
        return "image"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        return "unknown"
    if b"\x00" in head:
        return "unknown"
    try:
        lead = head.decode("utf-8").lstrip().lower()
    except UnicodeDecodeError:
        return "unknown"
    if lead.startswith("@startuml"):
        return "plantuml"
    if lead.startswith(_MAIL_HEADERS):
        return "eml"
    return "text"


def detect_format(path: Path) -> SourceFormat:
    return EXTENSIONS.get(path.suffix.lower()) or _sniff(path)


def read_source(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    try:
        fmt = detect_format(path)
    except OSError as exc:
        return unread("unknown", f"cannot open file: {exc}")
    reader = READERS.get(fmt)
    if reader is None:
        return unread(fmt, "unsupported format: no reader for this file type")
    try:
        return reader(path, source_id, ctx)
    except Exception as exc:  # noqa: BLE001 — a reader failure is data about the input
        return unread(fmt, f"{fmt} reader failed: {type(exc).__name__}: {exc}")
