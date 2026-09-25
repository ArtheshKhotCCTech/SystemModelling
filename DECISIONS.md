# Decisions

Daily decision log, written by the team in the team's own words. One commit per day.

Format: `D<n> | what we decided | why the alternative lost`

1. **SysML v2 validator = OMG SysML v2 Pilot Implementation.**
  - Lost: Sensmetry SysIDE — needs a commercial licence key.
  - Lost: `sysml2py` — syntax-only; accepted a model with undefined types that the Pilot rejected.

2. **omc probe model -> `Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks`**
   (FR-01 req. 3, devenv.md and ADR.md updated).
   - Lost: `Modelica.StateGraph.Examples.ControlledTanks` — compiles but stops at runtime on
     OpenModelica 1.27.1, MSL 4.0.0 and 4.1.0.
   - Lost: raising `-mei` — fails the same way at 1000.
   - Lost: another OpenModelica release / another solver — harder to reproduce on every machine.

3. **`config.py` reads `.env`** from the working directory with `python-dotenv`; real environment
   variables win; values are never copied into `os.environ`.
   - Lost: `environment.bat` only — an extra file `.env` users would not need.
   - Lost: a hand-written parser — would need its own quoting/escape handling.

4. **`PYTHONUTF8=1` and venv activation stay outside `.env`** (shell or `environment.bat`).
   - Why: Python and the shell read them before SpecAlive starts. Documented in devenv.md.

5. **`.env.example` is tracked**, with the user's machine paths as examples.
   - Lost: commented-out placeholders (the AI's suggestion); we accepted the version shown.

6. **The probe reports omc's simulation messages** (`SPECALIVE_MESSAGES`).
   - Why: without it a runtime failure showed only "unexpected omc output".

7. **The AI never commits, pushes or opens PRs**; the user commits, on `main`.