// Purpose: the catalogue's trace_substance_source kind: injects a carrier flow at a fixed
// trace-substance mass fraction; the commanded flow is what leaves the source, so the substance
// added is m_flow_in * C. C may be a scaling device rather than a physical composition.
model TraceSource "Trace-substance injection: a carrier flow at a fixed mass fraction"
  parameter Real C(unit = "kg/kg") "Trace-substance mass fraction of the carrier";
  SpecAlive.Interfaces.RealInput m_flow_in(unit = "kg/s") "Carrier mass flow leaving the source" annotation(Placement(transformation(extent = {{-120, -20}, {-80, 20}}), iconTransformation(extent = {{-120, -20}, {-80, 20}})));
  SpecAlive.Interfaces.AirFlowOutput outlet "Carrier flow delivered to the network" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
equation
  outlet.m_flow = m_flow_in;
  outlet.C = C;
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "trace source")}));
end TraceSource;
