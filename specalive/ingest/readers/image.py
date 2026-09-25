# Purpose: reads a diagram image. With vision enabled in config, the image goes to the vision model
# with a prompt asking only for visible labels, tags and connections, returned as diagram_text
# chunks and marked partial — model transcription is not verbatim text. With vision off, or when
# the model call fails, the image is recorded unread with the reason; it is never silently skipped.
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import ReadContext, ReadResult, unread

VISION_PROMPT = (
    "You transcribe engineering diagrams. List only what is visibly written or drawn in the "
    "image: every text label and tag exactly as written, and every drawn connection between two "
    "labelled elements with the label on the connection if there is one. Do not infer, "
    "complete or correct anything that is not visible."
)

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}


class DiagramConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    label: str | None


class DiagramReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: list[str]
    connections: list[DiagramConnection]


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    if not ctx.settings.vision:
        return unread("image", "image not read: vision is disabled (set SPECALIVE_VISION=1)")
    if ctx.llm is None:
        return unread("image", "image not read: no LLM client available for vision")
    from specalive.llm.client import LLMError

    try:
        reading = ctx.llm.complete(prompt=VISION_PROMPT, input_text=f"Diagram file: {path.name}",
                                   schema=DiagramReading, image=path.read_bytes(),
                                   image_media_type=MEDIA_TYPES.get(path.suffix.lower(),
                                                                    "image/png"))
    except LLMError as exc:
        return unread("image", f"image not read: vision call failed: {exc}")

    chunks = []
    if reading.labels:
        chunks.append(EvidenceChunk(source_id=source_id, locator="vision reading: labels",
                                    text="\n".join(reading.labels), kind="diagram_text"))
    if reading.connections:
        lines = [f"{c.source} -> {c.target}" + (f" : {c.label}" if c.label else "")
                 for c in reading.connections]
        chunks.append(EvidenceChunk(source_id=source_id, locator="vision reading: connections",
                                    text="\n".join(lines), kind="diagram_text"))
    if not chunks:
        return unread("image", "vision model found no labels or connections")
    return ReadResult("image", "partial",
                      f"transcribed by the vision model ({ctx.settings.model}); not verbatim text",
                      None, chunks)
