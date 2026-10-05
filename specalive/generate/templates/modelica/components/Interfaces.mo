// Purpose: connectors of the SpecAlive component package. Signal connectors are aliases of the MSL
// block interfaces; volume flow is causal (input/output), because an ideal valve sets the flow on
// both its sides and a tank or boundary follows it (ADR: constant-flow lightweight plant). Air
// flow (phase 10) is causal the same way: the upstream part sets the mass flow and the
// trace-substance mass fraction it carries, and a well-mixed volume passes its own on.
connector RealInput = Modelica.Blocks.Interfaces.RealInput "Real signal input";
connector RealOutput = Modelica.Blocks.Interfaces.RealOutput "Real signal output";
connector BooleanInput = Modelica.Blocks.Interfaces.BooleanInput "Boolean signal input";
connector BooleanOutput = Modelica.Blocks.Interfaces.BooleanOutput "Boolean signal output";
connector VolumeFlowInput = input Real(unit = "m3/s") "Volume flow rate set by the connected component" annotation(Icon(graphics = {Polygon(points = {{-100, 100}, {100, 0}, {-100, -100}, {-100, 100}}, lineColor = {0, 127, 255}, fillColor = {0, 127, 255}, fillPattern = FillPattern.Solid)}));
connector VolumeFlowOutput = output Real(unit = "m3/s") "Volume flow rate set by this component" annotation(Icon(graphics = {Polygon(points = {{-100, 100}, {100, 0}, {-100, -100}, {-100, 100}}, lineColor = {0, 127, 255}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid)}));
connector AirFlowInput "Air mass flow and the trace-substance mass fraction it carries, set upstream"
  input Real m_flow(unit = "kg/s") "Mass flow in the direction of the connection";
  input Real C(unit = "kg/kg") "Trace-substance mass fraction of that flow";
  annotation(Icon(graphics = {Polygon(points = {{-100, 100}, {100, 0}, {-100, -100}, {-100, 100}}, lineColor = {0, 127, 127}, fillColor = {0, 127, 127}, fillPattern = FillPattern.Solid)}));
end AirFlowInput;
connector AirFlowOutput "Air mass flow and the trace-substance mass fraction it carries, set here"
  output Real m_flow(unit = "kg/s") "Mass flow in the direction of the connection";
  output Real C(unit = "kg/kg") "Trace-substance mass fraction of that flow";
  annotation(Icon(graphics = {Polygon(points = {{-100, 100}, {100, 0}, {-100, -100}, {-100, 100}}, lineColor = {0, 127, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid)}));
end AirFlowOutput;
