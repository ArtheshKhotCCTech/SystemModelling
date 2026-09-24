// Purpose: minimal SysML v2 model that `specalive doctor` validates to prove the toolchain.
// It covers one of each construct FR-01 names: part, port, connection, attribute with a unit,
// state machine. Confirmed clean (no errors, no warnings) by the SysML v2 Pilot Implementation.
package SpecAliveProbe {
    private import ISQ::*;
    private import SI::*;

    port def FlowPort;

    part def Tank {
        attribute level : LengthValue = 0.5 [m];
        port inlet : FlowPort;
    }

    part def Valve {
        port outlet : ~FlowPort;
    }

    part system {
        part tank : Tank;
        part valve : Valve;
        connection feed connect valve.outlet to tank.inlet;
    }

    state def ValveStates {
        entry; then closed;
        state closed;
        state open;
        transition opening first closed then open;
        transition closing first open then closed;
    }
}
