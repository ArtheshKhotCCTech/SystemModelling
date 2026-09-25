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