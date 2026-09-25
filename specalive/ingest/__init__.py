# Purpose: the ingest layer — input files to located evidence (evidence.json). One reader per
# format (readers/), source classification (classify.py) and the stage entry point (ingest.py).
# It produces evidence, never IR; it may import `config`, `core`, and `llm` for vision and the
# classification fallback only (ARCHITECTURE.md layer table).
