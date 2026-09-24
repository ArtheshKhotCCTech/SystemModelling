# Purpose: reads a PlantUML architecture drawing as code, the same way as a Modelica file:
# blank-line blocks with line ranges and every `'` comment kept, because partial legacy drawings
# say what they leave out ("intentionally incomplete") in their comments.
from __future__ import annotations

from pathlib import Path

from specalive.ingest.readers._common import ReadContext, ReadResult
from specalive.ingest.readers.modelica import read_code


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    return read_code(path, source_id, "plantuml")
