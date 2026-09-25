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

14. **Vision is built in but off by default** (SPECALIVE_VISION=0). Images are recorded unread, with the reason.
   - Alternative: never read images in phase 3, and leave llm/client.py unchanged.

15. **Phase 3 started without a recorded phase 2 sign-off** (FR-02 acceptance 6).

16. **Email messages are ordered newest first by parsed date**, not by position in the file.
   - The IAQ thread gets newer as you read down, so file order would be wrong.
   - This follows FR-03 requirement 4 over R-ING-5 (order in the file).

17. **Classification order:** source-index row, then the document's title and header, then the
   format default, then the LLM only if every rule finds nothing.
   - This goes beyond `ARCHITECTURE.md`, which allows `ingest/` to use `llm/` for vision only.
     The document has not been updated.
     
18. **The source index is found by its columns** (file name, type, reliability), never by the
   sheet name (R-ING-4).
   
19. **Diagrams are classified `other`.**
   - Alternative: add a diagram role to `SourceRole`. That is an IR schema change and needs all
     three owners.
     
20. **Evidence has its own `Source` model** (`ingest/evidence.py`). The IR schema is untouched;
   phase 4 maps one onto the other.
   
21. **Every source id starts with `src_`.** Without it, `make_id` added the prefix only to
   paths starting with a digit. **Title keyword rules apply to document formats only** (pdf, docx, md, txt, xlsx), not to
   code, data or email.
   
22. **Two-column Word tables are read as `key: value` rows.** Document header tables have that
    shape. Tables with three or more columns use their first row as headers.

23. **Extraction runs one source at a time in a fixed role order, register first**, over
    batches capped in size.
    - Alternative: one pass over the whole bundle.
    
24. **A glossary of aliases found so far is carried into later passes.**

25. **A separate behaviour pass per controller.** Each item is validated separately, and a
    rejected item gets one retry with the error fed back.
    
26. **Replies cut off at the length limit are split and retried** (`LLMIncomplete` added to
    `llm/client.py`).
    
27. **Entity merging uses union-find.** Two formal tags never join; names that only look alike
    merge only with an `Assumption`.
    
28. **Status columns in the evidence come before the precedence ladder** (FR-04 requirement 12).
    A register row takes the rank of the record it cites. Approval outranks recency.
    
29. **Documents cited but absent from the bundle become their own source records**
    (`cr_004`, `urs_001`), and traces point at them.
    
30. **Interactive questions (A7, stretch) were not delivered.**

31. **Shipped with a 245 s cold L1 extract**, above the 2-minute target (FR-11 item 20).

32. **Phase 3 had no pull request of its own.** It reached `main` through PR #1 together with
    phase 4. Commit `70492ad` is titled "Add comprehensive tests…" but contains the whole phase 3
    implementation.

33. **Controller ports named by IR port id on the part usage.** The alternative, the role name on
  the part def, lost because roles like `start` clash with inherited library features.

34. - **Guards kept in the IR expression form.** Operands are `in` attributes of the state def,
  bound through `exhibit state` to real ports and parameters. `timer_expired` and `in_state` are
  small `calc def`s. Two alternatives lost:
  - Doc-only guards: nothing checks them.
  - SysML `accept after <duration>` time triggers: they cannot express the IR rule that STOP
    freezes a timer and START resumes the remaining time.

35. **The IR `history` resume target becomes a documented `state history`.** SysML v2 has no
  history pseudostate. The alternative, expanding it into one transition per resumable state,
  lost because it adds elements the IR does not have and breaks the one-id-once correspondence.

36. **Only effective parameter values become model values.** Superseded and verification-only
  parameters (for example the TP-17 press times and the 900 s stop time) are listed in the
  requirement's doc as "not modelled". The alternative, emitting them with a status tag, lost
  because it breaks R-SYS-3, and phase 8 reports them anyway.

37. **One port def per domain, with a single `out` item.** `in` ports are the conjugate (`~Def`).
  The alternative, separate in/out port def pairs, doubles the defs for no extra checking.

38. **`satisfy` links point at feature paths, including states and transitions through the
  exhibited machine.** The alternative, satisfying only by parts, loses most of the L1
  requirement-to-behaviour links.

39. **`specalive generate` / `compile` without `--only` exit 1 until phase 6.** The SysML is
  written and validated, but Modelica is not, so "all gates passed" would be a false pass.

