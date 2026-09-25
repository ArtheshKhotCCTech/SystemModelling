// Purpose: the catalogue's fluid_source kind: an ideal supply boundary with no equation of its own.
model FluidSource "Ideal supply boundary: delivers whatever flow downstream draws"
  SpecAlive.Interfaces.VolumeFlowInput outlet "Flow drawn by the downstream component";
end FluidSource;
