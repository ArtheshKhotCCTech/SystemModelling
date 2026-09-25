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

8. **The state machine schema gets `events`, `timers` and a `history` resume target**, beyond
   FR-02's field list.
   - Lost: packing STOP/resume and the frozen timer into transition text. The generators in
     phases 5 and 6 would have to guess at meaning that isn't typed.
   - Needs all three owners' sign-off, because it changes the shared schema.

9. **The TP-17 command schedule is stored as `verification_only` parameters on each pushbutton**
   (`press_times`, a list in seconds).
   - Lost: leaving it only in the URS-TST-002 requirement text. Phase 6/7 would have nowhere
     typed to read the stimulus from.
   - Consequence: `Parameter.value` may be a list.

10. **Guards, actions and acceptance checks are short strings that a small grammar in `ir.py`
    parses when the model loads.**
    - Lost: storing the parsed tree as nested JSON. It is correct but hard to read in the golden
      IR and harder for phase 4 to extract.
    - Lost: free text, which R-IR-6 forbids.

11. **Every numeric engineering value is a `Parameter` owned by its part. `attributes` hold only
    descriptive facts** such as fail position.
    - Why: each number then carries its own trace, status and authority, and a superseded value
      can stay in the IR.

12. **L1 plant kinds are lightweight SpecAlive components. The level sensor is the MSL
    `Modelica.Blocks.Routing.RealPassThrough`, checked with omc.**
    - Lost: MSL `BooleanTable` for the command button. It flips at each listed time, so every
      press would need two entries.

13. **A superseded parameter's id is the effective id plus the losing source**, for example
    `tk_101_high_level_urs_001`.
    - Why: ids stay unique and readable, and the conflict record can point at the losing value.
