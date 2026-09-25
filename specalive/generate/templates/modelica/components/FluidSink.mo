// Purpose: the catalogue's fluid_sink kind: an ideal drain boundary with no equation of its own.
model FluidSink "Ideal drain boundary: accepts whatever flow arrives"
  SpecAlive.Interfaces.VolumeFlowInput inlet "Flow delivered by the upstream component";
end FluidSink;
