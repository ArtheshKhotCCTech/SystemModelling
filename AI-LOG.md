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

16. **Invented transition-effect syntax.** The agent wrote `do save_history` (a bare reference to
   an action def) as a transition effect.
   Validator: `Couldn't resolve reference to Feature 'save_history'` and `Must reference an action`.
   Replaced by `do action : save_history`. Pinned in `tests/fixtures/sysml/state_machine.sysml`.

17. **Wrong redefinition of a directed parameter.** In the `exhibit state` bindings the agent wrote
   `:>> plc_101_level1 = ...` for an `in attribute` of the state def.
   Validator: `Redefining feature must have a compatible direction`.
   Replaced by `in :>> ...` (and `out :>> ...` for outputs).

18. **Missing library import.** The agent typed attributes `Real` / `Boolean` without importing
   `ScalarValues`. Validator: `Couldn't resolve reference to Type 'Real'`.
   Every generated package now has `private import ScalarValues::*;`.

19. **Name clash with an inherited library feature.** The first design named controller ports by
   their IR role (`start`, `stop`, ...). Every part inherits a `start` feature from the library.
   Validator: `WARNING: Duplicate of inherited member name 'start' from Part`. Quoting (`'start'`)
   does not help, because it is the same name. Dynamic ports are now named by IR port id
   (`plc_101_start`). Exhibit bindings use full paths (`plc_101.plc_101_start.value`) so a
   binding never resolves to itself.

20. **Latent bug in the phase 1 validator wrapper, found in phase 5.** `sysml_validate._ROOT_RE`
   expected the root-element echo to begin with the `1> ` prompt. After a warning, the Pilot
   prints the echo on a line of its own without the prompt, so a model with warnings and no
   errors was reported as failed (`validator parsed no model element`). Fixed the regex and
   added a test on the recorded output (`test_interpret_warnings_only_is_ok_when_root_follows_the_warning`).

21. **Template whitespace mistake, caught by reading the output rather than by the validator.**
   The Purpose comment at the top of each partial used `-#}`, which also stripped the indentation
   of the partial's first line: `port def` and `part def` landed at column 0. The validator
   accepted it, because layout means nothing to it, so only a human read caught it. Changed to `#}`.

22. **The missing-import fix put the import in the wrong class.**
    - The regex for `not found in scope System.` captured the trailing full stop, so the scope
      became `System.` and the last segment was empty. The import was inserted under the first
      package header instead of `model System`.
    - Caught by the unit test written before the code. Fix: the scope must end in a word
      character.

23. **The heredoc escaping failure again (see A11), this time in `toolchain/omc.py` and
    `tests/test_cli.py`.**
    - Python edits run through a shell heredoc turned `\n` into real line breaks inside string
      literals, and turned the `\b` in a regex into a backspace byte.
    - The AI's first attempt to patch this with a byte-level script replaced the wrong line: the
      probe's regex instead of the new one.
    - Fix: `omc.py` was restored from git and the compile section rewritten with direct edits;
      the `test_cli.py` strings were fixed by hand. The whole suite passed afterwards.
    - The same failure has now happened in two phases. A working rule to avoid multi-line
      heredoc edits for Python may be worth adding.

24. **The first test run used the wrong Python.** It ran under the system Python 3.13 instead of
    the project's `.venv` 3.12, and the AI noticed only from the traceback paths.

25. **A test the AI wrote first crashed on its own fixture.** The entry-action test used
    `t["actions"]` on transitions that have no `actions` key (`KeyError`). Nothing was wrong in
    the generator.

26. **Files beyond the approved plan.** The plan named `modelica.py`, `controller.py`, the
    templates, `omc.py` and `compile_loop.py`. The implementation also added
    `generate/modelica_text.py` (shared naming rules), `repair/__init__.py` and
    `tests/_modelica_support.py`. They were reported in the summary afterwards, not asked about
    first (compare A6).

27. **FR-06's own example fault was wrong for our toolchain** (see D51). Record this here only if
    the spec text was AI-drafted; otherwise it belongs in `DECISIONS.md` alone.
    - Caught by a spike before any code was written: omc 1.27.1 reports `Invalid unit expression`
      as a Notification.
   
28. **The phase 6 pushbutton was confidently wrong, and phase 7 caught it.** This is the
    strongest entry for the AI-collaboration walk.
    - `CommandButton` tested `time >= pressTimes[i]` inside a `for` loop. It compiled, it passed
      every phase 6 test, and the phase 6 summary called it correct.
    - Under omc 1.27.1 only the last index's crossing is tracked, and the pulse never ends. In
      the L1 run START at 20 s and STOP at 220/650 s never happened; the whole run was 260 s
      late.
    - The phase 6 pause/resume simulation test passed only because the solver's steps landed on
      its press times.
    - Caught by `specalive verify` against the reference trace: "change to fill_t1 at 20 s in
      the reference, the model changes to fill_t1 at 280 s". The AI then reproduced it in a
      10-line standalone model.
    - Fix: D68. There is now a phase 6 test that every L1 press gives exactly one pulse.
    - This shows compiling is not the same as being right, which is the briefing's own point.

