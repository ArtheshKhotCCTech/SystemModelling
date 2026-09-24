# Specification - Simulation and Verification

Delivered by **phase 7**, Track C. Tasks C1, C2, C3. Depends on phase 2; the simulation runner
can be built on day 1 against an MSL example, before Track B produces a model. Shares
`toolchain/omc.py` with phase 6 — agree the function signatures with its owner first.

## Purpose
Show that a compiling model is also a *right* one: it simulates, its trajectories agree with the
reference behaviour, its acceptance criteria pass, and its structure covers what the reference
says the system contains. The briefing: "Compiling is not the same as being right."

## Modules
1. `specalive/toolchain/omc.py` — `simulate()` added.
2. `specalive/verify/simulate.py` — run and load results.
3. `specalive/verify/compare.py` — reference trace comparison.
4. `specalive/verify/acceptance.py` — acceptance criteria as checks.
5. `specalive/verify/coverage.py` — structural coverage and repeatability.
6. CLI: `specalive verify --run out/<run> [--reference file.csv] [--golden ir.json]` writes
   `sim/result.csv`, `verification.json`, `coverage.json`.

## Requirements

### Simulation
1. Simulate with the experiment annotation's stop time and interval, CSV output. Timeout from
   `config.py`. A failed or timed-out simulation reports `FAILED` with `omc`'s message.
2. A simulation that ends early on an `assert` (an interlock) is a **FAIL of that interlock**,
   reported with the time and the assert message — not a crash.

### Reference comparison
3. The reference trace is the CSV the ingestion stage found with role `reference_data`, or one
   given by `--reference`.
4. **Variable mapping** from reference columns to model variables is built from the IR (each
   reference column is matched to an IR element by name, tag or unit) and written into
   `verification.json`, so a reviewer can see what was compared with what. An unmapped column is
   listed as `NOT COMPARED`, not dropped.
5. Comparisons:
   - continuous signals: max absolute and relative error over the common time span, and at the
     reference's sample times;
   - discrete/boolean signals and states: the times at which they change, matched in order,
     within a tolerance taken from the IR's acceptance criteria or verification parameters
     (L1's test procedure gives ±2 s), else a declared default;
   - state names are compared through the alias mapping in the IR.
6. Results: per signal PASS / FAIL / NOT COMPARED, with the numbers.

### Acceptance criteria
7. Each IR `AcceptanceCriterion` with a `check` is evaluated against the simulation result.
   Supported check forms: value at time, value over a window (always / never / reaches), event
   ordering, and "never simultaneously" over a set of boolean signals with an optional allowed
   state.
8. A criterion without a machine-checkable form is reported `NOT CHECKED` with the reason. It is
   never counted as a pass.

### Coverage and repeatability
9. `coverage.py` compares a produced IR with a reference IR: for parts, ports, connections,
   parameters (effective values within tolerance), states and transitions — matched by id, then
   by tag alias — it reports matched, missing and extra, and the percentage per category.
10. Repeatability: given two `ir.json` files from two runs, report whether the topology (parts by
    kind, connections by endpoint kinds) is identical, and list differences. Naming differences
    alone are not a failure (PRD §8.2).

## Acceptance
1. `verify` runs on `Modelica.StateGraph.Examples.ControlledTanks` (day 1, before any
   generated model exists) and produces `sim/result.csv`.
2. On the L1 model generated from the golden IR: every TP-17 acceptance criterion AC-01 … AC-08
   is PASS, or NOT CHECKED with a reason; state-change times match the reference trace within
   ±2 s.
3. `coverage` of the golden IR against itself is 100 % in every category; removing one part
   from a copy lowers the part percentage and lists it as missing.
4. Two runs of the pipeline on L1 (cached) give a repeatability verdict of identical.
5. A model with a deliberately violated interlock produces a FAIL naming the interlock and the
   time.

## Rules
| Id | Requirement |
|---|---|
| R-VER-1 | A check that did not run is NOT RUN / NOT CHECKED / NOT COMPARED — never PASS. |
| R-VER-2 | Every comparison states what was compared with what. |
| R-VER-3 | Tolerances come from the input's acceptance criteria where stated, and are otherwise declared as assumptions. |
| R-VER-4 | Verification documents define checks; they never change model parameters. |
| R-VER-5 | The golden IR is used here as a reference for scoring only, and only in tests and when passed explicitly with `--golden`. |
