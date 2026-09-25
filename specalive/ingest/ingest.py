# Purpose: the ingest stage. ingest() walks a bundle folder recursively in sorted path order (or
# takes one file), gives every file a deterministic source id from its path, reads it with the
# format's reader and classifies the lot; every file becomes a Source with a status, whether or
# not it could be read. write_evidence() writes evidence.json with no clock or random value in
# it, so the same bundle gives byte-identical output.
from __future__ import annotations

from pathlib import Path

from specalive.config import Settings
from specalive.core.ids import IdCollision, IdRegistry
from specalive.ingest.classify import classify
from specalive.ingest.evidence import EvidenceBundle, EvidenceChunk, Source
from specalive.ingest.readers import ReadContext, read_source
from specalive.ingest.readers._common import CompletionClient

EVIDENCE_FILE = "evidence.json"


class InputNotFound(FileNotFoundError):
    """The bundle folder or file does not exist."""


def _files(path: Path) -> tuple[Path, list[Path]]:
    if path.is_file():
        return path.parent, [path]
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        return path, sorted(files, key=lambda p: p.relative_to(path).as_posix())
    raise InputNotFound(f"input not found: {path}")


def _source_id(ids: IdRegistry, rel: str) -> str:
    # Two paths that fold to one id (a-b.txt, a_b.txt) are told apart by a counter, assigned in
    # sorted path order so the result is still deterministic.
    # Every source id starts "src_", whatever the path starts with.
    tag, n = f"src {rel}", 1
    while True:
        try:
            return ids.make("src", tag)
        except IdCollision:
            n += 1
            tag = f"src {rel} {n}"


def ingest(path: Path, settings: Settings, llm: CompletionClient | None = None) -> EvidenceBundle:
    """Read every file under `path` into evidence. `llm` serves vision and the classification
    fallback; pass None to run without any model call."""
    root, files = _files(Path(path))
    ctx = ReadContext(settings=settings, llm=llm)
    ids = IdRegistry()
    sources: list[Source] = []
    chunks: list[EvidenceChunk] = []
    for file in files:
        rel = file.relative_to(root).as_posix()
        source_id = _source_id(ids, rel)
        result = read_source(file, source_id, ctx)
        sources.append(Source(id=source_id, path=rel, format=result.format,
                              status=result.status, reason=result.reason, title=result.title))
        chunks.extend(result.chunks)
    sources, chunks = classify(sources, chunks, llm)
    return EvidenceBundle(root=str(root.resolve()), sources=sources, chunks=chunks)


def write_evidence(bundle: EvidenceBundle, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / EVIDENCE_FILE
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(bundle.model_dump_json(indent=2))
        fh.write("\n")
    return target
