# Purpose: reads a JSON export (BIM, CAD, metrology) as located records. Each top-level entry is a
# chunk addressed by its JSON path ("$.space"); an entry too large to quote is split into its
# members or array elements ("$.items[3]") until it fits. A record of scalars also keeps its
# key -> value map in `fields`. Key order is the file's own, so the output is deterministic.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import MAX_CHUNK_CHARS, ReadContext, ReadResult, cell_text


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _fields(value: Any) -> dict[str, str]:
    if isinstance(value, dict) and all(not isinstance(v, (dict, list)) for v in value.values()):
        return {str(k): cell_text(v) for k, v in value.items() if v is not None}
    return {}


def _walk(value: Any, path: str, source_id: str, out: list[EvidenceChunk]) -> None:
    text = _render(value)
    if len(text) <= MAX_CHUNK_CHARS or not isinstance(value, (dict, list)) or not value:
        out.append(EvidenceChunk(source_id=source_id, locator=path, text=text,
                                 kind="table_row", fields=_fields(value)))
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _walk(child, f"{path}.{key}", source_id, out)
    else:
        for i, child in enumerate(value):
            _walk(child, f"{path}[{i}]", source_id, out)


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ReadResult("json", "unread", f"not valid JSON: {exc}")
    chunks: list[EvidenceChunk] = []
    if isinstance(data, dict) and data:
        for key, child in data.items():
            _walk(child, f"$.{key}", source_id, chunks)
    else:
        _walk(data, "$", source_id, chunks)
    return ReadResult("json", "read", None, None, chunks)
