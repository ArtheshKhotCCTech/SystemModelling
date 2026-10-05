// Purpose: the catalogue's p_controller kind: proportional control with a bias and output limits,
// y = min(yMax, max(yMin, bias + k*(u_m - u_s))); the sign of k sets the direction of action.
// No integral term: a case that needs one needs another kind.
block PController "Proportional controller with bias and output limits"
  parameter Real k "Gain on measurement minus setpoint";
  parameter Real bias = 0 "Output when the measurement equals the setpoint";
  parameter Real yMin "Lower output limit";
  parameter Real yMax "Upper output limit";
  SpecAlive.Interfaces.RealInput u_s "Setpoint";
  SpecAlive.Interfaces.RealInput u_m "Measurement";
  SpecAlive.Interfaces.RealOutput y "Limited command";
equation
  y = min(yMax, max(yMin, bias + k * (u_m - u_s)));
end PController;
