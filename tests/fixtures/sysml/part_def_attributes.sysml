// Purpose: R-SYS-5 fixture. A part def declares typed attributes and ports; a part usage
// redefines the attributes with effective values and units and carries a doc; a kind with
// dynamic ports declares them on the usage, named by IR port id because a role such as `start`
// clashes with the `start` every part inherits; system-owned values sit on the system part.
package FixturePartDefAttributes {
    private import ISQ::*;
    private import SI::*;
    private import ScalarValues::*;

    port def BoolSignal { out attribute value : Boolean; }

    part def Tank {
        doc /* kind: tank */
        attribute area : AreaValue;
        attribute high_level : LengthValue;
    }
    part def SequenceController;

    part system {
        doc /* ir: system */
        part tk_1 : Tank {
            doc /* ir: tk_1 | name: Tank 1 | tags: T-1, tank1 */
            attribute :>> area = 1.2 [m^2] {
                doc /* ir: tk_1_area | source: src_a @ row 4 */
            }
        }
        part ctl_1 : SequenceController {
            port ctl_1_valve1 : BoolSignal {
                doc /* ir: ctl_1_valve1 */
            }
            port ctl_1_start : ~BoolSignal;
        }
        attribute stop_time : TimeValue = 900.0 [s] {
            doc /* ir: system_stop_time */
        }
        attribute press_times : TimeValue[*] = (20.0 [s], 280.0 [s]);
    }
}
