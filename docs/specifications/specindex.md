# Index of Specification Documents

This is the index of specification documents for the SpecAlive project.

The index format is
- `<relative document path>` : {{short 2-3 lines description of document content}}

## How to use this file
- Use this file to determine which specification documents to load.
- Do not load all specification documents every time.
- Update the index whenever you add a new specification document.

## Overview
SpecAlive turns mixed, messy engineering inputs into a traced IR, a SysML v2 model and a
Modelica model that compiles and simulates. The problem statement is the PRD in the project
root; the scoring is the participant briefing beside it. Both outrank these documents.

**One specification is one phase.** `FR-01` … `FR-10` map to phases 1 … 10 of
`../implementation_plan.md`. Two documents are **not** phases: `FR-11` (non-functional and
submission rules, binding on every phase) and `FR-12` (capability deliberately not delivered).

Each specification has the same shape: purpose, modules, requirements, acceptance, rules.
Rule ids (`R-IR-3`, `R-EXT-5` …) are stable handles for commit messages and review comments;
never renumber them. Task ids (`T1.1`, `A5` …) refer to `../../SpecAlive_Task_Plan.xlsx`, which
also holds the owners.

## Specifications Index

### Shared
- `./FR-01-foundation.md` : Phase 1. Package skeleton, config, CLI stubs, OpenAI client with
  response cache, and the day-1 toolchain proof: `omc` + MSL and the SysML v2 validator.
- `./FR-02-ir-and-catalogue.md` : Phase 2. The IR schema, the component catalogue, deterministic
  ids and units, and the hand-written golden IR for L1. The contract between all three tracks.

### Track A — inputs to IR
- `./FR-03-evidence-ingestion.md` : Phase 3. One reader per file format, producing located
  evidence chunks; source role, revision and reliability classification.
- `./FR-04-extraction-and-resolution.md` : Phase 4. LLM extraction into IR fragments, alias
  merging, the precedence ladder, conflicts, assumptions, questions and the honesty gate. Also
  the plain-text input path.

### Track B — IR to models
- `./FR-05-sysml-generation.md` : Phase 5. Deterministic SysML v2 textual generation from the IR
  and validation with the phase 1 tool.
- `./FR-06-modelica-generation.md` : Phase 6. Deterministic Modelica generation, the controller
  state machine, and the compile-and-repair loop. Carries the project's hard gate.

### Track C — verification and product
- `./FR-07-simulation-and-verification.md` : Phase 7. Simulation, comparison against a reference
  trace, acceptance criteria as executable checks, structural coverage and repeatability.
- `./FR-08-reports-and-traceability.md` : Phase 8. One-minute summary, traceability, assumptions
  and conflicts, the IR ↔ SysML ↔ Modelica correspondence table, plots.
- `./FR-09-cli-and-end-to-end.md` : Phase 9. The real pipeline behind `specalive run`, progress,
  output layout, graceful failure, and the adversarial spec set.

### Stretch
- `./FR-10-l2-feedback-extension.md` : Phase 10. Continuous closed-loop control, proven on L2
  Room CO2. The first test of whether the architecture generalises beyond L1.

### Not phases
- `./FR-11-nonfunctional-and-submission.md` : Determinism, honesty, traceability, generalisation,
  error handling, testing, logging, secrets, speed; plus the submission and process rules
  (`DECISIONS.md`, `AI-LOG.md`, deck, demo) and the definition of done. Follow it in all phases.
- `./FR-12-not-delivered.md` : L3 Magnetic Circuit, L4 NaCl Evaporation, web UI, round-trip
  editing and other PRD extensions this project does not ship, with what would re-enable each.
