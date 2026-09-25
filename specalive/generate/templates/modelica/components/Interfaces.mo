// Purpose: connectors of the SpecAlive component package. Signal connectors are aliases of the MSL
// block interfaces; volume flow is causal (input/output), because an ideal valve sets the flow on
// both its sides and a tank or boundary follows it (ADR: constant-flow lightweight plant).
connector RealInput = Modelica.Blocks.Interfaces.RealInput "Real signal input";
connector RealOutput = Modelica.Blocks.Interfaces.RealOutput "Real signal output";
connector BooleanInput = Modelica.Blocks.Interfaces.BooleanInput "Boolean signal input";
connector BooleanOutput = Modelica.Blocks.Interfaces.BooleanOutput "Boolean signal output";
connector VolumeFlowInput = input Real(unit = "m3/s") "Volume flow rate set by the connected component";
connector VolumeFlowOutput = output Real(unit = "m3/s") "Volume flow rate set by this component";