40. **Interlocks are acceptance criteria with mode `always` and no time window.** Each becomes an
    `assert` in the controller whose ports and states it reads. For L1 that is `ac_08`.
    - Lost: waiting for an interlock record in the IR. That is a schema change and needs all
      three owners.
    - Consequence: an invariant that reads outside one controller is not asserted. The generator
      reports it in its notes, and phase 7 checks it.

41. **Modelica uses `verification_only` values as the test scenario**: TP-17's press times and the
    900 s stop time. Effective values come first. Superseded and as-built-only values are never
    used.
    - Lost: effective values only, matching SysML (D36). The buttons would never be pressed and
      the run could not be compared with the reference trace.
    - The two models now differ on purpose: SysML shows the design, Modelica also carries the test.

42. **The controller is a single `when` block.** Its trigger list holds each command edge plus
    `pre(state) == S and guard` for every guarded transition. The body checks transitions from
    `pre(state)` in IR priority order.
    - Lost: one `when` per transition. Several branches assign `state`, and priority cannot be
      expressed across independent `when`s.
    - Lost: an `algorithm` outside `when`. The timer deadlines are `discrete Real`, and those can
      only be assigned inside a `when`.
    - Using `pre(state)` lets a guard that is already true when a state is entered still fire,
      one event iteration later.

43. **A timer is a deadline plus a remaining time.** `save_history` stores
    `remaining = deadline - time`; a history return sets `deadline = time + remaining`.
    - Lost: a timer that counts continuously with `der`. That adds a continuous state to a
      discrete concept and still needs extra freeze logic.

44. **Volume flow uses causal connectors** (`input`/`output Real`). The valve sets the flow on
    both of its sides; the tank, source and sink follow it.
    - Lost: a plain non-causal `Real` connector, which gives unbalanced components.
    - Lost: `Modelica.Fluid`, for the reason already in the ADR (flow would depend on head).

45. **Every usable IR value is one top-level parameter in `System`, named by its IR id.**
    Instances and the controller bind to those parameters.
    - Lost: writing numbers straight into modifiers. Each value would then appear in several
      places, and its IR id and ASSUMPTION comment would have no single home.

46. **Controller connectors are `SpecAlive.Interfaces` aliases of the MSL block interfaces.** The
    Python generator therefore writes no MSL class name beyond what the catalogue supplies
    (R-MO-3).

47. **The catalogue stays unchanged. The button pulse width (1 s) is a default of the
    `CommandButton` component.**
    - Lost: adding `pulse_width` to the catalogue. The catalogue's parameter list is part of the
      extraction prompt, so the change would invalidate every recorded LLM fixture.

