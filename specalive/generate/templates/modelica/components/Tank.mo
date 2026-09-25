// Purpose: the catalogue's tank kind: der(h) = (q_in - q_out) / A with a fixed initial level, and
// the level as a signal. Inflow and outflow are set by the neighbouring valves.
model Tank "Open tank of constant cross-section: the level integrates inflow minus outflow"
  parameter Real A(unit = "m2") "Cross-section area";
  parameter Real h_start(unit = "m") "Initial level";
  SpecAlive.Interfaces.VolumeFlowInput inlet "Inflow, set by the upstream component";
  SpecAlive.Interfaces.VolumeFlowInput outlet "Outflow, set by the downstream component";
  SpecAlive.Interfaces.RealOutput level(unit = "m") "Liquid level";
  Real h(unit = "m", start = h_start, fixed = true) "Liquid level";
equation
  der(h) = (inlet - outlet) / A;
  level = h;
end Tank;
