# Specification - Not Delivered

**This is not a phase.** Like `FR-11` it has no pull request of its own. It records what the PRD
describes or suggests that this project deliberately does not ship, so that absence is a decision
on record rather than an oversight, and so the next person knows what would re-enable each item.

## Why these are here
The timeline is 2–3 part-time days for three people. The PRD: "Scope expansion is rewarded when
it is coherent, not when it is merely large", and "One test case solved end to end beats four
solved partially." Each item below lost to depth on L1.

## What is not delivered

| Item | Source | Why not | What would re-enable it |
|---|---|---|---|
| **L3 Magnetic Circuit** | PRD §9 | New domain (quasi-static flux tubes, complex phasors, two grounds); needs catalogue kinds and phasor-typed ports the IR does not have. | Add `magnetic` / `electric` phasor port domains and flux-tube kinds to the catalogue, targeting `Modelica.Magnetic.QuasiStatic.FluxTubes`; a golden IR; the AV-11 analytic values as acceptance checks. |
| **L4 NaCl Evaporation Plant** | PRD §9 | Composition of L1–L3 under competing constraints: parallel split/join, 15 automated plus 13 manual valves, a custom medium the reference itself cannot run with pumps. | L2 and L3 first; parallel regions in the controller generator (possibly `Modelica.StateGraph.Parallel`, see `ADR.md`); StandardWater as the documented baseline medium. |
| **Web UI / SaaS** | PRD §11 ("SaaS is preferred") | Team decision for the timeline; reports carry the review function instead. | A thin web layer over the CLI stages, which already read and write files. |
| **Round-trip editing** | PRD §5.2 | Needs an edit model on top of the IR and trace updates on user change. | IR patches as evidence with source `user`, re-running generation; the trace machinery already supports it. |
| **Confidence scoring beyond a field** | PRD §5.2 | The IR carries `confidence`; calibrating it is out of scope. | Calibration against the golden IRs. |
| **Reuse library across runs** | PRD §5.2 | The catalogue is hand-written, not learned. | Promote recurring unknown-kind questions into catalogue entries after review. |
| **CAD / 3D geometry interpretation** | PRD §6.1 | JSON exports are read as text; no geometry is interpreted. | Readers for the exports, feeding elevations into static-head attributes. |
| **Sensor-fault and other non-baseline modes** | L2 DR-IAQ-05 item 8, L1 E-stop | Documented as out of the baseline runs by the inputs themselves. | Extract as additional states or modes; they would compile but have no reference trace. |

## Consequence worth stating
The generalisation claim rests on the architecture and on the adversarial spec set (`FR-09`), not
on having run four cases. Say so in the demo rather than letting judges discover it.

## Rules
| Id | Requirement |
|---|---|
| R-ND-1 | An item here moves out only through a new phase and specification, not as a side effect of another phase. |
| R-ND-2 | The demo states the scope honestly: L1 end to end, L2 if phase 10 landed, L3/L4 not attempted. |