29. **The AI's first assert parser reported the wrong time.**
    - omc prints a violated assert once at the event where it became false (65.0 s), then again
      where the run throws (65.2 s). The parser took the last one.
    - Caught by the FR-07 acceptance 5 test, which expected the draining state to begin at 65 s.
    - Fix: record the first violation of the stopping assert as the time, and the throw time as
      `stopped_at`.

30. **A test the AI wrote first was wrong, not the code.** The discrete-tolerance test's
    reference ended at 6 s, but the model change it was meant to match was at 6.5 s, outside the
    common time span. The fix was to lengthen the reference.

31. **The AI's first `compare_signals` quietly guessed.** When no variable map was passed, it
    fell back to assuming the controller's enumeration follows the IR state order. The AI removed
    the fallback before review and made the variable map a required argument. Keep this only if
    the team wants a self-caught example; it never reached a test run.

32. **The AI wrote a case-specific value into the package.** A docstring example in
    `verify/coverage.py` read "so TK-101 meets tk_101". The FR-11 grep (`TK-10`) caught it before
    the suite ran (`tests/test_rules.py` would have failed too). Changed to a neutral example.

33. **Heredoc edits failed a third time (see A11, A23).** Two multi-line Python edits through a
    bash heredoc failed with "unexpected EOF while looking for matching `'`". No file was damaged
    this time, because the shell refused before running. The AI switched to writing the edit
    scripts as files. Worth making the working rule suggested in A23.

34. **FR-07 named an MSL example already known to fail** (see D55). Record this here only if the
    spec text was AI-drafted; otherwise it belongs in `DECISIONS.md` alone.

35. **The AI's first correspondence rules called three superseded requirements MISSING.**
    - Its N/A rules assumed every requirement appears in SysML. The SysML generator emits
      only active ones (`urs_fun_006`, `urs_fun_008`, `urs_per_001` are superseded).
    - Caught by the test written first: golden L1 must have no MISSING rows (acceptance 3).
    - Fix: D72. The rule was learned from the generator's behaviour, not from a spec. Check
      that Track B agrees it is intended, not a gap.

36. **The AI wrote case-specific values into the package again (see A32).**
    - A docstring in `report/summary.py` used the L1 conflict,
      "TK-101 high_level: 0.80 m (CR-004 Rev 1) over 0.78 m", as its example.
    - A purpose comment said "(task B6)", which matches the FR-11 pattern `B[1-7]\b`.
    - Caught by the FR-11 grep during review, before hand-off. Replaced with a neutral template
      and "FR-08 req 4".
    - Second phase running with the same mistake. The grep works, but this is worth a working
      rule: no worked examples from test cases in package docstrings.

37. **The plan said "matplotlib 3.10.3 is installed". It was not, in the project's
    environment.**
    - The AI had checked with the `python` on PATH, which is 3.13. The project `.venv` is 3.12
      and had no matplotlib.
    - The same mistake made the first baseline `pytest` run fail with 4 collection errors
      (`No module named 'docx'`) before anything had changed. `docs/devenv.md` already says to
      use `.venv`.
    - Fix: ran everything through `.venv/Scripts/python`, and installed matplotlib there as the
      plan's new dependency.

38. **The AI's first Boolean plot hid data.**
    - The legend listed 12 entries, sat on the plot and covered the SHUT press at 700 s.
      Simulation and reference for the same signal were drawn in unrelated colours.
    - No test caught it; tests check files and groups, not legibility. The AI saw it when it
      opened the PNG.
    - Fix: one colour per signal, the reference in black dashed lines, and a two-entry legend
      outside the axes. Keep only if the team wants an example of reviewing output by eye.

39. **The AI's first correspondence draft had code it cleaned up before any test ran.**
    - A contradictory Modelica class-start condition.
    - A dead loop (`for heading in (NA,): del heading`).
    - An `ir:` regex that could match inside a requirement's text.
    - Self-caught, never ran. Keep only if the team wants a self-review example.

40. **A heredoc edit failed again (see A11, A23, A33).**
    - A Python edit script sent through a bash heredoc had `\s` in a non-raw string. The search
      text did not match, and the script stopped on its own `assert` before writing.
    - No file was damaged.
    - The AI moved the remaining edits into script files. A23's suggested working rule would
      have prevented it.

41. **One test the AI wrote first was wrong about wording, not behaviour.** It expected
    "more in assumptions.md"; the code writes "… and 22 more open questions in assumptions.md".
    The test was tightened to the exact text. This is minor; drop it unless it is useful.