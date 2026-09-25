// Purpose: R-SYS-5 fixture. A connection usage named by IR id joins an out port to a
// conjugated in port and carries a doc body.
package FixtureConnection {
    private import ISQ::*;
    private import SI::*;

    port def FluidPort { out attribute volume_flow : VolumeFlowRateValue; }
    part def Valve { port inlet : ~FluidPort; port outlet : FluidPort; }
    part def Tank { port inlet : ~FluidPort; }

    part system {
        part v_1 : Valve;
        part tk_1 : Tank;
        connection c_1 connect v_1.outlet to tk_1.inlet {
            doc /* ir: c_1 | from: v_1_outlet | to: tk_1_inlet | liquid */
        }
    }
}
