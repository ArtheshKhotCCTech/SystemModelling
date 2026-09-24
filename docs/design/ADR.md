# Architecture Decision Record (ADR) Index

This is an index of key architecture decision records.

The index format is of two types
1. `<relative document path>` : {{short 2-3 lines description of document content}}
2. {{decision description for short decisions}}

## How to use this file
- ADRs are high level design decisions which impact multiple packages or source files. Do not
  document low level design decisions like class design or method design here.
- Every decision carries the reason it was taken and the alternative that lost. Judges pick
  entries from `DECISIONS.md` and ask exactly that; this file is where the long form lives.
- A decision marked **Proposed** is the default until the named phase confirms or replaces it.
  Record the outcome here and in `DECISIONS.md`.

## ADR Index

### Where the LLM sits
- **Extract into a typed IR, then generate deterministically.** The PRD (§10) calls this "usually
  more reliable and easier to defend" than end-to-end generation, and warns (§7) that generating
  SysML and Modelica independently is "the most common way to get silent divergence".
  - **Rejected: the LLM writes SysML and Modelica directly.** Two independent generations have
    no shared structure to check against each other, and a generated file cannot be traced
    element by element to its evidence.
  - **Consequence:** `generate/` imports nothing from `llm/`. That rule is a grep, not a review
    comment.
- **Agentic behaviour only where a loop earns its cost.** Three places: extraction over many
  documents (per-document passes, then merge), the compile-and-repair loop (compiler output fed
  back), and clarifying questions (phase 4 stretch).
  - **Rejected: an LLM planner orchestrating the whole pipeline.** The PRD: "Using an agent
    where a single call would do is not automatically better." A fixed stage order is testable,
    repeatable and explainable in a 45-minute evaluation.
- **The repair loop may fix code, not design.** At most three LLM attempts; deterministic fixes
  first. A repair that changes the set of components or connections is rejected. Otherwise a
  compile failure could be "fixed" by deleting the part that failed — plausible, compiling and
  wrong, which the PRD scores below an honest partial model.

### Honesty and traceability
- **Every IR element carries a TraceLink or an Assumption, or it is rejected.** The PRD's honesty
  criterion: "No fabricated components. Every element traces to an input fragment or a declared
  assumption." Enforcing it at the IR means both generated models inherit it.
- **Components come only from the catalogue.** The LLM chooses a catalogue kind; it never names
  a Modelica class. This is the domain-knowledge injection the PRD (§10) asks about, and the
  guard against invented library components the briefing names as a common AI failure.
  - **Rejected: retrieval over the MSL source.** More general, but the catalogue is small enough
    to write by hand for the target cases, and an unknown kind becoming a `Question` is the
    behaviour the PRD wants.
- **Conflicts are resolved by an explicit precedence ladder and always recorded.** Highest first:
  1. approved change record (CR);
  2. approved design-review decision;
  3. released requirement specification / released design note;
  4. supplier datasheet (for equipment properties only);
  5. legacy model, legacy architecture drawing;
  6. informal notes, email, lab notebook.
  Verification documents (test procedures, reference traces) are **evidence of intent, not design
  authority** — the L1 change log says so in terms ("Verification input, not design authority").
  A tie, or a conflict the ladder cannot rank, becomes a `Question`.
  - **Evidence the ladder is needed:** every one of the four bundles carries at least one value a
    newer-looking file states wrongly (L1: T1 high 0.78 → 0.80 m; L2: outdoor CO2 350 → 300 ppm;
    L3: mu_r 1000 → 1200; L4: B7 cooling 20 → 25 °C). The L4 register states the rule: "Do not
    assume the newest-looking file is automatically the design authority."
  - **Not case-specific:** the ladder ranks document *roles*, which the classifier infers from each
    document's content. It contains no file names.

### Repeatability
- **Temperature 0, structured outputs, and an on-disk response cache keyed by model + prompt +
  input hash.** The PRD's repeatability criterion: "The same input run twice yields a
  structurally equivalent model." Temperature 0 alone does not guarantee identical output; the
  cache does, and it makes the offline test suite possible.
- **Ids come from canonical tags, not from the LLM.** Naming variation is acceptable to the PRD;
  topology variation is not. Deterministic ids make a topology diff between two runs a set
  comparison.

