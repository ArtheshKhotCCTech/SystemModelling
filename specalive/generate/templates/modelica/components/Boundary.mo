// Purpose: the catalogue's pressure_boundary kind: an ideal sink that accepts whatever air flow
// arrives; the lightweight plant has no pressure dynamics, so nothing is computed here.
model Boundary "Ideal boundary: accepts whatever air flow arrives"
  SpecAlive.Interfaces.AirFlowInput inlet "Air arriving at the boundary" annotation(Placement(transformation(extent = {{-120, -20}, {-80, 20}}), iconTransformation(extent = {{-120, -20}, {-80, 20}})));
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "boundary")}));
end Boundary;
