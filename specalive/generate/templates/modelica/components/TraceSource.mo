// Purpose: the catalogue's trace_substance_source kind: injects a carrier flow at a fixed
// trace-substance mass fraction; the commanded flow is what leaves the source, so the substance
// added is m_flow_in * C. C may be a scaling device rather than a physical composition.
model TraceSource "Trace-substance injection: a carrier flow at a fixed mass fraction"
  parameter Real C(unit = "kg/kg") "Trace-substance mass fraction of the carrier";
  SpecAlive.Interfaces.RealInput m_flow_in(unit = "kg/s") "Carrier mass flow leaving the source";
  SpecAlive.Interfaces.AirFlowOutput outlet "Carrier flow delivered to the network";
equation
  outlet.m_flow = m_flow_in;
  outlet.C = C;
end TraceSource;
