# Specification - IR Schema, Component Catalogue and Golden IR

Delivered by **phase 2**. Tasks T1.1, T1.2, T1.4 (T1.3, the L2 golden IR, belongs to
phase 10). Shared, and **signed off by all three owners**: after it lands, every track codes
against it, and a change is a cross-track change.

## Purpose
Define the single source of truth that both generated models come from, the catalogue that
constrains what can be generated, and a hand-written reference instance that lets Tracks B and
C start without waiting for Track A.

## Modules
1. `specalive/core/ir.py` — the schema.
2. `specalive/core/ids.py` — deterministic ids.
3. `specalive/core/units.py` — unit table.
4. `specalive/core/catalogue.py` and `catalogue/components.yaml`.
5. `docs/ir.schema.json` — exported JSON Schema (generated, committed).
6. `tests/goldens/L1_tank.ir.json` — golden IR for L1 Tank.

## Requirements

### The IR
1. `SystemModel` is the root: `name`, `description`, `parts`, `connections`, `parameters`,
   `state_machines`, `requirements`, `acceptance_criteria`, `assumptions`, `questions`,
   `conflicts`, `sources`.
2. `Part`: `id`, `kind` (a catalogue key), `name`, `tags` (every alias seen: formal tag, short
   name, legacy name), `attributes`, `ports`, `trace`, `assumption_ids`, `confidence`.
3. `Port`: `id`, `role` (e.g. `inlet`, `outlet`, `level_out`, `cmd_in`), `direction`
   (`in`/`out`/`inout`), `domain` (`fluid`, `signal_real`, `signal_bool`, `event`, `thermal`,
   `electric`, `magnetic`), `unit`.
4. `Connection`: `id`, `from_port`, `to_port`, `medium_or_signal`, `trace`.
5. `Parameter`: `id`, `owner` (part id or `system`), `name`, `value` (SI), `unit` (SI),
   `original` (value and unit as written), `status` (`effective`, `superseded`,
   `as_built_only`, `verification_only`), `authority` (source id), `trace`.
6. `StateMachine`: `id`, `owner`, `states` (`id`, `name`, `entry_actions`, `outputs` —
   the actuator pattern held in the state), `transitions` (`from`, `to`, `trigger` event,
   `guard` expression, `actions`, `priority`), `regions` (for parallel branches), `initial`.
   Guards and actions use a small expression language over IR ids (comparisons, `and`, `or`,
   `not`, timers), defined in `ir.py` and parsed, never free text.
7. `Requirement`: `id` (as in the source, e.g. `URS-F-004`), `text`, `category`, `status`
   (`active` / `superseded`), `superseded_by`, `satisfied_by` (element ids), `trace`.
8. `AcceptanceCriterion`: `id`, `text`, a machine-checkable `check` where one can be derived
   (signal, comparison, time window), or `check = None` with a reason, `trace`.
9. Honesty records:
   - `TraceLink`: `source_id`, `locator` (page, sheet+row, section, line), `quote` (verbatim,
     at most ~300 characters).
   - `Assumption`: `id`, `text`, `basis` (`engineering_convention`, `default`,
     `inferred`), `affects` (element ids), `confidence`.
   - `Question`: `id`, `text`, `options`, `default_if_unanswered`, `affects`, `answer`.
   - `Conflict`: `id`, `subject` (element id and field), `candidates` (value, source,
     authority rank), `resolution` (winning value or `unresolved`), `rationale`.
10. **Every `Part`, `Port`, `Connection`, `Parameter`, `StateMachine` and `Requirement` has a
    non-empty `trace` or at least one `assumption_id`.** A validator on `SystemModel` enforces
    it. `Port`s may inherit their part's trace.
11. Every cross-reference (a port id in a connection, an owner, an `affects` list) resolves; a
    dangling reference fails validation.
12. The schema exports to JSON Schema, and the extraction schemas sent to the LLM in phase 4
    are derived from it, so the two cannot drift.

### Ids and units
13. `ids.make_id(kind, tag)` produces a lowercase, Modelica- and SysML-legal identifier from
    the canonical tag (`TK-101` → `tk_101`). Deterministic, collision-checked, and the only way
    ids are made.
14. `units.py` converts the units that appear in the benchmark inputs (m, mm, m², m³, s, h,
    kg/s, m³/s, ppm, kg/kg, Pa, bar, °C, K, W, A, V, Hz, turns, 1/h) to SI. An unknown unit
    raises `UnknownUnit`, which phase 4 turns into a `Question`.

### The catalogue
15. Each entry: `kind`, `description`, `sysml` (part def name, ports), `modelica` (class,
    parameter mapping from IR attribute names, connector mapping from port roles), `required`
    attributes, and `defaults` — each default with the assumption text phase 4 records when it
    is used.
16. The phase 2 catalogue covers at least the L1 kinds: `tank`, `on_off_valve`,
    `level_sensor`, `command_button`, `sequence_controller`, `fluid_source`, `fluid_sink`.
17. The Modelica target of a kind is either an MSL class or a class in the SpecAlive component
    package (see `ADR.md`, model representation). The catalogue says which, and nothing else in
    the code decides.
18. `catalogue.py` validates the file at load: every mapped connector exists in the entry's port
    list, every required attribute has a mapping.

### The golden IR
19. `tests/goldens/L1_tank.ir.json` is written **by hand from the L1 bundle**, using the
    effective values (T1 high 0.80 m; waits 10 / 12 / 8 s; areas 1.2 / 1.4 m²; flows
    0.006 / 0.0045 / 0.005 m³/s), the nine controller states and transitions of the design note,
    the interlocks, and the TP-17 acceptance criteria. Each element traces to the document that
    justifies it.
20. It records the conflicts a correct extraction must find (0.78 vs 0.80 m; 10 vs 12 s;
    10 vs 8 s) and the legacy state-name mapping as aliases.

## Acceptance
1. `tests/goldens/L1_tank.ir.json` loads and validates against `SystemModel`.
2. Removing the `trace` from one part in a copy of the golden IR fails validation with a message
   naming that part. Same for a dangling port reference.
3. `docs/ir.schema.json` regenerates identically from `ir.py` (a test compares them).
4. The catalogue loads and validates; every `kind` in the golden IR is in it.
5. `python -c "import specalive.core.ir, sys; print('openai' in sys.modules)"` prints `False`.
6. The pull request carries the three owners' sign-off.

## Rules
| Id | Requirement |
|---|---|
| R-IR-1 | The IR is the only input to generation. Nothing generates from evidence or from another generated model. |
| R-IR-2 | No element without a trace or an assumption (requirement 10). |
| R-IR-3 | Ids are made by `ids.make_id` only; the LLM never chooses an id. |
| R-IR-4 | Parameter values are stored in SI; the original value and unit are kept. |
| R-IR-5 | A superseded value stays in the IR with `status = superseded`; it is never deleted. Traceability needs the loser as much as the winner. |
| R-IR-6 | Guards and actions are parsed expressions over IR ids, not free text. |
| R-CAT-1 | A kind not in the catalogue is never emitted. Phase 4 turns it into a Question. |
| R-CAT-2 | Every catalogue default carries the assumption text that is recorded when it is used. |
| R-GLD-1 | Golden IRs live in `tests/`. Nothing in `specalive/` reads them. |
| R-GLD-2 | A schema change after sign-off updates every golden IR in the same pull request. |
