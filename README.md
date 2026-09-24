# SpecAlive

Turns a bundle of messy engineering inputs into a traced intermediate representation (IR), a
SysML v2 textual model and a Modelica model that compiles and simulates. Every element traces
to the input that justified it or to a declared assumption.

Read next: `AGENTS.md`, then `docs/` (start with `docs/implementation_plan.md`).

## Status
Phase 1 (foundation): package skeleton, CLI, LLM client with response cache, toolchain probes.
The pipeline stages are stubs until their phases land.

## Setup
Full checklist: `docs/devenv.md`.

```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
specalive doctor
pytest
```

`specalive doctor` must report OK on all four checks before any modelling phase starts.

## Compiling the generated model
*To be filled in by phase 6/9: the exact `omc` command that compiles the committed model.*
