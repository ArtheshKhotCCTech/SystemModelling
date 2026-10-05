// Purpose: the catalogue's p_controller kind: proportional control with a bias and output limits,
// y = min(yMax, max(yMin, bias + k*(u_m - u_s))); the sign of k sets the direction of action.
// No integral term: a case that needs one needs another kind.
block PController "Proportional controller with bias and output limits"
  parameter Real k "Gain on measurement minus setpoint";
  parameter Real bias = 0 "Output when the measurement equals the setpoint";
  parameter Real yMin "Lower output limit";
  parameter Real yMax "Upper output limit";
  SpecAlive.Interfaces.RealInput u_s "Setpoint" annotation(Placement(transformation(extent = {{-120, 30}, {-80, 70}}), iconTransformation(extent = {{-120, 30}, {-80, 70}})));
  SpecAlive.Interfaces.RealInput u_m "Measurement" annotation(Placement(transformation(extent = {{-120, -70}, {-80, -30}}), iconTransformation(extent = {{-120, -70}, {-80, -30}})));
  SpecAlive.Interfaces.RealOutput y "Limited command" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
equation
  y = min(yMax, max(yMin, bias + k * (u_m - u_s)));
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "P control")}));
end PController;
