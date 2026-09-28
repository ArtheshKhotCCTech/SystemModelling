# SpecAlive

Turns a bundle of messy engineering inputs into a traced intermediate representation (IR), a
SysML v2 textual model and a Modelica model that compiles and simulates. Every element traces
to the input that justified it or to a declared assumption.

Read next: `AGENTS.md`, then `docs/` (start with `docs/implementation_plan.md`).

## Compiling the committed model
`examples/L1_tank/` holds the Modelica model (`model.mo`), SysML model and IR produced by
`specalive run` on the L1 Tank bundle. From the project root, with OpenModelica and MSL 4.0.0
installed:

```
cd examples/L1_tank/build
omc compile.mos
```

If `omc` is not on `PATH`, use its full path, e.g.
`"C:\Program Files\OpenModelica1.27.1-64bit\bin\omc.exe" compile.mos`. The script loads MSL
4.0.0 and `../model.mo`, runs `checkModel` and `buildModel` on `system_model.System`, and
prints `SPECALIVE_CHECK=Check of system_model.System completed successfully.`

## Setup
Full checklist: `docs/devenv.md`.

```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
specalive doctor
pytest
```

`specalive doctor` must report OK on all four checks (Python, omc + MSL, SysML v2 validator,
OpenAI API). Settings come from environment variables, then `.env` in the working directory;
`OPENAI_API_KEY` is never printed or cached.

## Running the pipeline
```
specalive run <bundle_dir | spec.txt> -o out/<run> [--text "..."] [--reference file.csv]
              [--golden ir.json] [--no-llm-cache] [--interactive]
```

- A folder is read as a bundle; a `.txt` file, or `--text "..."`, is treated as a plain-text
  requirement spec.
- `--reference` gives the reference trace CSV (default: the bundle's `reference_data` CSV).
- `--golden` scores structural coverage against a reference IR.
- `--no-llm-cache` calls the API for every request; the fresh answers replace cached ones.
- `--interactive` is accepted but not delivered: open questions and their defaults are listed in
  `report/summary.md`.

Example: `specalive run Testcases/tank_sysmlv2_full_dataset/tank_sysmlv2_full_dataset -o out/tank`.

Each stage prints its start, a one-line result and its duration; the LLM stage says which source
it is on. A stage that fails writes its artefact with the failure, the stages that depend on it
are `NOT RUN`, and the reports are still written. The run ends with an outcome table.

| Exit code | Meaning |
|---|---|
| 0 | every gate passed |
| 1 | the model was produced but a gate failed (see the outcome table) |
| 2 | input problem: nothing usable to model, with what was wrong |
| 3 | toolchain or infrastructure problem: omc or the validator missing, API unreachable |

Each stage is also its own subcommand (`ingest`, `extract`, `generate`, `compile`, `verify`,
`report`), reading and writing the same run folder; `specalive <stage> --help` lists its options.

## Output layout (`out/<run>/`)
| File | Written by | Content |
|---|---|---|
| `evidence.json` | ingest | every source with its read status, role and revision; located chunks |
| `ir.json`, `extract_report.json` | extract | the traced IR; discarded, unresolved and missing items |
| `model.sysml`, `model.mo` | generate | SysML v2 and Modelica, generated from the IR only |
| `sysml_validation.json` | compile | validator verdict, issues and the command that reproduces it |
| `compile.log`, `repair_log.json`, `build/compile.mos` | compile | omc verdict, every repair attempt, the reproducing omc command |
| `sim/result.csv`, `verification.json`, `coverage.json` | verify | simulation, reference comparison, acceptance criteria, coverage |
| `report/summary.md`, `traceability.md`, `assumptions.md`, `correspondence.md`, `plots/*.png` | report | the one-minute summary and the detailed reports |
| `run.json`, `run.log` | run | inputs, tool and model versions, per-stage status and timing, token use and cost, the compile command; the log |

## Status
Phases 1–8 are delivered, and phase 9 (`specalive run`) is in progress. On the L1 bundle the
extracted model compiles and simulates the full run. The acceptance criteria are not all met
yet: operator press times are not yet gathered from the test procedure, so the demo sequence
does not start. `tests/adversarial/` holds the unseen specs, with their expectations written
before they were run.
