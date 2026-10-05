// Purpose: the catalogue's fluid_sink kind: an ideal drain boundary with no equation of its own.
model FluidSink "Ideal drain boundary: accepts whatever flow arrives"
  SpecAlive.Interfaces.VolumeFlowInput inlet "Flow delivered by the upstream component" annotation(Placement(transformation(extent = {{-120, -20}, {-80, 20}}), iconTransformation(extent = {{-120, -20}, {-80, 20}})));
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "sink")}));
end FluidSink;
