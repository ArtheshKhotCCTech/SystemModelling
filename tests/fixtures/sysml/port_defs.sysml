// Purpose: R-SYS-5 fixture. One port def per IR domain, each with one directed item; an IR
// port with direction `in` is typed by the conjugated def (~Def), `out`/`inout` by the def.
package FixturePortDefs {
    private import ISQ::*;
    private import SI::*;
    private import ScalarValues::*;

    port def FluidPort { out attribute volume_flow : VolumeFlowRateValue; }
    port def RealSignal { out attribute value : Real; }
    port def BoolSignal { out attribute value : Boolean; }
    port def EventSignal { out attribute occurred : Boolean; }
    port def HeatPort { out attribute heat_flow_rate : HeatFlowRateValue; }
    port def ElectricPort { out attribute current : ElectricCurrentValue; }
    port def MagneticPort { out attribute magnetic_flux : MagneticFluxValue; }

    part def Source { port outlet : FluidPort; port level_out : RealSignal; }
    part def Sink { port inlet : ~FluidPort; port level_in : ~RealSignal; }
}