48. **The output interval defaults to StopTime / 500** (omc's default), and the model marks it as
    `ASSUMPTION (generator default)`.
    - Lost: 1 s to match the reference trace. That would be a case-specific value in the
      generator.

49. **The repair topology check reads instances and `connect()` pairs by IR id, not by instance
    name.**
    - Lost: comparing names in the text. The deterministic keyword-rename fix would then fail
      its own check.

50. **`model.repaired.mo` is compiled once more before it is delivered**, so the printed command
    reproduces that exact file, not an attempt copy. Cost: one extra build of a few seconds.

51. **The deterministic-fix acceptance test injects a missing `import SI`, not a misspelled
    unit.** Under omc 1.27.1 a bad unit string (`"m^2"`) is only a Notification and the compile
    passes, so FR-06's own example could not show the loop working. The unit fix is kept, but
    only runs when other errors exist.

52. **The Modelica controller generator refuses** parallel regions (L4 is not delivered, FR-12),
    `==` / `!=` on Reals, and guards that read a port the controller does not own. Each refusal
    is a generation error that names the element. None of them is guessed.

53. **`generate` and `compile` without `--only` now run both models, and the worst exit code
    wins.** This replaces D39.
   
54. **`verify` takes `-o/--out` like every other stage, not `--run` as FR-07 writes it.**
    - Lost: `--run` only, which would make verify the one stage that differs.
    - Lost: accepting both. Two names for one option is CLI surface nobody asked for.
    - FR-07's text is now out of step with the CLI; the owners should correct it.

55. **FR-07 acceptance 1 uses `Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks`.**
    - Lost: `Modelica.StateGraph.Examples.ControlledTanks`, which the spec names. On omc 1.27.1
      it stops with "too many event iterations" (already in the ADR for the phase 1 probe).

56. **Acceptance 1 is an omc-marked test calling `verify/simulate.py`, not a CLI flag.**
    - Lost: `specalive verify --model <MSL class>`. It would add CLI surface only a test needs.

57. **The IR id -> result variable map is read from the `[IR id]` descriptions the generator
    writes, plus the catalogue's connector names.**
    - Lost: importing the generator's naming functions. `verify/` may not import `generate/`.
    - Lost: moving the naming rules into `core/`. That touches the shared contract layer.
    - Lost: assuming a variable is named after its IR id. The keyword rename (`end` -> `end_`)
      would break that silently.
    - Cost: verify depends on two generator conventions: every instance and controller connector
      carries `[IR id]`, and a controller's first variable of its enumeration type is the
      active state. If the generator changes either, verify reports notes instead of guessing.

58. **Verify simulates only the model the compile stage delivered** (`repair_log.json`: the
    repaired file if there is one), and refuses a model that did not compile.
    - Lost: simulating `model.mo` regardless. It could simulate a file other than the one whose
      compile was reported.

59. **Verify runs its own `simulate.mos` in `out/<run>/sim/`**, not the executable the compile
    built. That gives a separate command a judge can rerun, at a cost of a few seconds per run.

60. **Tolerances come from the IR where it states them, otherwise from declared defaults in
    `config.py`:** 2 s for event times and 2 % of the reference signal's range for continuous
    signals. `verification.json` lists each tolerance with its source; defaults are listed
    as assumptions (R-VER-3).
    - The IR tolerance is a system-owned parameter with a time unit and "tolerance" in its name.
      For L1 that is TP-17's ±2 s.
    - Lost: hard-coding ±2 s. That is a case value in the package.
    - Lost: a per-signal tolerance field in the IR. That is a schema change.

61. **Discrete signals and states are compared by their change times, matched in order;
    continuous signals by the largest error at the reference's sample times.**
    - Lost: comparing discrete values sample by sample. A 0.6 s offset would count as many
      mismatched samples, with no time error to report against TP-17's ±2 s.

62. **Mapping a reference column to the model:**
    - A column whose values are state names maps to the state machine they belong to.
    - Any other column maps by tag alias to one part, then by port role or connector name to one
      port, and the unit suffix is checked.
    - An ambiguous or unmatched column is NOT COMPARED, with the reason. For L1 that applies to
      `wait_remaining_s`.
    - Lost: letting the LLM map columns. It would bring the LLM into `verify/`, and the mapping
      could change from run to run.
    - When ingestion finds several `reference_data` CSVs, none is picked; the user chooses one
      with `--reference`.

63. **Event-ordering checks are not supported.** The IR `Check` schema has only `at`, `always`
    and `eventually`. Adding an ordering form is a schema change for all three owners. For L1,
    AC-01/04/07 stay NOT CHECKED with the IR's reason, and the state-change comparison covers
    their intent.

64. **A criterion that reads `timer_expired(...)` is NOT CHECKED.** The timer is internal to the
    generated controller and has no named result variable. Reading the generator's
    `_deadline` variables would couple verify to generator internals.

65. **An assert that stops the run fails the criterion its message names.**
    - The generator writes each assert message as `<criterion id>: <text>`.
    - Verify records when the assert was first violated as well as when the run threw.
    - Windows that run past the stop are NOT CHECKED, not passed.

66. **Repeatability compares topology only** (parts by kind, connections by the kinds at each
    end), and lists naming differences without failing on them (PRD §8.2). In coverage, a
    parameter counts as matched only when its effective value agrees within a relative 1e-6. A
    parameter found with a different value is listed as mismatched, apart from missing ones.

67. **`coverage.json` is always written.** It says NOT RUN when no `--golden` is given, because
    the golden IR may be read only when passed explicitly (R-VER-5).

68. **`CommandButton.mo` (phase 6) was rewritten on the MSL `Modelica.Blocks.Sources.BooleanTable`**
    (switch times: press, press + width, ...). Approved by the owner during phase 7.
    - Lost: marking FR-07 acceptance 2 as an expected failure and leaving the fix to Track B.
    - Lost: leaving the suite red.
    - Not tried: other hand-written event formulations. BooleanTable is MSL and worked first
      time, including with an empty press list.
    - Open edge: two presses closer than one pulse width. BooleanTable expects increasing switch
      times, and this is untested.