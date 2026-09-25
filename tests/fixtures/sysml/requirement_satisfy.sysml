// Purpose: R-SYS-5 fixture. Requirement usages with doc, satisfied by parts, ports,
// connections, attributes and, through an exhibited state, by states and transitions; a name
// that is a SysML keyword is written quoted ('state').
package FixtureRequirementSatisfy {
    private import ISQ::*;
    private import SI::*;
    private import ScalarValues::*;

    port def BoolSignal { out attribute value : Boolean; }
    part def Tank { attribute area : AreaValue; port cmd : ~BoolSignal; }
    part def Controller { port cmd_out : BoolSignal; }
    state def sm_1 {
        entry; then a;
        state a;
        state b;
        transition tr_1 first a then b;
    }

    requirement req_1 {
        doc /* ir: req_1 | tags: R-1 | The tank shall hold water. */
    }
    requirement 'state' {
        doc /* ir: state */
    }

    part system {
        part tk_1 : Tank { attribute :>> area = 1.0 [m^2]; }
        part ctl_1 : Controller {
            exhibit state sm_1_behaviour : sm_1;
        }
        part 'part' : Tank;
        connection c_1 connect ctl_1.cmd_out to tk_1.cmd;
        satisfy req_1 by tk_1;
        satisfy req_1 by tk_1.area;
        satisfy req_1 by tk_1.cmd;
        satisfy req_1 by c_1;
        satisfy req_1 by ctl_1.sm_1_behaviour;
        satisfy req_1 by ctl_1.sm_1_behaviour.a;
        satisfy req_1 by ctl_1.sm_1_behaviour.tr_1;
        satisfy 'state' by 'part';
    }
}
