# Implementation Plan

This document describes the phase-wise implementation plan for SpecAlive: an agentic
pipeline from mixed engineering inputs to a traced IR, a SysML v2 model and a compiling,
simulating Modelica model.

## Phase Implementation sequence
- **One phase is one specification is one pull request.** `FR-01` … `FR-10` map to phases
  1 … 10. `FR-11` is cross-cutting and is not a phase; `FR-12` records what is not delivered.
- Follow `specifications/FR-11-nonfunctional-and-submission.md` in all phases.
- Phases 1 and 2 are **shared and sequential**. Nothing else starts until phase 2 has landed,
  because the IR schema is the contract every track codes against.
- After phase 2, **three tracks run in parallel**. Within a track, do not start the next
  phase until the previous one is fully implemented and the user explicitly asks for it.
- Task-level detail — IDs, estimates, dependencies, **owners** — is in
  `../SpecAlive_Task_Plan.xlsx`. The task IDs below refer to that sheet.

```
                    ┌─ Track A:  Phase 3 ─► Phase 4 ─┐
Phase 1 ─► Phase 2 ─┼─ Track B:  Phase 5 ,  Phase 6 ─┼─► Phase 9 ─► (Phase 10)
                    └─ Track C:  Phase 7 ─► Phase 8 ─┘
```

Track B's phases 5 and 6 depend only on phase 2 and can run side by side if the track has
the hands. Phase 8 needs the outputs of phases 5, 6 and 7 to report on, but can be built
against golden-IR outputs before those phases finish.

## Target timeline
Sized for 2–3 part-time days. Must-have work is about 59 hours of manual effort; see the
task sheet for the per-phase split.

| Day | Work |
|---|---|
| Day 1 | Phase 1 (toolchain settled), phase 2 (IR frozen, golden L1 IR written). Start phases 3 and 7. |
| Day 2 | Tracks A, B, C in parallel against the golden IR. |
| Day 3 | Phase 9: integrate on L1, adversarial specs, demo rehearsal. Phase 10 only if time allows. |

