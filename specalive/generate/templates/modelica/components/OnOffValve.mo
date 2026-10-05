// Purpose: the catalogue's on_off_valve kind: an ideal Boolean flow switch passing its constant
// nominal flow when commanded open, as the ADR's constant-flow plant requires.
model OnOffValve "Ideal Boolean flow switch: passes its nominal flow when open, none when closed"
  parameter Real q_nominal(unit = "m3/s") "Flow when open";
  SpecAlive.Interfaces.VolumeFlowOutput inlet "Flow drawn from upstream" annotation(Placement(transformation(extent = {{-120, 30}, {-80, 70}}), iconTransformation(extent = {{-120, 30}, {-80, 70}})));
  SpecAlive.Interfaces.VolumeFlowOutput outlet "Flow delivered downstream" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
  SpecAlive.Interfaces.BooleanInput open "True commands the valve open" annotation(Placement(transformation(extent = {{-120, -70}, {-80, -30}}), iconTransformation(extent = {{-120, -70}, {-80, -30}})));
equation
  outlet = if open then q_nominal else 0;
  inlet = outlet;
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "valve")}));
end OnOffValve;
