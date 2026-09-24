# Specification - Modelica Generation and Compile Loop

Delivered by **phase 6**, Track B. Tasks B3, B4, B5. Depends on phase 2 only; built and
tested against the golden IR. **Carries the project's hard gate:** the briefing and the PRD both
treat "compiles without error" as binary, checked live by the judges.

## Purpose
Render the IR as a Modelica model built from catalogue components, with a controller generated
from the IR state machine, and make it compile — repairing mechanical faults automatically,
never by changing what the model is.

## Modules
1. `specalive/generate/modelica.py` — plant, wiring, parameters, experiment annotation.
2. `specalive/generate/controller.py` — state machine to Modelica.
3. `specalive/generate/templates/modelica/` — model template and the SpecAlive component package
   (lightweight equation-based components the catalogue can target).
4. `specalive/toolchain/omc.py` — load, check, build.
5. `specalive/repair/compile_loop.py`.
6. CLI: `specalive generate --only modelica` writes `model.mo`; `specalive compile` writes
   `compile.log`, `repair_log.json` and, when repaired, `model.repaired.mo`.

## Requirements

### Generation
1. **Deterministic**, as for SysML: same IR, byte-identical `.mo`; `generate/` imports no LLM.
2. Output is one Modelica package containing the system model and any SpecAlive component
   classes it uses, so the model compiles from one file with only MSL loaded.
3. One component instance per IR part, of the class the catalogue names, with parameters mapped
   from IR attributes and effective parameters, units as `unit=` / `quantity` attributes or SI
   types.
4. One `connect()` per IR connection, between the connectors the catalogue maps the port roles
   to. A port role the catalogue cannot map is a generation error naming the part and role —
   never a guess.
5. Each instance and connection carries a comment with its IR id.
6. `annotation(experiment(StopTime=…, Interval=…))` from the IR's verification parameters when
   present; otherwise a declared default recorded as an assumption.
7. Assumed parameters carry a comment `// ASSUMPTION A-n: …`.

### Controller
8. An IR state machine becomes a controller with:
   - a Modelica `type … = enumeration(…)` with one literal per IR state;
   - a discrete state variable with the IR initial state as its start value;
   - transitions as guarded assignments in an `algorithm` section, evaluated in IR priority
     order, with `when` / `elsewhen` for event triggers (rising edges of command inputs);
   - timers as a discrete start-time or remaining-time variable per timed state, so a pause can
     freeze and resume them when the IR says so;
   - outputs as functions of the state (the state's `outputs` pattern), so an output can only be
     true in a state the IR allows;
   - each IR interlock as an `assert` that fails the simulation if violated.
9. Command priority, pause/resume semantics and timer freezing are whatever the IR says. **The
   generator has no built-in notion of START, STOP or SHUT**; they are IR events like any other.

### Compile and repair
10. `omc.py` writes a `.mos` script that loads MSL (pinned version), loads the file, runs
    `checkModel` and `buildModel`, and collects `getErrorString()` after each step.
11. The loop:
    1. compile; if clean, stop;
    2. apply **deterministic fixes** for known mechanical faults (missing `import`, unit string
       spelling, a reserved word as a name) and recompile;
    3. otherwise, up to `config.REPAIR_ATTEMPTS` (default 3) LLM repairs: the model receives the
       `.mo` text, the error text and the IR summary, and returns a revised `.mo`;
    4. each candidate is **checked for topology preservation** before compiling: the multiset of
       component instances (class and IR id) and the set of `connect` pairs must equal the
       original's. A candidate that changes them is rejected and logged, and does not count as a
       fix;
    5. stop on the first clean compile or when attempts run out.
12. `repair_log.json` records every attempt: the errors in, the change made (a diff), whether it
    was deterministic or LLM, whether topology held, the result. These entries are the raw
    material for `AI-LOG.md`.
13. When the loop gives up, the stage reports `FAILED` with the last errors, keeps every
    attempt's file, and later stages report `NOT RUN`. It never claims a compile it did not get.
14. The exact command that compiles the delivered model is written to `compile.log` and later
    to `run.json` and the README.

## Acceptance
1. The golden L1 IR produces a `.mo` that **compiles with zero errors under `omc`** using the
   printed command, run by someone other than the author, on their own machine.
2. The L1 controller has the nine design-note states; the interlocks from the IR are present as
   asserts; pause freezes the remaining timer.
3. Every IR part and connection appears exactly once in the `.mo`, found by IR id comment.
4. Generating twice gives byte-identical output.
5. A test injects a known mechanical fault (e.g. a misspelled unit) and shows a deterministic
   fix; a second test mocks an LLM repair that deletes a component and shows it rejected.
6. `grep` for test-case tags or values in `specalive/generate/` and `specalive/repair/` returns
   nothing.

## Rules
| Id | Requirement |
|---|---|
| R-MO-1 | Compiling under `omc` is a hard gate, not a target. |
| R-MO-2 | Modelica is generated from the IR only, deterministically. |
| R-MO-3 | Components come from the catalogue; no class name is written that the catalogue did not supply. |
| R-MO-4 | Repair fixes code, never design: a repair that changes components or connections is rejected. |
| R-MO-5 | Every repair attempt is logged, including rejected ones. |
| R-MO-6 | A compile that failed is reported failed; downstream stages report NOT RUN. |
| R-MO-7 | The generator knows no domain events by name; behaviour comes from the IR state machine. |
| R-MO-8 | The compile command is printed and reproducible, because judges run it. |
