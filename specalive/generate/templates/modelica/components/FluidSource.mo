// Purpose: the catalogue's fluid_source kind: an ideal supply boundary with no equation of its own.
model FluidSource "Ideal supply boundary: delivers whatever flow downstream draws"
  SpecAlive.Interfaces.VolumeFlowInput outlet "Flow drawn by the downstream component" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "source")}));
end FluidSource;
