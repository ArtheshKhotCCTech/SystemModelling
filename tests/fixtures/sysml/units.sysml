// Purpose: R-SYS-5 fixture. Every SI unit of core/units.py with the ISQ value type and unit
// expression generate/sysml.py writes for it; "1" is a plain Real without a unit.
package FixtureUnits {
    private import ISQ::*;
    private import SI::*;
    private import ScalarValues::*;

    part system {
        attribute u_m : LengthValue = 1.0 [m];
        attribute u_m2 : AreaValue = 1.0 [m^2];
        attribute u_m3 : VolumeValue = 1.0 [m^3];
        attribute u_s : TimeValue = 1.0 [s];
        attribute u_kg_s : MassFlowRateValue = 1.0 [kg/s];
        attribute u_m3_s : VolumeFlowRateValue = 1.0 [m^3/s];
        attribute u_one : Real = 1.0;
        attribute u_kg_kg : MassFractionValue = 1.0 [kg/kg];
        attribute u_pa : PressureValue = 1.0 [Pa];
        attribute u_k : ThermodynamicTemperatureValue = 1.0 [K];
        attribute u_w : PowerValue = 1.0 [W];
        attribute u_a : ElectricCurrentValue = 1.0 [A];
        attribute u_v : ElectricPotentialValue = 1.0 [V];
        attribute u_hz : FrequencyValue = 1.0 [Hz];
        attribute u_per_s : FrequencyValue = 1.0 [s^-1];
        attribute u_exponent : LengthValue = 1e-06 [m];
        attribute u_negative : ThermodynamicTemperatureValue = -1.5 [K];
    }
}
