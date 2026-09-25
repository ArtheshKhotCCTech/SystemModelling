# AI Log

Cases where AI output was overridden, corrected or discarded, written by the team.

Format: `A<n> | what the AI produced | what we did instead | why`

1. **"OpenModelica isn't installed."**
   - AI said: not on PATH, not in the usual folders.
   - Truth: installed at `C:\Program Files\OpenModelica1.27.1-64bit` (v1.27.1); the first folder
     search returned nothing and the AI concluded too early.
   - Caught: Had to explicitly mention the location

2. **omc probe script used `res.resultFile` inside a string expression** (`specalive/toolchain/omc.py`).
   - OpenModelica 1.27.1 rejects it: `Error: Variable res.resultFile not found in scope`.
   - Never run against a real omc: the real-tool test was skipped while omc was not found.
   - Caught: once `.env` pointed at omc.exe, the skipped test ran and failed.
   - Fix: copy `res.resultFile` / `res.messages` into variables first; print the simulation's
     messages under a new `SPECALIVE_MESSAGES` marker.

3. **Said the probe model path "isn't wrong"** when we pointed at
   `Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks`.
   - Technically true (the StateGraph model exists), but the AI had not looked for a working
     alternative; we found the model that simulates on 1.27.1.

4. **First `.env.example` was wrong in two places.**
   - Said "SpecAlive does not load .env" — outdated as soon as `.env` loading was added.
   - Included `PYTHONUTF8=1`, which has no effect from `.env` (Python reads it at start-up).
   - Caught while implementing `.env` loading; corrected.