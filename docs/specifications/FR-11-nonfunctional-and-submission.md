# Specification - Non Functional Requirements and Submission

**This is the one cross-cutting specification. It is not a phase; follow it in all phases.**
Process tasks P1–P5 of the task sheet are governed here.

## Determinism and repeatability
1. The same input and configuration give the same IR topology and byte-identical generated
   models. Mechanisms: temperature 0, the response cache, deterministic ids, sorted iteration.
2. No clock, UUID or random value reaches a generated model or an IR. Timestamps belong in
   `run.json` only.
3. A prompt change invalidates its cache entries deliberately (the prompt is in the key); nobody
   edits the cache by hand.

## Honesty
4. The PRD, verbatim, and the reason for most of this document: "A model that is partially
   complete and honest about its gaps scores above one that is superficially complete and quietly
   wrong."
5. No fabricated components, ports, physics or values. Every element traces to evidence or a
   declared assumption (`R-IR-2`).
6. Contradictions are flagged; missing information is assumed-and-stated or asked (`R-EXT-1`,
   `R-EXT-2`).
7. No stage reports a pass it did not earn. A check that did not run is `NOT RUN`, `NOT CHECKED`
   or `NOT COMPARED`.

## Generalisation
8. **No case-specific logic in `specalive/`.** No test-case tag, file name, folder name or value.
   A review greps for them: `TK-10`, `XV-10`, `RM-201`, `B[1-7]\b`, `0\.78`, `0\.80`, `_sysmlv2_`.
9. Case knowledge lives in two places only: `catalogue/components.yaml` (generic component kinds)
   and `tests/` (goldens, fixtures, adversarial specs).
10. **Declared case-specific handling.** If anything case-specific proves unavoidable, it is listed
    here, with the reason, before the demo. The PRD: "If your pipeline contains logic that only
    fires for the two-tank problem, say so, because judges will look."
    - *None at present.*

## Error handling
11. Input problems (unreadable file, nothing modellable, contradictory with no default) and
    infrastructure problems (tool missing, API error, timeout) are distinguished in messages,
    statuses and exit codes (`FR-09`).
12. A stage failure degrades the run; reports are always produced.
13. Tool-reported errors are data, not exceptions (`R-FND-4`). `omc` messages and validator
    messages are carried into the reports verbatim — they are the most useful thing the system can
    tell a user.

## Testing
14. `pytest` for every layer. Each phase delivers the tests for its modules, written before the
    code (working rules).
15. The suite runs **offline**: LLM calls are served from recorded cache fixtures; `omc` and the
    validator tests are marked and skipped with a clear reason when the tool is absent — never
    silently passed.
16. Snapshot tests pin generated SysML and Modelica for the golden IRs.
17. The end-to-end L1 run (`FR-09` acceptance 1–2) is the release check. Quote its numbers in the
    pull request that completes phase 9.

## Logging, secrets, speed
18. Logs go to `out/<run>/run.log`; the terminal shows progress, not debug output.
19. `OPENAI_API_KEY` is read from the environment by `config.py` only; never printed, logged,
    cached or committed.
20. Speed targets from the PRD: first structural draft < 2 min; compiling model < 10 min for a
    supplied case. Per-stage timings are in `run.json`.

## Module-level state
21. No mutable module-level state on the pipeline path. Configuration is read once into an
    immutable settings object and passed down.

---

# Submission and process rules

The briefing: "Four things. Nothing else is read." — the git repository, `DECISIONS.md`,
`AI-LOG.md`, and at most 8 slides plus a live demo. Scoring is 45 method, 10 AI collaboration,
45 outcome, with Method capped at 27 if only one member can explain the design.

## The repository (P5, and every phase)
22. Contains at least one generated Modelica model that compiles, **and the command to compile
    it**, in the README. Judges run that command.
23. Readable cold in five minutes: README first, then `AGENTS.md`, then `docs/`.
24. Incremental commits with working slices early (Prototype discipline, 7 points). One phase per
    pull request makes this natural.

## `DECISIONS.md` (P1)
25. **One commit every day**, weekend included. Format:
    `D<n> | what we decided | why the alternative lost`.
26. Written by the team, in the team's words. Retro-added entries show in the git log and carry
    no weight; a missed day is a missed day.
27. Log what was killed. Judges pick three entries and ask what the alternative was.
28. Candidates already visible in this plan: CLI over SaaS; OpenAI; extract-then-generate over
    end-to-end generation; enumeration controller over StateGraph; lightweight components over
    `Modelica.Fluid` for L1; the SysML validator choice; L1-first scope.

## `AI-LOG.md` (P2)
29. **At least two** documented cases where AI output was overridden, corrected or discarded —
    what was done instead, and why. Both are examined live.
30. Sources to watch as they happen: rejected repairs in `repair_log.json`; discarded extraction
    fragments (quote not found); invented MSL classes or SysML syntax caught by the compiler or the
    validator; AI-suggested design choices the team rejected.
31. The AI tools themselves must not write these entries (working rules). "We asked Claude, it
    worked" scores near zero.

## Domain expert (P3)
32. Talk to a domain expert early and record the conversation's **visible delta** — a scope cut,
    a reframing, an assumption killed (Empathize, 10 points). No delta, no marks. Judges may be
    the experts; their Empathize score for teams that interviewed them is dropped, so it confers
    no advantage but costs nothing.

## Architecture note and deck (P4, P5)
33. Architecture note: one page — the pipeline diagram from `ARCHITECTURE.md` and the five
    decisions that matter most, each with its losing alternative.
34. Deck: at most 8 slides. Rehearse the live demo on an unseen spec (`FR-09` adversarial set);
    setup time comes out of the demo slot, and a compiler that will not start is a compile failure.

## Individual probes
35. Each member must be able to explain a part of the system they did not build. The phase
    specifications and the task sheet's owner column are what to study from.

## Definition of done (per phase)
- [ ] Tests written first, all passing offline.
- [ ] Acceptance checks of the phase's specification run, with numbers quoted in the pull request.
- [ ] Layer rule grep clean (`generate/` has no `llm`; nothing imports `cli`).
- [ ] Case-specific grep clean (item 8).
- [ ] `sourcemap.md` updated for every file added, removed or renamed.
- [ ] Anything the AI got wrong during the phase flagged to the owner for `AI-LOG.md`.
- [ ] That day's `DECISIONS.md` entry committed.
