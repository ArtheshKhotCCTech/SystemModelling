# ARCHITECTURE OF SPECALIVE

## Key Architecture Guidelines
Always follow the decisions in `ADR.md`.

### The shape of the system
SpecAlive is a **staged pipeline with a typed intermediate representation (IR) at its
centre**. The LLM turns messy evidence into IR; deterministic code turns IR into SysML v2
and Modelica; external tools check the results; reports explain them.

```
 inputs ──► ingest ──► evidence ──► extract ──► IR ──┬──► generate.sysml ──► .sysml ──► SysML validator
 (bundle                            (LLM)            │
  or text)                                           ├──► generate.modelica ─► .mo ──► omc check ──► simulate ──► verify
                                                     │                          ▲  │
                                                     │                          └──┘ repair (LLM, max 3,
                                                     │                                topology frozen)
                                                     └──► report (summary, traceability, assumptions, correspondence)
```

Three rules make this shape work:
1. **The IR is the single source of truth.** Both models are generated from it, never from
   each other or from the raw input.
2. **The LLM never writes a model.** It fills the IR (in `extract/`) and proposes fixes to
   compile errors (in `repair/`). Everything in `generate/` is templates over the IR.
3. **Every stage writes its result to disk, and the next stage reads it from disk.** This is
   what lets the three tracks work in parallel: Track B can generate from a golden IR file
   before Track A can produce one.

### Modules
`specalive/` is one package with a layered structure and acyclic dependencies. **The layers
are directories**, so the direction of a dependency is visible in its import path.

```
specalive/
  __init__.py
  config.py                  # read by every layer; reads nothing
  core/       ir.py  catalogue.py  units.py  ids.py
  llm/        client.py  cache.py
  ingest/     evidence.py  classify.py  readers/{pdf,docx,xlsx,eml,text,modelica,puml,json,csv,image}.py
  extract/    extract.py  merge.py  precedence.py  gaps.py  text_input.py  questions.py
  generate/   sysml.py  modelica.py  controller.py  templates/{sysml,modelica}/
  toolchain/  omc.py  sysml_validate.py
  repair/     compile_loop.py
  verify/     simulate.py  compare.py  acceptance.py  coverage.py
  report/     summary.py  traceability.py  assumptions.py  correspondence.py  plots.py
  cli.py
catalogue/    components.yaml
tests/        goldens/  fixtures/  adversarial/  test_*.py
```

Allowed imports, and only these:

| Layer | May import |
|---|---|
| `config` | nothing |
| `core` | `config` |
| `llm` | `config`, `core` |
| `ingest` | `config`, `core`, `llm` (vision only) |
| `extract` | `config`, `core`, `llm`, `ingest` |
| `generate` | `config`, `core` — **not `llm`** |
| `toolchain` | `config` |
| `repair` | `config`, `core`, `llm`, `generate`, `toolchain` |
| `verify` | `config`, `core`, `toolchain` |
| `report` | `config`, `core`, `verify` |
| `cli` | everything; nothing imports it |

- `core/` is the contract. It holds the IR schema, the catalogue loader, unit handling and
  deterministic id construction. It must import without pulling in `openai`.
- `generate/` must be reproducible byte for byte from the same IR. No clock, no randomness,
  no network, no unordered iteration reaching the output.
- `repair/` is the **only** place the LLM sees generated code. It may change the `.mo`
  text; it may not change the IR, and a repair that changes the set of components or
  connections is rejected.
- Nothing in `specalive/` reads `tests/`. Golden IRs are test data.

### Stage contracts and the run folder
Each stage is also a CLI subcommand, so each can be run and tested alone.

| Stage | Subcommand | Reads | Writes (under `out/<run>/`) | Phase |
|---|---|---|---|---|
| Ingest | `specalive ingest <bundle>` | input files | `evidence.json` | 3 |
| Extract | `specalive extract` | `evidence.json` | `ir.json` | 4 |
| Generate | `specalive generate` | `ir.json` | `model.sysml`, `model.mo` | 5, 6 |
| Validate / compile | `specalive compile` | `model.sysml`, `model.mo` | `sysml_validation.json`, `compile.log`, `repair_log.json` | 5, 6 |
| Simulate / verify | `specalive verify` | `model.mo`, reference data | `sim/result.csv`, `verification.json`, `coverage.json` | 7 |
| Report | `specalive report` | all of the above | `report/*.md`, `report/plots/*.png` | 8 |
| All | `specalive run <bundle or text>` | input | everything, plus `run.json` | 9 |

