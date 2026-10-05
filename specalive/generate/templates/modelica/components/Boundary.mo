// Purpose: the catalogue's pressure_boundary kind: an ideal sink that accepts whatever air flow
// arrives; the lightweight plant has no pressure dynamics, so nothing is computed here.
model Boundary "Ideal boundary: accepts whatever air flow arrives"
  SpecAlive.Interfaces.AirFlowInput inlet "Air arriving at the boundary";
end Boundary;
