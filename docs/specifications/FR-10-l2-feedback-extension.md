# Specification - L2 Feedback Extension (stretch)

Delivered by **phase 10**. Tasks T1.3, B7. **Only after phase 9 is done.** The PRD's L2 adds
one reasoning skill to L1: closed-loop feedback — disturbance, sensor, control law, actuator
acting back on the process.

## Purpose
Prove the architecture generalises: a second case, of a different kind, handled by **adding
catalogue entries and generator support for a pattern**, not by adding L2-specific code.

## Modules
1. `tests/goldens/L2_co2.ir.json` (T1.3).
2. `catalogue/components.yaml` — new kinds: `room_volume`, `mass_flow_source`,
   `trace_substance_source`, `pressure_boundary`, `concentration_sensor`, `gain`,
   `p_controller` (with limits and bias), `schedule_table`, `constant`.
3. `specalive/generate/modelica.py`, `specalive/generate/sysml.py` — continuous signal wiring
   (`Real` signal ports, block chains) where phase 5/6 only needed the discrete patterns.

## Requirements
1. The L2 golden IR is written by hand from the L2 bundle using the effective values: 100 m³
   room, outdoor 300 ppm (not the legacy 350), peak occupancy 15 (not 12), Kp 6.0, bias 3.5 ACH,
   integral disabled, limits 0.2–6.0 ACH, 8.18E-6 kg/s CO₂ per person; the 1000 ppm limit as
   **absolute**; the source-sign convention and the `C = 100 kg/kg` carrier trick as documented
   modelling devices, each an attribute with its own trace.
2. Signal chains (sensor → normalisation gain → controller → ACH-to-mass-flow gain → source) are
   generated from IR connections between `signal_real` ports; there is no "feedback loop"
   generator, only blocks and connections.
3. Units stay explicit through the chain; a normalised signal is marked dimensionless with its
   normalisation in the trace.
4. The catalogue's Modelica targets for the fluid parts may be MSL `Modelica.Fluid` components
   (the L2 reference is an MSL trace-substance example). Whatever is chosen is recorded in
   `ADR.md`.
5. **No L2-specific code.** Everything L2 needs arrives as catalogue data or as a generic
   capability (continuous signals, schedules, saturation) that any case can use.

## Acceptance
1. The L2 golden IR validates; its `.sysml` validates; its `.mo` compiles.
2. The 24 h simulation's maximum room CO₂ is ≤ 1000 ppm, and within 1 % of the reference
   (996.5 ppm near t = 54 000 s).
3. Physical supply flow is positive and the source command negative, as the CP-23 checks require.
4. `specalive run` on the L2 bundle reaches ≥ 80 % coverage against the L2 golden IR.
5. The diff for this phase touches the catalogue, generic generator code and tests — and no
   file contains an L2 tag or value outside `tests/`.

## Rules
| Id | Requirement |
|---|---|
| R-L2-1 | A new case is supported by catalogue data and generic capability, never case-specific branches. |
| R-L2-2 | Modelling devices (sign conventions, numerical scaling tricks) are recorded as such, not presented as physical quantities. |
