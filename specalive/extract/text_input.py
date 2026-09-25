# Purpose: the plain-text input path (FR-04 requirement 17). A pasted paragraph or a text file
# becomes a one-source evidence bundle with role requirement_spec, chunked into line-located
# paragraphs exactly as the ingest text reader does, so it runs through the same extraction as a
# full bundle (R-EXT-8: one code path).
from __future__ import annotations

from specalive.core.ids import make_id
from specalive.ingest.evidence import EvidenceBundle, Source
from specalive.ingest.readers._common import Line, block_chunks, capped, paragraphs


def text_bundle(text: str, name: str = "text") -> EvidenceBundle:
    """Evidence for `text`; `name` (e.g. the file name) names the source."""
    source_id = make_id("src", f"src {name}")
    lines = [Line(i, t.rstrip()) for i, t in enumerate(text.splitlines(), start=1)]
    blocks = [part for para in paragraphs(lines) for part in capped(para)]
    chunks = block_chunks(source_id, blocks, "prose")
    source = Source(id=source_id, path=name, format="text",
                    status="read" if chunks else "unread",
                    reason=None if chunks else "the text is empty", role="requirement_spec",
                    classified_by="none",
                    classification_basis="plain-text input is treated as a requirement spec")
    return EvidenceBundle(root=".", sources=[source], chunks=chunks)
