# Adversarial specs — expected behaviour (FR-09 requirement 6, R-CLI-4)

> **STATUS: DRAFT, written by the coding agent before any run. The team reviews and edits this
> file before the first `specalive run` on these specs.** An expectation changed after a run is
> recorded as a deviation in `RESULTS.md`, never edited in place.

The pipeline was not tuned on any of these. Each is run as
`specalive run tests/adversarial/<spec>.txt -o out/adv_<name>`.
`tests/test_adversarial.py` checks the items marked **[test]** from the recorded responses.

## `one_paragraph_spec.txt` (phase 4, FR-04 acceptance 6)
A rainwater buffer tank in the L1 pattern family, all values and units stated. Kept as the
"different small system, same pattern family" case.
- [test] Parts: one tank, two on/off valves, a level sensor, a controller, a source and a sink.
- [test] Modelica compiles; SysML validates.
- [test] No conflict and no question about a stated value.

## `heated_tank_thermostat.txt` — a component the catalogue lacks
A heated tank with a thermostat and a drain valve. The catalogue has no heater and no
temperature sensor or thermostat.
- [test] The tank, both valves, the level transmitter and the controller are extracted with
  catalogue kinds.
- [test] The heater EH-5 and the thermostat TC-5 are **not** parts of the IR; each is named in a
  `Question` (unknown kind) or in `extract_report.json` as unresolved — never mapped to an
  invented kind or a Modelica class.
- [test] No Modelica class outside the catalogue appears in `model.mo`.
- The transition on "TC-5 reports 60 degC" cannot be expressed over IR ids; it is discarded with
  a reason or listed as missing information, not guessed.
- [test] The model still compiles (the thermal part is absent, and the report says so).

## `contradiction_no_precedence.txt` — direct contradiction, no precedence information
One source states CT-4's high level as 1.0 m and later as 1.3 m. There is no date, revision,
approval or source ranking to choose between them.
- [test] A `Question` names CT-4's high level and offers both 1.0 m and 1.3 m.
- [test] Neither value is silently chosen: if one is used as a default it is marked as the
  question's default or an `Assumption`, and the `Conflict` (if recorded) names the other.
- The summary lists the question under open questions.

## `missing_units_and_ics.txt` — missing units and initial conditions
No units on the area, valve flow or level; no initial level; no flow for OV-72.
- [test] No value is stored with a unit the text does not give unless an `Assumption` declares
  the unit; otherwise the value becomes a `Question`.
- [test] The initial level of ST-7 is a catalogue default with an `Assumption`.
- [test] OV-72's missing nominal flow is a `Question` or a declared default with an
  `Assumption` — never silently filled.
- [test] If the IR can be generated, `model.mo` compiles and carries `ASSUMPTION` comments for
  the assumed values; if it cannot, the run exits 1 or 2 with the reason, and the reports are
  still written.

## Graceful failure (FR-09 acceptance 4) — covered by `tests/test_cli_run.py`
- An empty directory: exit 2, a clear message, reports still written.
- `omc` not on the path: exit 3; `ir.json`, `model.sysml` and the reports still written.
