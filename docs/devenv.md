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
     `simulate(Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks);` succeeds.
   - **SysML v2 validator: the OMG SysML v2 Pilot Implementation** (chosen in phase 1, see
     `design/ADR.md`). It needs **Java 21** — Java 17 fails with `UnsupportedClassVersionError`.
     Install into the gitignored `tools/` folder, nothing system-wide:
     1. Download `jupyter-sysml-kernel-<version>.zip` from the latest release at
        https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation/releases and unzip it
        into `tools/sysml-pilot/`. You should then have
        `tools/sysml-pilot/sysml/jupyter-sysml-kernel-<version>-all.jar` and
        `tools/sysml-pilot/sysml/sysml.library/`. (Phase 1 used release 2026-08, kernel 0.62.0.)
     2. If `java -version` is below 21, download a Temurin 21 JRE zip
        (https://adoptium.net/temurin/releases/?version=21) and unzip it into `tools/`.
     3. Point `SPECALIVE_JAVA` at that `java.exe` (step 5). `SPECALIVE_SYSML_VALIDATOR` defaults
        to `tools/sysml-pilot/sysml`; set it only if you unzipped elsewhere.
   - **git.**
   - An **OpenAI API key** with access to the chosen model.
3. If anything is missing:
   - Ask whether it is already installed and where.
   - If not installed, guide setup of the required software and packages.
4. Create the virtual environment and install: `pip install -e .[dev]`.
5. Copy `.env.example` to `.env` in the project root and fill it in. `specalive/config.py`
   reads `.env` from the working directory, so run `specalive` and `pytest` from the project
   root. A real environment variable of the same name overrides the `.env` value.
   - Set `SPECALIVE_OMC` to the full path of `omc.exe`, or leave it as `omc` if OpenModelica's
     `bin` folder is on `PATH`.
   - Set `SPECALIVE_JAVA` to a Java 21 `java.exe` if the default `java` is older.
   - Set `OPENAI_API_KEY`.
   - Set `SPECALIVE_CACHE_DIR` to a writable directory for cached LLM responses.
   - Write values unquoted or in single quotes. Inside double quotes a backslash starts an
     escape, which breaks Windows paths.
6. Some settings cannot go in `.env`, because Python or the shell reads them before SpecAlive
   starts. Set them in your shell, your user environment, or an optional `environment.bat`
   (Windows) / `environment.sh` (Unix) in the project root:
   - Activate the virtual environment.
   - Set `PYTHONUTF8=1`. The inputs contain non-ASCII text and the default Windows code page
     cannot encode it.
   - If you use `environment.bat` / `environment.sh`, it prints `Environment configured`.
7. **Never commit `.env` or the environment file.** They hold the API key. Both are in
   `.gitignore`; `.env.example` is tracked and must never hold a real key.

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
