// Purpose: the catalogue's mass_flow_source kind: a commanded air supply whose command is the mass
// flow at the source's own port, positive into the source (the source-port sign convention), so
// air delivered to the network is the negated command; the trace mass fraction is an input.
model MassFlowSource "Commanded air supply: delivers minus the port mass-flow command"
  SpecAlive.Interfaces.RealInput m_flow_in(unit = "kg/s") "Mass flow at the source port, positive into the source";
  SpecAlive.Interfaces.RealInput C_in(unit = "kg/kg") "Trace-substance mass fraction supplied";
  SpecAlive.Interfaces.AirFlowOutput outlet "Air delivered to the network";
equation
  outlet.m_flow = -m_flow_in;
  outlet.C = C_in;
end MassFlowSource;
