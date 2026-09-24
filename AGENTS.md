# SpecAlive Agent Guide

## Objective
Turn a bundle of messy engineering inputs — prose, PDFs, spreadsheets, emails, diagrams,
legacy models — into a **structured system model**, a **SysML v2 textual model** and a
**Modelica model that compiles and simulates**, with every element traced to the input that
justified it or to a declared assumption.

This is the System Modelling track of the AI in Engineering hackathon. The problem statement
is `CCTech Millinium_Hackathon_PRD_System_Modelling_V1.2.pdf`; how it is judged is
`AI-in-Engineering-Hackathon-Participant-Briefing (1).pdf`. Both sit in the project root and
outrank anything written here.

Delivery is phased. **One phase is one specification is one pull request.** Within a track,
do not start the next phase until the previous one is fully implemented and the user
explicitly asks for it.

## Working Rules
Read `.claude/workingrules.md` and strictly follow the rules.

## Team and ownership
Three people: Arthesh, Parth and Yasmeen. **Task ownership lives in
`SpecAlive_Task_Plan.xlsx`, column `Owner`** — not in these documents, so it is changed in
one place. Every task there carries its phase and its specification document.

Work runs in three parallel tracks once phase 2 has landed:

| Track | Phases | Scope |
|---|---|---|
| A | 3, 4 | Inputs → evidence → IR |
| B | 5, 6 | IR → SysML v2, IR → Modelica, compile loop |
| C | 7, 8, 9 | Simulate, verify, report, CLI, end to end |

Phases 1 and 2 are shared and come first. Phase 10 is stretch.

## Project Folder Map
Create a folder only when a phase actually delivers into it.

- `.claude/` : coding agent configuration.
  - `.claude/workingrules.md` : the working rules. **Tracked** — it is evidence of how the
    team directs AI, which the briefing scores.
  - `.claude/memory/`, `.claude/settings.local.json` : **gitignored**.
- `specalive/` : the one application package. Layered, acyclic, and the layers are
  **directories**, so a dependency's direction is visible in its import path and checkable
  by grep.
  - `config.py` : top level. Every layer reads it; it reads nothing.
  - `core/` : the IR schema and the component catalogue loader. Imports nothing else in the
    package.
  - `llm/` : the OpenAI client, structured outputs, response cache.
  - `ingest/` : file readers and source classification. Produces evidence, never IR.
  - `extract/` : evidence → IR. Extraction, entity resolution, precedence, assumptions.
  - `generate/` : IR → SysML v2 and IR → Modelica. **Deterministic. Imports no `llm/`.**
  - `toolchain/` : wrappers around external tools — `omc`, the SysML v2 validator.
  - `repair/` : the compile-and-repair loop. The only place generated code meets the LLM.
  - `verify/` : simulation results against references and acceptance criteria; coverage.
  - `report/` : summary, traceability, assumptions, correspondence, plots.
  - `cli.py` : the command line entry point, at the top.
- `catalogue/` : the component catalogue (data, not code).
- `tests/` : `pytest`. `tests/goldens/` holds hand-written golden IRs — **test data only**.
- `docs/` : project documentation
  - `docs/devenv.md` : development environment setup
  - `docs/implementation_plan.md` : phases, tracks, settled decisions, blanks to fill
  - `docs/specifications/` : `FR-01` … `FR-12`
  - `docs/specifications/specindex.md` : index of specifications — **read this first, and
    do not load every specification every time**
  - `docs/design/ARCHITECTURE.md` : architecture rules and constraints
  - `docs/design/ADR.md` : architecture decision records, each with its reason
  - `docs/design/sourcemap.md` : index of source files, their phase and purpose
- `Testcases/` : the four supplied bundles, read-only input.
- `out/` : run outputs. Gitignored, rewritten by every run.
- Root files: `pyproject.toml`, `DECISIONS.md`, `AI-LOG.md`, `README.md`, `.gitignore`.

## Specification numbering
`FR-01` … `FR-10` map to phases 1 … 10. Two documents are **not** phases: `FR-11`
(non-functional and submission rules, binding on every phase) and `FR-12` (capability
deliberately not delivered).

## Required Reading Before making any Changes
- Read `.claude/workingrules.md`.
- Read your memories from `.claude/memory/`.
- Read `docs/implementation_plan.md` for the roadmap and the settled decisions.
- Read `docs/specifications/specindex.md`, then only the specification files you need.
- Read `docs/specifications/FR-11-nonfunctional-and-submission.md`. It binds **every** phase.
- Follow `docs/design/ARCHITECTURE.md` and the decisions in `docs/design/ADR.md`.
- Update `docs/design/sourcemap.md` when you add, remove or rename a source file.

## Non-negotiables
The rules that will cost the most if broken. `FR-11` holds the full set.

- **The IR is the single source of truth.** SysML and Modelica are both generated from it and
  never from each other or from the raw input. Generating them independently is the most
  common way to get silent divergence.
- **The LLM extracts; code generates.** `generate/` imports nothing from `llm/`. The LLM
  appears in `extract/` and `repair/` only.
- **No fabrication.** Every IR element carries a `TraceLink` to an input fragment or an
  `Assumption`. An element with neither is rejected, not emitted.
- **Contradictions are flagged, never silently resolved.** A resolution by precedence
  records a `Conflict` naming the losing value and why it lost. A conflict that precedence
  cannot settle becomes a `Question`.
- **Components come from the catalogue.** The LLM may choose a catalogue entry; it may not
  invent an MSL class name. An unmapped kind is reported, not guessed.
- **No case-specific logic in the pipeline.** Nothing under `specalive/` may mention a
  test-case tag, file name or value (`TK-101`, `RM-201`, `0.80`, `tank_sysmlv2…`). Golden
  IRs live in `tests/` and nothing in the package reads them. If a case-specific rule is ever
  unavoidable, declare it in `FR-11` — the PRD says judges will look.
- **The Modelica must compile.** `omc` `checkModel` is a hard gate, not a target. The repair
  loop may fix syntax and wiring; it may **not** change topology.
- **Repeatability.** Temperature 0, cached LLM responses, sorted iteration. The same input
  twice gives the same topology.
- **Reporting never fails the work.** Reconfigure stdout/stderr to UTF-8 with replacement in
  any entry point.
- **Never commit a secret.** `OPENAI_API_KEY` comes from the environment only.

## Verification
- `pytest` covers every layer. Generators are tested against the golden IRs, extraction
  against recorded (cached) LLM responses, so the suite runs offline.
- The end-to-end check is `specalive run` on the L1 Tank bundle, compared against its
  reference trace and acceptance criteria. Quote the numbers in the pull request.
- Every compile the pipeline claims must be reproducible by the command printed next to it.
  Judges run that command.

## Technology
Python 3.12. OpenAI API (structured outputs) for extraction and repair. Pydantic v2 for the
IR, Jinja2 for code generation. OpenModelica `omc` with the Modelica Standard Library 4.x.
SysML v2 validation with the tool chosen in phase 1. A command-line interface only.
