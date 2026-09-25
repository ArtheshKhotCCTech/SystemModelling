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
- Entries are planned until their phase lands; phase 1 files now exist. The phase that creates
  a file replaces its planned purpose with the real one if they differ. A file created that is
  not listed here must be added in the same pull request.

## Sourcemap Index

### Top level
| Source File | Phase | Purpose |
|---|---|---|
| `pyproject.toml` | 1, 5, 6 | Package metadata, runtime and `[dev]` dependencies, the `specalive` console script. Phase 5 adds `jinja2` and ships the generator templates as package data; phase 6 adds the Modelica component package files. |
| `specalive/__init__.py` | 1 | Package marker and `__version__`. |
| `specalive/config.py` | 1, 3 | Every setting in one immutable `Settings` built by `load_settings()`: model name, cache directory, omc path and MSL version, SysML validator folder and Java path, timeouts, repair attempt limit, token prices, the vision switch (3), API key (hidden from repr). The only module that reads environment variables. |
| `specalive/cli.py` | 1, 3, 4, 5, 6, 9 | Command-line entry point. Phase 1: argparse subcommands with the stages stubbed, `cache clear`, and `doctor` (four OK/FAIL toolchain checks). Phase 3: `ingest` writes `evidence.json`, lists every source not fully read, exits 2 on an input problem. Phase 4: `extract` (`-i`, `--text`, `--text-file`) writes `ir.json` and `extract_report.json`, exits 2 on an input problem and 3 on an LLM problem. Phase 5: `generate --ir --only sysml` writes `model.sysml` (exit 2 on a bad IR); `compile --only sysml` writes `sysml_validation.json` and prints the validator command (exit 1 on errors, 2 without a model, 3 when the validator did not run); Phase 6: `generate` writes `model.mo` too (`--only` picks one), prints the generator's notes and exits 2 on a generation error; `compile --only modelica` runs the repair loop, prints the status, errors and the omc command, and exits 0 ok/repaired, 1 FAILED, 2 without a model, 3 NOT RUN; without `--only` both run and the worst exit code wins. Phase 9 wires the real pipeline, progress output and graceful failure. |
| `DECISIONS.md` | 1 | Daily decision log, written by the team. Phase 1 creates the header only. |
| `AI-LOG.md` | 1 | Where AI output was overridden or discarded, written by the team. Phase 1 creates the header only. |
| `README.md` | 1, 9 | Setup, the `run` command, **the command that compiles the committed model**, output layout. Phase 9 completes it. |
| `.gitignore` | 1 | Excludes run outputs, the LLM cache, the virtual environment, environment scripts and agent memory. |
| `docs/ir.schema.json` | 2 | JSON Schema exported from `core/ir.py`; regenerated and checked by a test. |

### `core/` — the contract
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/core/__init__.py` | 2 | Layer marker for the contract layer. |
| `specalive/core/ir.py` | 2 | The Pydantic IR: parts, ports, connections, parameters, state machines (events, timers, `history` resume target), requirements, acceptance criteria with checks, and the honesty records (TraceLink, Assumption, Question, Conflict). A `SystemModel` validator enforces trace-or-assumption and resolves every cross-reference; guards, actions and check conditions are parsed by a small expression language over IR ids. `python -m specalive.core.ir` prints the JSON Schema. |
| `specalive/core/catalogue.py` | 2 | Loads and validates `catalogue/components.yaml` at load (connectors, required attributes, defaults with assumption text); answers "which SysML def, which Modelica class, which connector names" for an IR kind; `check_model` reports parts whose kind or port role the catalogue lacks. |
| `specalive/core/units.py` | 2 | Explicit unit table to SI (scale and offset). An unknown unit raises `UnknownUnit`, never guessed. |
| `specalive/core/ids.py` | 2, 5 | Deterministic element ids from canonical tags, legal in Modelica and SysML; `IdRegistry` refuses two tags collapsing onto one id. Phase 5: `sysml_name()` writes a reserved or illegal name as a quoted SysML name (FR-05 requirement 6). |
| `catalogue/components.yaml` | 2 | The component catalogue: IR kind → SysML part def and port defs, Modelica class and its source (MSL, SpecAlive component, generated), parameter and connector mappings, required attributes, defaults with assumption text. Phase 2 covers the seven L1 kinds. |

### `llm/`
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/llm/__init__.py` | 1 | Layer marker for the LLM layer. |
| `specalive/llm/client.py` | 1, 3 | OpenAI wrapper: strict structured outputs from Pydantic models, temperature 0, cache-first, token and cost logging, `LLMError` with request id; `openai` imported lazily. Phase 3: optional image input for vision, its hash part of the cache key. |
| `specalive/llm/cache.py` | 1 | On-disk response cache keyed by model, prompt and input hash; makes runs repeatable and tests offline. |

