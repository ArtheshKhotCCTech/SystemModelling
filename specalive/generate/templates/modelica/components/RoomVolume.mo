// Purpose: the catalogue's room_volume kind: a well-mixed air volume of constant mass rho*V whose
// trace-substance mass fraction C integrates what each inflow brings, rho*V*der(C) =
// sum m_in*(C_in - C); the exhaust carries the inflows out at C, and C is a signal for a sensor.
model RoomVolume "Well-mixed air volume: the trace mass fraction follows the inflows"
  parameter Real V(unit = "m3") "Air volume";
  parameter Real rho(unit = "kg/m3") "Air density, constant";
  parameter Real C_start(unit = "kg/kg") = 0 "Initial trace-substance mass fraction";
  SpecAlive.Interfaces.AirFlowInput supply "Supply air" annotation(Placement(transformation(extent = {{-120, 30}, {-80, 70}}), iconTransformation(extent = {{-120, 30}, {-80, 70}})));
  SpecAlive.Interfaces.AirFlowInput source "Trace-substance source" annotation(Placement(transformation(extent = {{-120, -70}, {-80, -30}}), iconTransformation(extent = {{-120, -70}, {-80, -30}})));
  SpecAlive.Interfaces.AirFlowOutput exhaust "Exhaust air, at the room's mass fraction" annotation(Placement(transformation(extent = {{80, 30}, {120, 70}}), iconTransformation(extent = {{80, 30}, {120, 70}})));
  SpecAlive.Interfaces.RealOutput concentration(unit = "kg/kg") "Room trace mass fraction" annotation(Placement(transformation(extent = {{80, -70}, {120, -30}}), iconTransformation(extent = {{80, -70}, {120, -30}})));
  Real C(unit = "kg/kg", start = C_start, fixed = true) "Room trace mass fraction";
equation
  rho * V * der(C) = supply.m_flow * (supply.C - C) + source.m_flow * (source.C - C);
  exhaust.m_flow = supply.m_flow + source.m_flow;
  exhaust.C = C;
  concentration = C;
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "room")}));
end RoomVolume;
