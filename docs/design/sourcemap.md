# Index of source code for the SpecAlive project

## index format
| Source File | Phase | Purpose |
|---|---|---|

## How to use this file
- Use this file to determine which source code file to load based on the "purpose" of the
  source code file.
- Do not load all source code documents every time.
- Update the index whenever you add, remove or rename a source code file.
- The **Phase** column is the phase of `../implementation_plan.md` that delivers the file.
- **Every entry below is planned; none exists yet.** The phase that creates a file replaces its
  planned purpose with the real one if they differ. A file created that is not listed here must
  be added in the same pull request.

## Sourcemap Index

### Top level
| Source File | Phase | Purpose |
|---|---|---|
| `pyproject.toml` | 1 | Package metadata, runtime and `[dev]` dependencies, the `specalive` console script. |
| `specalive/__init__.py` | 1 | Package marker and `__version__`. |
| `specalive/config.py` | 1 | Every setting in one place: model name, cache directory, tool paths, timeouts, repair attempt limit. Read by every layer; reads nothing. |
| `specalive/cli.py` | 1, 9 | Command-line entry point. Phase 1 stubs the subcommands; phase 9 wires the real pipeline, progress output and graceful failure. |
| `DECISIONS.md` | 1 | Daily decision log, written by the team. Phase 1 creates the header only. |
| `AI-LOG.md` | 1 | Where AI output was overridden or discarded, written by the team. Phase 1 creates the header only. |
| `README.md` | 1, 9 | Setup, the `run` command, **the command that compiles the committed model**, output layout. Phase 9 completes it. |
| `.gitignore` | 1 | Excludes run outputs, the LLM cache, the virtual environment, environment scripts and agent memory. |
| `docs/ir.schema.json` | 2 | JSON Schema exported from `core/ir.py`; regenerated and checked by a test. |

### `core/` — the contract
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/core/ir.py` | 2 | The Pydantic IR: parts, ports, connections, parameters, state machines, requirements, acceptance criteria, and the honesty records (TraceLink, Assumption, Question, Conflict). Single source of truth for both generated models. |
| `specalive/core/catalogue.py` | 2 | Loads and validates `catalogue/components.yaml`; answers "which SysML def, which Modelica class, which connector names" for an IR kind. |
| `specalive/core/units.py` | 2 | Explicit unit table to SI. An unknown unit is reported, never guessed. |
| `specalive/core/ids.py` | 2 | Deterministic element ids from canonical tags, so naming is stable across runs. |
| `catalogue/components.yaml` | 2 | The component catalogue: IR kind → SysML part def, Modelica class, parameters, port mapping. |

### `llm/`
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/llm/client.py` | 1 | OpenAI wrapper: structured outputs from Pydantic models, temperature 0, token and cost accounting. |
| `specalive/llm/cache.py` | 1 | On-disk response cache keyed by model, prompt and input hash; makes runs repeatable and tests offline. |

### `ingest/` — inputs to evidence
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/ingest/evidence.py` | 3 | `EvidenceChunk` and `EvidenceBundle`: text plus source, locator (page, sheet/row, section) and reliability. |
| `specalive/ingest/classify.py` | 3 | Infers each source's role (change record, review decision, spec, datasheet, legacy model, informal note, verification document), revision and date; uses a source-index table when the bundle has one. |
| `specalive/ingest/readers/*.py` | 3 | One reader per format: pdf, docx, xlsx, eml, text/markdown, Modelica, PlantUML, json, csv (header and statistics), image (vision or flagged unread). |

### `extract/` — evidence to IR
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/extract/extract.py` | 4 | LLM passes over evidence producing IR fragments, each with its supporting quote. |
| `specalive/extract/merge.py` | 4 | Entity resolution: unifies aliases (tag, short name, legacy name) into one element per real component. |
| `specalive/extract/precedence.py` | 4 | Ranks competing values by source authority, keeps the winner, records every loser as a Conflict; unrankable conflicts become Questions. |
| `specalive/extract/gaps.py` | 4 | Assumptions for implicit conventions and missing values, and the honesty gate that rejects untraced elements. |
| `specalive/extract/text_input.py` | 4 | Plain-text input path: a pasted paragraph becomes a one-chunk evidence bundle. |
| `specalive/extract/questions.py` | 4 (stretch) | Interactive clarifying questions; answers are recorded as evidence with their own trace. |

### `generate/` — IR to models (no LLM)
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/generate/sysml.py` | 5 | Renders the IR as SysML v2 textual notation through Jinja2 templates; carries IR ids and traces as documentation. |
| `specalive/generate/templates/sysml/*` | 5 | SysML v2 templates: package, part/port defs, connections, attributes, requirements, state machines. |
| `specalive/generate/modelica.py` | 6 | Renders the IR as a Modelica package: components from the catalogue, `connect()` equations, parameters, experiment annotation, IR ids in comments. |
| `specalive/generate/controller.py` | 6 | Renders an IR state machine as a Modelica enumeration state with timers, command priority and interlock assertions. |
| `specalive/generate/templates/modelica/*` | 6 | Modelica templates, including the lightweight SpecAlive component package. |

### `toolchain/` — external tools
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/toolchain/omc.py` | 1, 6, 7 | Runs `omc` scripts: probe (1), load/check/build (6), simulate (7). Returns structured results including the exact command. |
| `specalive/toolchain/sysml_validate.py` | 1, 5 | Runs the chosen SysML v2 validator: probe (1), validate a generated model (5). |

### `repair/`
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/repair/compile_loop.py` | 6 | Compile, parse errors, apply deterministic fixes, then at most three LLM repairs; rejects any repair that changes topology; logs every attempt. |

### `verify/`
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/verify/simulate.py` | 7 | Simulates a compiled model and loads the result as a table. |
| `specalive/verify/compare.py` | 7 | Maps result variables to a reference trace and compares values and event timing within tolerance. |
| `specalive/verify/acceptance.py` | 7 | Evaluates the IR's acceptance criteria against the simulation result; each is PASS, FAIL or NOT CHECKED with a reason. |
| `specalive/verify/coverage.py` | 7 | Structural coverage of an IR against a reference IR, and topology diff between two runs. |

### `report/`
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/report/summary.py` | 8 | The one-minute summary an engineer approves or rejects. |
| `specalive/report/traceability.py` | 8 | Element → source quote table. |
| `specalive/report/assumptions.py` | 8 | Assumptions, conflicts (with the losing value and why it lost) and open questions. |
| `specalive/report/correspondence.py` | 8 | IR id ↔ SysML element ↔ Modelica component table, proving the layers agree. |
| `specalive/report/plots.py` | 8 | Simulation trajectory plots, overlaid on the reference where one exists. |

### `tests/`
| Source File | Phase | Purpose |
|---|---|---|
| `tests/fixtures/probe.sysml` | 1 | Minimal SysML v2 model (part, port, connection, attribute with unit, state machine) that `specalive doctor` validates to prove the toolchain. |
| `tests/fixtures/sysml/*` | 5 | One minimal validated example per SysML construct the templates use (`R-SYS-5`). |
| `tests/goldens/L1_tank.ir.json` | 2 | Hand-written reference IR for L1. Fixture for the generators and the reference for coverage. Never read by `specalive/`. |
| `tests/goldens/L2_co2.ir.json` | 10 | Hand-written reference IR for L2. |
| `tests/adversarial/*` | 9 | Unseen specs for generalisation and graceful-failure testing. |
| `tests/test_*.py` | each | Unit tests for the phase's modules. |
