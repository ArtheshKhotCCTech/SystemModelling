# SpecAlive Development Environment Setup

Use this checklist for onboarding a team member. **Do it on day 1.** The briefing's own
advice: tool friction, not modelling, is what sinks teams in this domain, and a compiler that
will not start during judging counts as a compile failure.

1. Review the tech stack in `docs/design/ARCHITECTURE.md`.
2. Verify required tools are installed:
   - **Python 3.12.** Several Pythons are installed side by side on Windows machines here;
     create the virtual environment explicitly with 3.12 (`py -3.12 -m venv .venv`).
   - **OpenModelica** (`omc`), a recent release, with the **Modelica Standard Library 4.x**.
     Check: `omc --version`, then a `.mos` script with `loadModel(Modelica);` and
     `simulate(Modelica.StateGraph.Examples.ControlledTanks);` succeeds.
   - **SysML v2 validator** — the one chosen in phase 1 (T0.3). The candidate is the OMG
     SysML v2 Pilot Implementation, which needs **Java 17**. Record the install steps here
     once the spike settles it.
   - **git.**
   - An **OpenAI API key** with access to the chosen model.
3. If anything is missing:
   - Ask whether it is already installed and where.
   - If not installed, guide setup of the required software and packages.
4. Create the virtual environment and install: `pip install -e .[dev]`.
5. Create `environment.bat` (Windows) or `environment.sh` (Unix) in the project root.
6. Ensure the environment file:
   - Activates the virtual environment.
   - Puts `omc` on `PATH` (and Java, if the validator needs it).
   - Sets `OPENAI_API_KEY`.
   - Sets `SPECALIVE_CACHE_DIR` to a writable directory for cached LLM responses.
   - Sets `PYTHONUTF8=1`. The inputs contain non-ASCII text and the default Windows code page
     cannot encode it.
   - Prints `Environment configured`.
7. **Never commit the environment file.** It holds the API key. It is in `.gitignore`.

## Test data
1. The four benchmark bundles are under `Testcases/<case>_sysmlv2_full_dataset/<case>_sysmlv2_full_dataset/`,
   each with the same nine numbered folders: requirements, engineering register, diagrams,
   design notes, correspondence, legacy code, datasheets, commissioning, datasets.
2. They are **input**. Nothing writes into `Testcases/`.
3. For everyday work use L1 Tank. It is the smallest and the target of phases 1–9.

## Cost and speed
1. The response cache (phase 1) means a re-run of the same input costs nothing and returns the
   same result. Clear it deliberately (`specalive cache clear`) when a prompt changes.
2. The PRD targets a first structural draft in under 2 minutes and a compiling model in under
   10. Watch the per-stage timings the CLI prints.
