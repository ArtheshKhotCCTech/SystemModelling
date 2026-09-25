# Purpose: the evidence records the ingest stage writes and the extract stage reads. A Source is one
# input file with its read status and its classification (role, revision, date, reliability, and
# how that was decided); an EvidenceChunk is a small, quotable piece of one source with a locator a
# reviewer can follow back to the original. EvidenceBundle checks every chunk names a real source.
# This is evidence, not IR: phase 4 maps Source onto core.ir.Source.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from specalive.core.ir import SourceRole, TraceLink

SourceFormat = Literal["pdf", "docx", "xlsx", "eml", "text", "markdown", "modelica", "plantuml",
                       "json", "csv", "image", "unknown"]
SourceStatus = Literal["read", "partial", "unread"]
ChunkKind = Literal["prose", "table_row", "code", "diagram_text", "email_message",
                    "data_summary"]
Reliability = Literal["high", "medium", "low"]
# How the role was decided: a source-index row, the document's own title and header, the file
# format's default, the LLM, or nothing (role "other").
ClassifiedBy = Literal["source_index", "content", "format", "llm", "none"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceChunk(_Record):
    source_id: str
    locator: str = Field(min_length=1, description="page+line, sheet+row, section, message")
    text: str = Field(min_length=1)
    kind: ChunkKind
    role: SourceRole | None = Field(None, description="defaults to the source's role")
    fields: dict[str, str] = Field({}, description="column header -> cell, for table rows")


class Source(_Record):
    id: str
    path: str = Field(description="bundle-relative, forward slashes")
    format: SourceFormat
    status: SourceStatus
    reason: str | None = Field(None, description="why the source was not fully read")
    title: str | None = None
    role: SourceRole = "other"
    revision: str | None = None
    date: str | None = Field(None, description="ISO date")
    reliability: Reliability | None = None
    document: str | None = Field(None, description="document number stated in its header")
    doc_status: str | None = Field(None, description="status stated in its header")
    classified_by: ClassifiedBy = "none"
    classification_basis: str | None = None
    classification_trace: TraceLink | None = None

    @model_validator(mode="after")
    def _reason_when_not_read(self) -> Source:
        if self.status != "read" and not self.reason:
            raise ValueError(f"source {self.id} is {self.status} but gives no reason")
        return self


class EvidenceBundle(_Record):
    root: str = Field(description="absolute path of the bundle folder")
    sources: list[Source]
    chunks: list[EvidenceChunk]

    @model_validator(mode="after")
    def _references_resolve(self) -> EvidenceBundle:
        seen: set[str] = set()
        for s in self.sources:
            if s.id in seen:
                raise ValueError(f"duplicate source id {s.id}")
            seen.add(s.id)
        dangling = sorted({c.source_id for c in self.chunks} - seen)
        if dangling:
            raise ValueError(f"chunks name unknown source(s): {', '.join(dangling)}")
        return self
