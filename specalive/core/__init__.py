# Purpose: the contract layer — the IR schema (ir.py), the component catalogue loader
# (catalogue.py), the SI unit table (units.py) and deterministic ids (ids.py). Every other layer
# codes against it; it imports only `config` and must import without pulling in `openai`.
