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

5. **The phase 2 plan said the golden IR would have 16 parts. The bundle has 13.**
   - Caught when the golden was built and the count came out at 13.
   - Nothing was generated wrong, but the plan we approved carried a number the AI had not
     counted.

6. **The AI mapped `command_button` to MSL `Modelica.Blocks.Sources.BooleanTable` in the plan.**
   - That block flips its output at every listed time, so each momentary press would need a press
     time and a release time.
   - Instead: a SpecAlive `CommandButton` component that takes the list of press times.
   - The AI changed it during implementation and reported the change afterwards, not before.

7. **The AI's first IR test fixture shared one trace dict between every element.**
   - One test changed that dict, and two later tests failed for reasons that had nothing to do
     with `ir.py`.
   - Fix: the fixture returns a deep copy. Worth noting as a false failure the AI created itself.

8. **Email separator pattern missed hyphenated labels.**
   - `---- Follow-up ----` didn't match, so the NaCl thread gave 2 messages instead of 3.
   - All tests had passed. Found by reading the actual output; a test was added, then the
     pattern fixed.

9. **The L1 design note was classified `review_decision`.**
   - The title rule read the title and header as one string. The header line "Released after
     design review DR-02" matched "design review" before "design note" could.
   - Caught by the bundle acceptance test. Fix: check the title on its own first.

10. **The IAQ email was given revision `C`.**
   - The header parser read "OCC-SCH-04 Rev C" from a sentence in the email body.
   - Caught by reviewing the classification table. Fix: header parsing on document formats only.
   
11. **Control bytes written into source files.**
   - Shell heredoc edits collapsed backslash escapes and wrote real NULL and control characters
     into `tests/test_cli.py` and `specalive/llm/client.py`.
   - Caught when git flagged the file as binary and a test failed to import. Both fixed, and
     every changed file scanned.

12. **Minor, caught by unit tests:** inconsistent `src_` id prefix; the text `model Plant` in
   Modelica code read as a document title.

13. **The LLM invented quotes in the format of its own prompt.** 13 alias fragments quoted
   `"TK-101 [tank] aka tank1, T1"`, the format of the glossary the extractor gives the model.
   That text appears nowhere in the source. The verbatim quote check discarded every one.
   *The strongest example: the model cited its prompt as evidence, and it was caught.*

14. **The LLM stitched a quote across PDF table columns.** It joined a row label with a cell
   from another column (`"Nominal demo flow coefficient equivalent\n0.0045 m^3/s"`), so 2 flow
   values were discarded. The effective flows still came from the register.

15. **The LLM gave duplicate transition priorities.** "Any state → SHUTDOWN" was given the same
   priority as other transitions from each state (7 transitions); the validator rejected them.