## Decoupling the tracks
The golden IR for L1 Tank (phase 2) is what lets the tracks run in parallel. Track B
generates from it and Track C verifies what Track B produced from it — neither waits for
Track A's extraction to work. Track A is then measured by how close its extracted IR comes to
the golden one (phase 7's coverage check).

The golden IR is **test data**. It lives under `tests/goldens/`, and nothing in `specalive/`
may read it. See `specifications/FR-11-nonfunctional-and-submission.md`.

---

## Shared

### Phase 1 — Foundation
1. Implements `specifications/FR-01-foundation.md`. Tasks T0.1–T0.4.
2. Delivers the package skeleton, `config.py`, the CLI entry point with its subcommands
   stubbed, the OpenAI client with its response cache, the toolchain probes, `pyproject.toml`,
   `DECISIONS.md` and `AI-LOG.md` (headers only — the entries are the team's).
3. **Settles the two highest-risk unknowns first**: that `omc` compiles and simulates an MSL
   example from a script, and which SysML v2 validator parses a model from the command line.
   Tool friction is what the briefing says sinks teams in this domain.

### Phase 2 — IR schema, catalogue and golden IR
1. Implements `specifications/FR-02-ir-and-catalogue.md`. Tasks T1.1, T1.2, T1.4.
2. Delivers `core/ir.py`, `core/catalogue.py`, `catalogue/components.yaml`,
   `tests/goldens/L1_tank.ir.json`, and the exported JSON Schema.
3. **All three owners sign off the schema.** After this lands, a schema change is a
   cross-track change and needs all three again.

---

## Track A — Inputs to IR

### Phase 3 — Evidence ingestion
1. Implements `specifications/FR-03-evidence-ingestion.md`. Tasks A1, A2.
2. Delivers `ingest/readers/*`, `ingest/classify.py`, `ingest/evidence.py`.
3. Produces evidence, never IR. Every reader must say what it could not read.

### Phase 4 — Extraction and resolution
1. Implements `specifications/FR-04-extraction-and-resolution.md`. Tasks A3–A6, A8; A7 is
   stretch.
2. Delivers `extract/extract.py`, `extract/merge.py`, `extract/precedence.py`,
   `extract/gaps.py`, `extract/text_input.py`.
3. This is where the honesty requirements live. The pull request must show the L1 conflicts
   it found (effective T1 high level, the two changed waits) and the assumptions it made.

---

## Track B — IR to models

### Phase 5 — SysML v2 generation
1. Implements `specifications/FR-05-sysml-generation.md`. Tasks B1, B2.
2. Delivers `generate/sysml.py`, `generate/templates/sysml/*`, `toolchain/sysml_validate.py`.

### Phase 6 — Modelica generation and compile loop
1. Implements `specifications/FR-06-modelica-generation.md`. Tasks B3, B4, B5.
2. Delivers `generate/modelica.py`, `generate/controller.py`, `generate/templates/modelica/*`,
   `toolchain/omc.py`, `repair/compile_loop.py`.
3. **The hard gate of the whole project.** The generated model compiles under `omc`, and the
   command that proves it is printed and reproducible.

---

## Track C — Verification and product

### Phase 7 — Simulation and verification
1. Implements `specifications/FR-07-simulation-and-verification.md`. Tasks C1, C2, C3.
2. Delivers `toolchain/omc.py` simulate support (shared with phase 6 — coordinate),
   `verify/simulate.py`, `verify/compare.py`, `verify/acceptance.py`, `verify/coverage.py`.
3. Can start on day 1 against an MSL example model, before Track B produces anything.

### Phase 8 — Reports and traceability
1. Implements `specifications/FR-08-reports-and-traceability.md`. Tasks C4, B6.
2. Delivers `report/summary.py`, `report/traceability.py`, `report/assumptions.py`,
   `report/correspondence.py`, `report/plots.py`.
3. B6 (the IR ↔ SysML ↔ Modelica correspondence table) is Track B's knowledge but Track C's
   report; the owner in the task sheet decides who writes it.

### Phase 9 — CLI and end to end
1. Implements `specifications/FR-09-cli-and-end-to-end.md`. Tasks C5, C6.
2. Delivers the real `cli.py` pipeline, progress reporting, the output layout, graceful
   failure, and the adversarial spec set under `tests/adversarial/`.
3. First phase that runs inputs to verified model with no hand-written IR in the loop.

---

## Stretch

### Phase 10 — L2 feedback extension
1. Implements `specifications/FR-10-l2-feedback-extension.md`. Tasks T1.3, B7.
2. Adds the continuous closed-loop pattern (sensor, gain, P controller, flow source, trace
   substance) to the catalogue and generators, proven on L2 Room CO2.
3. Only if phase 9 is done. It is the first test of whether the architecture generalises
   rather than fits L1.

---

## Process work (not a phase)
Tasks P1–P5, governed by `specifications/FR-11-nonfunctional-and-submission.md`:
`DECISIONS.md` every day, `AI-LOG.md` with at least two real overrides, a domain-expert
conversation with a recorded outcome, the architecture note, and the deck of at most eight slides.

## Settled decisions
Recorded with their reasons in `design/ADR.md`; listed here so they are not re-litigated.

1. **Scope: L1 Tank end to end first.** L2 is stretch (phase 10); L3 and L4 are not
   delivered (`FR-12`). The PRD: one case solved end to end beats four solved partially.
2. **Interface: command line only.** Accepted cost: the PRD's SaaS preference and some
   design-thinking marks.
3. **LLM: OpenAI API**, structured outputs, temperature 0, with a response cache.
4. **Architecture: extract into a typed IR, then generate deterministically.**
5. **Language: Python 3.12.**

## Still to fill in
1. **Owners.** Column `Owner` of `SpecAlive_Task_Plan.xlsx` is empty. Fill it before
   phase 1 starts; the summary tab shows each person's load.
2. **SysML v2 validator.** Decided by the phase 1 spike (T0.3); record it in `ADR.md` and
   `DECISIONS.md`.
3. **OpenAI model name.** Pick one that supports structured outputs and vision; record it in
   `config.py` and `ADR.md`.
4. **Domain expert.** Who the team will talk to (P3), and when. Day 1 is best — the briefing
   scores a visible change resulting from that conversation.
5. **Hackathon dates.** The briefing's hard stop reads 23 Sep 2026. Confirm the team's actual
   deadline and demo slot.
