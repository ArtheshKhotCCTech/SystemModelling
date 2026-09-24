# Specification - SysML v2 Generation

Delivered by **phase 5**, Track B. Tasks B1, B2. Depends on phase 2 only; built and tested
against the golden IR, so it does not wait for Track A.

## Purpose
Render the IR as a SysML v2 textual model that parses and validates, covers structure, interfaces,
connections, requirements and behaviour, and carries enough identity for every element to be
traced back to the IR and from there to its evidence.

## Modules
1. `specalive/generate/sysml.py`.
2. `specalive/generate/templates/sysml/` — `package.sysml.j2` and one partial per element type.
3. `specalive/toolchain/sysml_validate.py` — validation of a generated file.
4. CLI: `specalive generate --ir out/<run>/ir.json -o out/<run> --only sysml` writes
   `model.sysml`; `specalive compile --only sysml` writes `sysml_validation.json`.

## Requirements
1. **Deterministic.** The same IR produces a byte-identical `.sysml`. No LLM, no clock, no
   unordered iteration. `sysml.py` imports nothing from `specalive.llm`.
2. One package per system, importing the ISQ/SI libraries needed for units.
3. Emitted element types, at minimum:
   - `part def` per catalogue kind used, with its `port`s and `attribute`s;
   - `port def`s for each port domain used, with directed items (`in` / `out`);
   - the system `part` with its part usages, one per IR part, named by IR id;
   - `connect` (or `interface` / `flow`, as the validator supports) per IR connection;
   - `attribute`s with values and units for effective parameters;
   - `requirement def` / `requirement` per active IR requirement, with `satisfy` links to the
     elements in `satisfied_by`;
   - `state def` per IR state machine with states, `entry` actions, and transitions with
     `accept` triggers and `if` guards; parallel regions where the IR has them.
4. **Traceability in the model.** Each element carries a `doc` comment with its IR id and its
   primary source id and locator. Superseded parameter values are **not** emitted as values;
   they appear in the report (phase 8), not the model.
5. **Assumed elements are visibly marked**, e.g. `doc /* ASSUMPTION A-3: ... */`, so a reviewer
   reading only the SysML can see what the input did not state.
6. Names: IR ids are used as SysML names; the human name and tags go into `doc`. Names that
   collide with SysML keywords are escaped by `ids.py`, not by the template.
7. Templates use `StrictUndefined`: a missing field is an error, never an empty string.
8. Validation runs the phase 1 tool on the generated file and returns `ok`, the error list
   with line numbers, and the command used. A validator that cannot run returns `NOT RUN` with
   the reason, never `ok`.
9. **Before a construct is added to a template, a minimal example of it passes the validator.**
   Keep those examples under `tests/fixtures/sysml/`. SysML v2 syntax is exactly the kind of
   thing an LLM will state confidently and wrongly; the validator, not memory, is the authority.

## Acceptance
1. The golden L1 IR produces `model.sysml` that the validator accepts with zero errors.
2. It contains at least these element types: part def, port def, part usage, connection,
   attribute with unit, requirement with satisfy, state def with transitions. (The briefing's
   Solid tier asks for 3+ element types; this is the floor.)
3. Every IR part, connection, requirement and state machine appears exactly once, found by its
   IR id — checked by a test that parses the ids out of the `doc` comments.
4. Generating twice gives byte-identical output (snapshot test).
5. `grep -r "specalive.llm\|from ..llm\|import llm" specalive/generate/` returns nothing.
6. A deliberately broken IR (dangling port) fails at IR validation, before any template runs.

## Rules
| Id | Requirement |
|---|---|
| R-SYS-1 | SysML is generated from the IR only, deterministically. |
| R-SYS-2 | Every emitted element carries its IR id; the correspondence table in phase 8 depends on it. |
| R-SYS-3 | Only effective values become model values. Superseded ones are reported, not modelled. |
| R-SYS-4 | Assumed elements are marked as such in the model text. |
| R-SYS-5 | No construct enters a template until a fixture using it passes the validator. |
| R-SYS-6 | A validation that did not run is reported NOT RUN, never passed. |
