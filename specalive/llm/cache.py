# Purpose: on-disk cache of LLM responses, which is what makes runs repeatable and the test suite
# offline. The key is a SHA-256 over the canonical JSON of model name, full prompt, response
# schema and a hash of the input, so changing any of them — the model included (R-FND-5) — is a
# miss, never a stale hit. One JSON file per entry, written atomically; unreadable files are misses.
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def key(model: str, prompt: str, schema: dict[str, Any], input_text: str) -> str:
        material = {
            "model": model,
            "prompt": prompt,
            "schema": schema,
            "input_sha256": _sha256(input_text),
        }
        return _sha256(json.dumps(material, sort_keys=True, ensure_ascii=False))

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Any | None:
        try:
            return json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=1)
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, self._path(key))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def clear(self) -> int:
        """Delete every entry; return how many were removed."""
        if not self.directory.is_dir():
            return 0
        removed = 0
        for entry in self.directory.glob("*.json"):
            entry.unlink()
            removed += 1
        return removed
