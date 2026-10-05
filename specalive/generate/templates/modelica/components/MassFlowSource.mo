// Purpose: the catalogue's mass_flow_source kind: a commanded air supply whose command is the mass
// flow at the source's own port, positive into the source (the source-port sign convention), so
// air delivered to the network is the negated command; the trace mass fraction is an input.
model MassFlowSource "Commanded air supply: delivers minus the port mass-flow command"
  SpecAlive.Interfaces.RealInput m_flow_in(unit = "kg/s") "Mass flow at the source port, positive into the source" annotation(Placement(transformation(extent = {{-120, 30}, {-80, 70}}), iconTransformation(extent = {{-120, 30}, {-80, 70}})));
  SpecAlive.Interfaces.RealInput C_in(unit = "kg/kg") "Trace-substance mass fraction supplied" annotation(Placement(transformation(extent = {{-120, -70}, {-80, -30}}), iconTransformation(extent = {{-120, -70}, {-80, -30}})));
  SpecAlive.Interfaces.AirFlowOutput outlet "Air delivered to the network" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
equation
  outlet.m_flow = -m_flow_in;
  outlet.C = C_in;
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "air supply")}));
end MassFlowSource;