### Model representation
- **Controllers are generated as a Modelica enumeration state with `algorithm` / `when` logic.**
  A SysML `state def` maps one-to-one onto an enumeration literal per state, with transitions as
  guarded assignments. Timers, command priority and interlocks are explicit and easy to read.
  - **Rejected: `Modelica.StateGraph`.** It is the library the L1 reference diagram was drawn
    in, but it is a graphical, connection-heavy idiom (steps, transitions, signals wired
    together) that is harder to generate as text and harder to repair. The generated model must
    match the reference's structure and behaviour, not its library internals.
  - **Revisit** if a parallel split/join (L4) is attempted: StateGraph's `Parallel` may then be
    cheaper than hand-coded concurrent regions.
- **Proposed (confirm at phase 2 sign-off): L1 physical plant as lightweight equation-based
  components from a SpecAlive component package, with MSL for types, units and signal blocks.**
  The L1 valve datasheet says "each valve is treated as an ideal Boolean flow switch", the
  engineering register gives constant nominal flows, and the reference trace is constant-flow.
  `der(level) = (q_in - q_out)/A` reproduces that; `Modelica.Fluid` tanks and valves would make
  flow depend on head and pressure, so the trajectories would not match the reference and the
  medium setup adds compile risk.
  - **Cost, accepted:** the PRD encourages MSL use. The catalogue allows a kind to target either
    a SpecAlive component or an MSL class, so the `Modelica.Fluid` variant stays open as an
    extension.

### Product shape
- **Command line only.** The team's decision, for the 2–3 day timeline. **Cost, accepted:** the
  PRD prefers SaaS, and design-thinking marks depend on how ambiguity is surfaced to a user. The
  mitigation is the report layer: assumptions, conflicts and questions are first-class outputs,
  not log lines.
- **Each stage is a subcommand that reads and writes files.** It costs a little plumbing, and
  buys three tracks that can be built and tested without waiting for each other.
- **Scope: L1 end to end first; L2 stretch; L3 and L4 not delivered.** The PRD: "One test case
  solved end to end beats four solved partially." The briefing: "A narrow subsystem that
  generates, compiles and holds up under questioning beats an ambitious plant model that does
  none of those." Generalisation is shown by the adversarial spec set (phase 9), not by breadth.

### Technology
- **Python 3.12.** The team's language; every library needed has wheels for it.
- **OpenAI API.** The team's decision. Structured outputs give schema-valid JSON directly from
  the Pydantic models.
- **The `omc` toolchain probe simulates `Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks`.**
  FR-01 first named `Modelica.StateGraph.Examples.ControlledTanks`. On OpenModelica 1.27.1 that
  model compiles but the run stops with "Simulation terminated due to too many, i.e. 20, event
  iterations", on MSL 4.0.0 and 4.1.0 alike.
  - **Rejected: raising the event-iteration limit.** With `-mei=1000` it fails the same way at
    1000 iterations, so the model loops on an event and a bigger limit only delays the failure.
  - **Consequence:** the Fluid example of the same name simulates to completion on 1.27.1 with
    MSL 4.0.0, so it proves what the probe exists to prove: `omc` loads MSL, compiles and runs.
- **Confirmed in phase 1 (T0.3): OMG SysML v2 Pilot Implementation as the SysML validator.** It
  is the reference implementation the PRD cites, and the only candidate that checks name
  resolution and typing, not just syntax: on a model referencing an undefined type it reports
  `Couldn't resolve reference to Type 'NoSuchType'` with line and column. Release 2026-08
  (kernel 0.62.0) was used.
  - **How it runs:** it has no batch CLI. `SysMLInteractive` (in `jupyter-sysml-kernel-*-all.jar`)
    is an interactive shell; `toolchain/sysml_validate.py` sends the model over stdin inside a
    `%` … `%` block, then `%exit`, and parses the `ERROR:` / `WARNING:` lines. About 4 s per run.
  - **Gotchas found in the spike:** it needs **Java 21** (class file 65), not 17; it exits 0 even
    when the model has errors, so the verdict comes from the output; and it mis-resolves a
    *relative* library path containing spaces (`Kernel%20Libraries`), so the library path is
    always passed absolute.
  - **Rejected: Sensmetry SysIDE (`syside` on PyPI).** It refuses to import without a commercial
    licence key (`SYSIDE_LICENSE_KEY`), so it cannot run on judges' or teammates' machines by
    default.
  - **Rejected: `sysml2py`.** Pure Python and easy to install, but syntax-only: it accepted a
    model with two undefined types that the Pilot rejected. A validator that passes unresolved
    references would let generated SysML look valid when it is not.
- **`.claude/workingrules.md` is tracked in git.** It is evidence of how the team directs its AI
  tools, which the briefing scores under AI collaboration. Agent memories and local settings stay
  ignored.
