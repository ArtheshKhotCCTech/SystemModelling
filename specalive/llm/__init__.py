# Purpose: the LLM layer — the OpenAI client with strict structured outputs (client.py) and its
# on-disk response cache (cache.py). Imported only by extract/, repair/ and ingest/ (vision);
# generate/ must never import it (ARCHITECTURE.md layer table).
