// Purpose: the catalogue's tank kind: der(h) = (q_in - q_out) / A with a fixed initial level, and
// the level as a signal. Inflow and outflow are set by the neighbouring valves.
model Tank "Open tank of constant cross-section: the level integrates inflow minus outflow"
  parameter Real A(unit = "m2") "Cross-section area";
  parameter Real h_start(unit = "m") "Initial level";
  SpecAlive.Interfaces.VolumeFlowInput inlet "Inflow, set by the upstream component" annotation(Placement(transformation(extent = {{-120, -20}, {-80, 20}}), iconTransformation(extent = {{-120, -20}, {-80, 20}})));
  SpecAlive.Interfaces.VolumeFlowInput outlet "Outflow, set by the downstream component" annotation(Placement(transformation(extent = {{80, 30}, {120, 70}}), iconTransformation(extent = {{80, 30}, {120, 70}})));
  SpecAlive.Interfaces.RealOutput level(unit = "m") "Liquid level" annotation(Placement(transformation(extent = {{80, -70}, {120, -30}}), iconTransformation(extent = {{80, -70}, {120, -30}})));
  Real h(unit = "m", start = h_start, fixed = true) "Liquid level";
equation
  der(h) = (inlet - outlet) / A;
  level = h;
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "tank")}));
end Tank;
