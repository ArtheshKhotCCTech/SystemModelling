// Purpose: the catalogue's room_volume kind: a well-mixed air volume of constant mass rho*V whose
// trace-substance mass fraction C integrates what each inflow brings, rho*V*der(C) =
// sum m_in*(C_in - C); the exhaust carries the inflows out at C, and C is a signal for a sensor.
model RoomVolume "Well-mixed air volume: the trace mass fraction follows the inflows"
  parameter Real V(unit = "m3") "Air volume";
  parameter Real rho(unit = "kg/m3") "Air density, constant";
  parameter Real C_start(unit = "kg/kg") = 0 "Initial trace-substance mass fraction";
  SpecAlive.Interfaces.AirFlowInput supply "Supply air";
  SpecAlive.Interfaces.AirFlowInput source "Trace-substance source";
  SpecAlive.Interfaces.AirFlowOutput exhaust "Exhaust air, at the room's mass fraction";
  SpecAlive.Interfaces.RealOutput concentration(unit = "kg/kg") "Room trace mass fraction";
  Real C(unit = "kg/kg", start = C_start, fixed = true) "Room trace mass fraction";
equation
  rho * V * der(C) = supply.m_flow * (supply.C - C) + source.m_flow * (source.C - C);
  exhaust.m_flow = supply.m_flow + source.m_flow;
  exhaust.C = C;
  concentration = C;
end RoomVolume;