### `ingest/` — inputs to evidence
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/ingest/__init__.py` | 3 | Layer marker for the ingest layer. |
| `specalive/ingest/evidence.py` | 3 | `Source` (path, format, read status with reason, role, revision, date, reliability, document number and status, how it was classified and the index row that says so), `EvidenceChunk` (source id, locator, text, kind, role, header -> value `fields` for table rows) and `EvidenceBundle`, which rejects duplicate sources and chunks of unknown sources. |
| `specalive/ingest/classify.py` | 3 | Role, revision, date and reliability per source: a source-index table recognised by its columns (traced to its row), then the document's own title and header fields, then the format default, then the LLM only when every rule finds nothing. Register rows get their sheet's role (change log, requirements, verification) from its columns. |
| `specalive/ingest/ingest.py` | 3 | The stage: walks a bundle in sorted path order (or one file), makes `src_` ids from paths, reads and classifies every file, and writes a deterministic `evidence.json`. |
| `specalive/ingest/readers/__init__.py` | 3 | Reader registry: format by extension, else by content sniffing; any reader exception becomes an `unread` source with the reason. |
| `specalive/ingest/readers/_common.py` | 3 | `ReadContext`, `ReadResult`, chunking under a size cap at line boundaries, table-row rendering with headers, header and email date parsing. |
| `specalive/ingest/readers/pdf.py` | 3 | PDF text layer per page, cut at numbered headings and id-led items, located by page and line; no text layer is unread, failed pages partial. |
| `specalive/ingest/readers/docx.py` | 3 | Word body in order: paragraphs with their section, table rows keyed by headers (two-column tables as key: value), page headers; embedded images reported. |
| `specalive/ingest/readers/xlsx.py` | 3 | Every sheet; header row found by shape, each row a chunk naming sheet, row and headers; formulas with no cached value reported. |
| `specalive/ingest/readers/eml.py` | 3 | Email thread split into messages at separators, "wrote:" lines and `>` quotes, each with sender and date, decoded, newest first by parsed date. |
| `specalive/ingest/readers/text.py` | 3 | Plain text as line-ranged paragraphs; Markdown headings, list items, paragraphs and table rows with their section. |
| `specalive/ingest/readers/modelica.py` | 3 | Modelica as `code` blocks with line ranges, comments kept; also the shared code reader. |
| `specalive/ingest/readers/puml.py` | 3 | PlantUML as `code` blocks, comments kept. |
| `specalive/ingest/readers/json_.py` | 3 | JSON entries as chunks addressed by JSON path, split further until quotable. |
| `specalive/ingest/readers/csv_.py` | 3 | CSV summarised: header, row count, time span, per-column statistics or distinct values; never inlined. |
| `specalive/ingest/readers/image.py` | 3 | Images to the vision model as `diagram_text` (partial, not verbatim) when `SPECALIVE_VISION` is on; otherwise unread with the reason. |

### `extract/` — evidence to IR
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/extract/__init__.py` | 4 | Layer marker for the extract layer. |
| `specalive/extract/fragments.py` | 4 | The LLM's structured-output schemas (part, connection, parameter, requirement, criterion, document, alias and assumption fragments; the behaviour reply), each with chunk id and verbatim quote; `Found` (a verified fragment with its location and chunk role), `Draft` (the IR under construction), `ExtractReport`, and `name_key`. |
| `specalive/extract/extract.py` | 4 | The stage: per-source structure passes in a fixed role order over size-capped batches, a glossary handed to later passes, verbatim quote checking (unverified fragments discarded and counted), a behaviour pass per controller validated item by item against the IR expression language, then merge, precedence, gaps and the honesty gate; `run_extract`, `extract_text`, `write_ir`. |
| `specalive/extract/merge.py` | 4 | Entity resolution: union-find over name keys (same tag, names given together, alias tables), look-alike names merged only with an Assumption; deterministic part ids, catalogue ports, aliases and trace union; connections resolved through aliases, controller ports made from them; evidence to IR source mapping. |
| `specalive/extract/precedence.py` | 4 | The ADR ladder by source role (a register row takes its cited record's rank); evidence status columns first, approval over recency, later date within a rank; winner effective, losers superseded, a Conflict naming every candidate; configuration variants kept without conflict; ties and provisional winners become Questions; document registry and cited-record sources. |
| `specalive/extract/gaps.py` | 4 | Explicit convention rules and catalogue defaults, each with a declared Assumption; Questions for required values with no default; source-stated simplifications as traced Assumptions; missing documents; the honesty gate that removes untraced elements, cascading, and never adds a trace. |
| `specalive/extract/text_input.py` | 4 | Plain-text input path: a paragraph or text file becomes a one-source `requirement_spec` evidence bundle chunked like the text reader, then runs through the same extraction. |
| `specalive/extract/questions.py` | 4 (stretch) | Interactive clarifying questions; answers are recorded as evidence with their own trace. |

### `generate/` — IR to models (no LLM)
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/generate/__init__.py` | 5 | Layer marker for the generate layer; imports config and core only, never the LLM. |
| `specalive/generate/sysml.py` | 5 | IR + catalogue to SysML v2 text, deterministic and LLM-free: a sorted view model (effective values only, units to ISQ types from a validated table, guards translated from the IR expression tree, IR events/timers/actions as attribute, calc and action defs, IR history as a documented state, regions as parallel states, the machine exhibited on its owner with bindings to real ports and attributes, satisfy paths), a `doc` per element with IR id, primary source and ASSUMPTION marks, rendered by StrictUndefined Jinja2 templates. `load_ir`, `render_sysml`, `write_sysml`. |
| `specalive/generate/templates/sysml/*` | 5 | SysML v2 templates, layout only: `package.sysml.j2` and one partial each for the behaviour library, port defs, part defs, events, state defs (flat or parallel), requirements and the system part. |
| `specalive/generate/modelica.py` | 6 | IR + catalogue to one Modelica package, deterministic and LLM-free: only the SpecAlive component classes used, one controller class per state machine, and `System` with one top-level parameter per effective or verification-only IR value (superseded never), one instance per part of the catalogue class with parameters bound by IR id (a catalogue default only with an ASSUMPTION comment), one `connect()` per connection, `[IR id]` description strings, ASSUMPTION comments, and the experiment annotation from `stop_time`/`start_time`/`output_interval` with declared generator defaults. Returns the text, model name and notes; `render_modelica`, `write_modelica`. |
| `specalive/generate/modelica_text.py` | 6 | Modelica lexical rules shared by the generators and the repair loop: keywords, legal names (keyword + `_`), package names, escaped string literals, numbers, and `ModelicaGenerationError`. |
| `specalive/generate/controller.py` | 6 | One IR state machine as a Modelica controller class: an enumeration literal per state, one `when` over command edges and `pre(state) == S and guard` conditions whose body checks transitions in IR priority order, a deadline and remaining time per timer (frozen by `save_history`, restored on a history return), outputs as equations over the state, and window-free `always` acceptance criteria as asserts. Knows no event names; refuses parallel regions, `==` on Reals and reads outside its owner. |
| `specalive/generate/templates/modelica/*` | 6 | `package.mo.j2` (package, SpecAlive library, controllers, System) and `controller.mo.j2`, layout only; `components/*.mo`: the SpecAlive component package — causal volume-flow and signal `Interfaces`, `Tank` (der(h) = (q_in - q_out)/A), `OnOffValve` (ideal constant-flow switch), `CommandButton` (one pulse per press time), `FluidSource`, `FluidSink`. |

### `toolchain/` — external tools
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/toolchain/__init__.py` | 1 | Layer marker for the external-tool layer. |
| `specalive/toolchain/process.py` | 1 | The one subprocess runner: timeout, UTF-8 decoding, structured `ToolResult` (`ok`, `command`, `stdout`, `stderr`, `duration`, `returncode`) and `ProbeResult`; never raises for a tool failure. |
| `specalive/toolchain/omc.py` | 1, 6, 7 | Runs `omc` scripts: probe (1); compile (6) — `compile.mos` loading the pinned MSL and one file, `checkModel` and `buildModel` with `getErrorString()` after each, omc messages parsed with file, line and column, a verdict ok / failed / NOT RUN and the `cd <build> && omc compile.mos` command that reproduces it; simulate (7). |
| `specalive/toolchain/sysml_validate.py` | 1, 5 | Drives the SysML v2 Pilot Implementation's interactive shell over stdin and parses its `ERROR:`/`WARNING:` lines into issues with line and column: probe and `validate_text`/`validate_file` (1). Phase 5: a verdict is `ok`, `failed` or `NOT RUN` (R-SYS-6); `write_report` writes `sysml_validation.json` with issues and the reproducing command; the root echo is found after a warning too. |

### `repair/`
| Source File | Phase | Purpose |
|---|---|---|
| `specalive/repair/__init__.py` | 6 | Layer marker for the repair layer. |
| `specalive/repair/compile_loop.py` | 6 | The compile-and-repair loop: compile; deterministic fixes keyed on omc's message (missing import, keyword as a name, unit spelling); then up to `repair_attempts` LLM repairs with a structured reply. Every candidate is checked against the original topology (instances by class and IR id, connect pairs by IR id, so renames hold) and rejected if it differs. Writes `attempts/*.mo`, `repair_log.json` (errors, diff, kind, topology, result per attempt), `compile.log` and `model.repaired.mo`, which is compiled once more so the printed command reproduces it. |

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
| `tests/fixtures/ingest/two_pages.pdf`, `corrupt.pdf` | 3 | A minimal two-page PDF with a text layer, and a broken one, for the PDF reader and the unread path. |
| `tests/fixtures/extract_cache/*` | 4 | Recorded LLM responses for the L1 bundle and the adversarial text spec, so FR-04 acceptance runs offline. Re-recorded, never hand-edited, after a prompt change. |
| `tests/fixtures/sysml/*` | 5 | One minimal validated example per SysML construct the templates use (`R-SYS-5`): `port_defs`, `part_def_attributes`, `units`, `connection`, `requirement_satisfy`, `state_machine`, `parallel_regions`. |
| `tests/fixtures/snapshots/L1_tank.mo` | 6 | Byte-exact snapshot of the Modelica generated from the golden L1 IR (FR-11 item 16). Regenerated deliberately and reviewed, never hand-edited. |
| `tests/fixtures/snapshots/L1_tank.sysml` | 5 | Byte-exact snapshot of the SysML generated from the golden L1 IR (FR-11 item 16). Regenerated deliberately and reviewed, never hand-edited. |
| `tests/goldens/L1_tank.ir.json` | 2 | Hand-written reference IR for L1. Fixture for the generators and the reference for coverage. Never read by `specalive/`. |
| `tests/goldens/L2_co2.ir.json` | 10 | Hand-written reference IR for L2. |
| `tests/adversarial/*` | 4, 9 | Unseen specs for generalisation and graceful-failure testing. Phase 4 adds `one_paragraph_spec.txt` (FR-04 acceptance 6); phase 9 completes the set. |
| `tests/test_*.py` | each | Unit tests for the phase's modules. |
| `tests/test_config.py` | 1 | Settings defaults, environment overrides, bad values, immutability, key never in repr. |
| `tests/test_llm_cache.py` | 1 | Cache key components (R-FND-5), round trip, corrupt entries, clear. |
| `tests/test_llm_client.py` | 1 | Client with the network mocked: strict schema, temperature 0, one call for two identical requests, `LLMError` cases, cost logging, key never cached. |
| `tests/test_toolchain.py` | 1, 5, 6 | `run_tool` timeouts and failures as data; omc and Pilot output parsing; real-tool probes, skipped with a reason when a tool is absent. Phase 6: the compile script, omc message parsing and compile verdicts. |
| `tests/test_cli.py` | 1, 5, 6 | Subcommand list, stub exit codes, `cache clear`, `doctor` output and exit code, key never shown. Phase 5: `generate` and `compile --only sysml` outputs and exit codes. Phase 6: `generate` writes `model.mo`; `compile --only modelica` statuses and exit codes; both models by default. |
| `tests/test_rules.py` | 1 | Structural rules as tests: import without a key, only `config` reads the environment, the layer import table, nothing imports `cli`, no case-specific values. |
| `tests/test_ids.py` | 2, 5 | Tag normalisation, determinism, reserved-word and leading-digit prefixes, registry collisions; `sysml_name` quoting (5). |
| `tests/test_units.py` | 2 | Every benchmark unit to SI, spelling variants, lists, `UnknownUnit`. |
| `tests/test_ir.py` | 2 | IR contract on a small model: trace-or-assumption, dangling references, SI units, one effective value, expression language, state-machine rules. |
| `tests/test_catalogue.py` | 2 | Shipped catalogue covers L1 and loads; each broken-entry case fails at load naming the kind; `check_model`. |
| `tests/test_ingest_readers.py` | 3 | Each reader on small fixtures: locators, kinds, headers kept, email split and order, CSV summary, image with vision off and on, broken files unread. |
| `tests/test_ingest_classify.py` | 3 | Keyword and header rules, index-row parsing, index recognised by columns and traced, fallbacks down to the LLM, register sheet roles. |
| `tests/test_ingest_pipeline.py` | 3 | Scratch bundles: every file a Source, deterministic ids and order, corrupt file isolated, byte-identical `evidence.json`, evidence model validation. |
| `tests/test_ingest_bundles.py` | 3 | FR-03 acceptance 1-5 on the four `Testcases/` bundles. |
| `tests/test_golden_l1.py` | 2 | FR-02 acceptance 1–5 on the L1 golden IR, its effective values, states, criteria and conflicts, and verbatim plain-text quotes. |
| `tests/_extract_support.py` | 4 | Shared phase 4 test builders: small evidence bundles, `Found` fragments without an LLM, and `FakeLLM`, which serves canned replies by schema and records its calls. |
| `tests/test_extract_passes.py` | 4 | Chunk ids, fixed pass order, batching, quote verification (acceptance 8), chunk roles, catalogue in the prompt, the glossary, and the behaviour pass discarding invalid items. |
| `tests/test_extract_merge.py` | 4 | Alias unification, look-alike merges only with an Assumption, unknown kinds as Questions, kind conflicts, catalogue and controller ports, connection resolution, IR source mapping. |
| `tests/test_extract_precedence.py` | 4 | The ladder, cited-record ranks, evidence status first, approval over recency, losers kept and named, variants, ties and provisional values as Questions, units and value parsing, requirements. |
| `tests/test_extract_gaps.py` | 4 | Catalogue defaults with assumptions, Questions for missing required values, conventions, stated assumptions, missing documents, the honesty gate. |
| `tests/test_extract_text.py` | 4 | Plain text as a one-source bundle through the same extraction path. |
| `tests/test_extract_stage.py` | 4 | `run_extract` on a scratch bundle, byte-identical `ir.json` (acceptance 7), and the `extract` CLI contract and exit codes. |
| `tests/test_generate_sysml.py` | 5 | FR-05 acceptance 1-6 on the golden L1 IR (element types, one doc id per element, snapshot, effective values only, ASSUMPTION marks, no `llm` import, dangling port fails first) and small IRs for escaping, regions, history, list values and error paths; real-validator runs on every fixture and model. |
| `tests/_modelica_support.py` | 6 | Shared phase 6 builders: a small complete plant IR with a timer, pause and history resume; the golden L1 IR; the omc skip marker; `simulate_values`, which reads variables at given times from an omc simulation. |
| `tests/test_generate_modelica.py` | 6 | FR-06 acceptance 1, 3, 4, 6 on the golden L1 IR (catalogue classes, one `[IR id]` per part and connection, bound parameters, effective and verification-only values only, ASSUMPTION comments, experiment, snapshot, real omc compile) and small IRs for defaults, escaping, keyword names and error paths. |
| `tests/test_generate_controller.py` | 6 | FR-06 acceptance 2 and requirements 8-9: nine states, initial state, one when-clause, priority order, event edges, timer freeze and restore, history, outputs, invariant asserts, no command names in the generator; refusals; an omc simulation of pause and resume. |
| `tests/test_compile_loop.py` | 6 | FR-06 acceptance 5 and requirements 11-14: topology by IR id, each deterministic fix, the loop against a scripted compiler and LLM (clean, fixed, rejected LLM repair, exhaustion, LLM failure, NOT RUN), and a real omc repair of a missing import. |
| `tests/test_extract_l1.py` | 4 | FR-04 acceptance 1-7 on L1 and the text spec from recorded responses, including coverage against the golden IR. |