`run.json` records the tool versions, the model name, per-stage timings, and **the exact
`omc` command that compiles the model**, because judges run that command.

A stage that cannot run writes its artefact with status `NOT RUN` and the reason. It never
writes a pass it did not earn, and it never silently skips.

### The IR in one paragraph
A `SystemModel` holds `parts` (each with a `kind` from the catalogue, `tags`/aliases,
`attributes` and `ports`), `connections` between ports, `parameters` (value, unit, status,
authority), `state_machines` (states, transitions with guard, trigger and action, regions
for parallel branches), `requirements` (with status and what verifies them),
`acceptance_criteria`, and the honesty records: `assumptions`, `questions`, `conflicts`.
Every element carries `trace: list[TraceLink]` or references an `Assumption`, and a
`confidence`. The full schema is `FR-02-ir-and-catalogue.md`.

### The component catalogue
`catalogue/components.yaml` maps an IR `kind` (e.g. `tank`, `on_off_valve`,
`level_sensor`, `sequence_controller`, `flow_source`, `room_volume`) to:
- the SysML v2 part definition to emit,
- the Modelica class to instantiate and the parameter names it takes,
- the port mapping from IR port roles to Modelica connector names.

It is how domain knowledge enters the system, and the constraint that stops invented
components: extraction may only choose a kind the catalogue has. An input describing
something the catalogue lacks yields a `Question`, not a guess.

### Implementation guidelines
- Load a bundle once; readers never re-open a file another reader already parsed.
- IR values are stored in SI with the original value and unit kept in the trace, so a reviewer
  can see what was converted.
- Element ids are **derived deterministically** from canonical tags (`ids.py`), never chosen
  by the LLM, so naming is stable across runs.
- Sort every collection that reaches an output by id.
- Every entry point reconfigures stdout and stderr to UTF-8 with `errors="replace"`.
- Every external tool call has a timeout and returns a structured result
  (`ok`, `stdout`, `stderr`, `command`), never raises for a tool-reported error.

## Technology Stack
- language : Python 3.12
- IR / validation : Pydantic v2
- templating : Jinja2 (`StrictUndefined`, so a missing field fails loudly)
- LLM : OpenAI API, structured outputs, temperature 0, on-disk response cache
- document readers : `pypdf` / `pdfplumber`, `python-docx`, `openpyxl`, stdlib `email`, `json`, `csv`
- simulation : OpenModelica `omc`, Modelica Standard Library 4.x
- SysML v2 : the validator chosen in phase 1 (candidate: OMG SysML v2 Pilot Implementation)
- plotting : matplotlib
- CLI : `typer` or `argparse`, with `rich` for progress
- unit test framework : `pytest`

## Technology stack specific instructions for code generation
- **OpenAI structured outputs in strict mode** require every property to be listed as required
  and `additionalProperties: false`. Model an optional field as `X | None` with no default in
  the schema sent to the API, not as a missing key.
- **`omc` reports most errors through `getErrorString()`, not the exit code.** Call it after
  every `loadModel`, `loadFile`, `checkModel` and `simulate`, and treat non-empty error text
  as failure.
- `omc` needs `loadModel(Modelica)` before any MSL class resolves. Pin the MSL version
  in the `.mos` script.
- Modelica `when` clauses fire on the rising edge of their condition; a `when` inside an
  `algorithm` section with several branches must use `elsewhen`, not independent `when`s,
  when the branches assign the same variable.
- In Modelica, `==` on `Real` is not allowed in conditions; threshold comparisons are `>=` / `<=`,
  which is also what the L1 design note requires.
- SysML v2 textual: attribute values with units need the ISQ/SI libraries imported
  (`private import ISQ::*; private import SI::*;`). Confirm every construct the templates use
  against the phase 1 validator before relying on it — do not trust memory of the syntax.
- Jinja2 whitespace control (`{%-` / `-%}`) matters in generated Modelica; test templates
  against the golden IR with a byte-exact snapshot.

## Design Documents
- `docs/design/sourcemap.md` : list of source files, their phase and purpose. Use it to decide
  which files to modify for planning, code generation, bug fixes and features.
- `docs/design/ADR.md` : the decisions behind this document, with their reasons.
- `docs/specifications/specindex.md` : index of the specifications.
- `docs/implementation_plan.md` : the phase-wise delivery sequence.
