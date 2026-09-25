// Purpose: the catalogue's on_off_valve kind: an ideal Boolean flow switch passing its constant
// nominal flow when commanded open, as the ADR's constant-flow plant requires.
model OnOffValve "Ideal Boolean flow switch: passes its nominal flow when open, none when closed"
  parameter Real q_nominal(unit = "m3/s") "Flow when open";
  SpecAlive.Interfaces.VolumeFlowOutput inlet "Flow drawn from upstream";
  SpecAlive.Interfaces.VolumeFlowOutput outlet "Flow delivered downstream";
  SpecAlive.Interfaces.BooleanInput open "True commands the valve open";
equation
  outlet = if open then q_nominal else 0;
  inlet = outlet;
end OnOffValve;
