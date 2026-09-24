# Specification - Reports and Traceability

Delivered by **phase 8**, Track C. Tasks C4, B6. Needs the artefacts of phases 5, 6 and 7 to
report on; build against outputs generated from the golden IR, so it does not wait for Track A.

## Purpose
Deliver the PRD's output layers 3 and 4: the evidence and traceability record, and a summary an
engineer can approve or reject in under a minute. With a CLI-only product, **these reports are
the user interface** — they are how ambiguity is surfaced, which the briefing scores under design
thinking.

## Modules
1. `specalive/report/summary.py` → `report/summary.md`.
2. `specalive/report/traceability.py` → `report/traceability.md`.
3. `specalive/report/assumptions.py` → `report/assumptions.md`.
4. `specalive/report/correspondence.py` → `report/correspondence.md` (task B6).
5. `specalive/report/plots.py` → `report/plots/*.png`.
6. CLI: `specalive report --run out/<run>`.

## Requirements
1. **`summary.md`**, readable in under a minute, in this order:
   1. one-paragraph description of the system as the model understands it;
   2. a status line per gate: IR valid, SysML valid, Modelica compiles, simulates, acceptance
      criteria (n PASS / n FAIL / n NOT CHECKED), coverage if a reference IR was given;
   3. counts: parts, connections, states, requirements; assumptions, open questions, conflicts;
   4. **the open questions**, each with its default, first — they are what the engineer must act
      on;
   5. the top conflicts resolved by precedence, one line each ("T1 high: 0.80 m (CR-004) over
      0.78 m (URS-001 Rev A)");
   6. the command that compiles the model.
2. **`traceability.md`**: one row per IR element — id, type, name, primary source, locator,
   quote, confidence; assumed elements flagged. Grouped by element type, sorted by id.
3. **`assumptions.md`**: assumptions (text, basis, affected elements); conflicts (every
   candidate with its source and rank, the winner, the rationale); questions (options, default,
   answer if given); `rejected_untraced` elements; `missing_information`; unread sources.
4. **`correspondence.md`** (B6): one row per IR element — IR id, SysML element (qualified
   name), Modelica element (instance, connect pair or state literal), and a status column that is
   `MISSING` if any layer lacks it. Built by parsing the generated files for IR id comments, not by
   trusting the generator. This is the evidence for the briefing's Full tier ("Modelica derived
   from the SysML, correspondence shown").
5. **Plots**: one figure per compared signal group, simulation overlaid on the reference where one
   exists, state as a step trace; axis labels with units.
6. Reports are generated from artefacts on disk; a missing artefact makes its section say
   `NOT RUN — <reason>`, never disappear.
7. Markdown only, readable in a terminal and on GitHub.

## Acceptance
1. For an L1 run from the golden IR, all four reports and the plots are produced.
2. `summary.md` fits on one screen (≤ 60 lines) and names the compile command.
3. `correspondence.md` has no `MISSING` rows for the golden L1 run; deleting one connection from
   a copy of the generated `.mo` makes it show that connection as `MISSING` in the Modelica
   column.
4. Deleting `verification.json` from a run folder and re-running `report` produces reports whose
   verification section reads `NOT RUN` with a reason.
5. A reviewer who did not build the pipeline can answer, from the reports alone: what was
   assumed, what conflicted and why the winner won, and what is still open.

## Rules
| Id | Requirement |
|---|---|
| R-REP-1 | Open questions and assumptions are first-class outputs, first in the summary — not log lines. |
| R-REP-2 | Correspondence is verified by parsing the generated files, never asserted. |
| R-REP-3 | A section with nothing to report says NOT RUN and why. |
| R-REP-4 | Every number in a report is taken from an artefact, not recomputed differently. |
