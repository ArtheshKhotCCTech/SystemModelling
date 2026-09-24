# Specification - CLI and End to End

Delivered by **phase 9**, Track C. Tasks C5, C6. Needs phases 4, 6 and 8. The first phase that
runs from inputs to a verified model with no hand-written IR in the loop — and the one the live
demo exercises on a spec the judges supply.

## Purpose
One command that takes a bundle or a paragraph of text and produces every output layer, shows its
progress while doing so, fails gracefully on bad input, and is tested on inputs the team did not
design against.

## Modules
1. `specalive/cli.py` — `run` wired to the real stages; the per-stage subcommands from phase 1
   now call the implementations.
2. `tests/adversarial/` — the unseen spec set.
3. `README.md` — setup, the `run` command, the compile command, the output layout.

## Requirements
1. `specalive run <bundle_dir | spec.txt> -o out/<run> [--text "…"] [--interactive]
   [--reference file.csv] [--golden ir.json] [--no-llm-cache]` runs ingest → extract → generate
   → compile → verify → report.
2. **Progress is visible.** Each stage prints its start, a one-line result and its duration; a
   long LLM stage shows what it is working on (source n of m). The PRD penalises "silence with no
   progress indication"; genuine multi-step latency is acceptable.
3. **Stages degrade, they do not crash.** A stage that fails writes its artefact with a failure
   status; later stages that depend on it report `NOT RUN`; the reports are still produced. The
   run ends with a one-screen outcome table.
4. Exit codes: 0 all gates passed; 1 the model was produced but a gate failed (reported);
   2 input problem (nothing usable to model — reported with what was wrong); 3 toolchain or
   infrastructure problem (`omc` or validator missing, API unreachable). Input problems and
   infrastructure problems are never confused.
5. `run.json` in the run folder: inputs, tool and model versions, per-stage status and timing,
   token use and cost, and the compile command.
6. **Adversarial set (C6)**, at least three specs the pipeline was not tuned on, each with the
   behaviour expected written down *before* running:
   - a plain-text paragraph describing a different small system in the same pattern family (e.g.
     a heated tank with a thermostat and a drain valve);
   - a spec with a direct contradiction and no precedence information — expected: a `Question`,
     not a silent choice;
   - a spec missing units and initial conditions — expected: assumptions or questions, and a
     model that still compiles with the assumptions marked;
   - optionally: an input describing a component the catalogue lacks — expected: a `Question`
     and no invented component.
7. The results of the adversarial runs — what happened, what was fixed as a result — are recorded
   (the briefing scores "tested against something real … and the results changed the build").

## Acceptance
1. `specalive run Testcases/tank_sysmlv2_full_dataset/tank_sysmlv2_full_dataset -o out/tank`
   on a clean cache completes in **under 10 minutes**, producing every artefact; the first
   structural draft (`ir.json`) exists in **under 2 minutes** of the run's start.
2. On that run: IR valid, SysML valid, Modelica compiles (command reproduced by another team
   member), simulates, acceptance criteria as in `FR-07` acceptance 2, coverage ≥ 80 % against the
   golden IR.
3. Each adversarial spec behaves as its written expectation says, or the deviation is recorded
   with what was changed.
4. `specalive run` on an empty directory exits 2 with a clear message; with `omc` removed from
   `PATH` it exits 3 and still writes the IR, the SysML and the reports.
5. The README's compile command, pasted into a fresh shell with the environment script, compiles
   the committed example model.

## Rules
| Id | Requirement |
|---|---|
| R-CLI-1 | Never silent: every stage reports start, result and duration. |
| R-CLI-2 | Failure degrades the run, never aborts it without reports. |
| R-CLI-3 | Input problems and infrastructure problems have different exit codes and messages. |
| R-CLI-4 | Adversarial expectations are written before the run, not after. |
| R-CLI-5 | The repo always contains at least one generated `.mo` that compiles, with its command. |
