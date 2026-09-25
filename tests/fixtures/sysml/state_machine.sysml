// Purpose: R-SYS-5 fixture for the behaviour constructs: IR events as attribute defs used as
// accept triggers, guards over `in` attributes with the timer_expired / in_state calcs, state
// outputs as entry assignments, transition effects (one or several IR actions), a documented
// `history` resume target, transition docs, and an exhibit binding operands to real features
// by full path, since an operand and the port it reads share the IR id as their name.
package FixtureStateMachine {
    private import ISQ::*;
    private import SI::*;
    private import ScalarValues::*;

    calc def timer_expired { in timer : TimeValue; return : Boolean; }
    calc def in_state { in state_ref; return : Boolean; }
    action def start_timer { in timer : TimeValue; }
    action def save_history;
    action def clear_history;

    attribute def start_cmd { doc /* ir: start_cmd | rising edge of ctl_1_start */ }
    attribute def stop_cmd;

    port def RealSignal { out attribute value : Real; }
    port def BoolSignal { out attribute value : Boolean; }
    part def Tank { attribute high_level : LengthValue; }
    part def Controller { attribute wait : TimeValue; }

    state def sm_1 {
        doc /* ir: sm_1 */
        in attribute ctl_1_level : Real;
        in attribute tk_1_high_level : LengthValue;
        out attribute ctl_1_valve : Boolean;
        attribute wait_timer : TimeValue;
        entry; then idle;
        state idle {
            doc /* ir: idle | name: IDLE */
            entry action {
                assign ctl_1_valve := false;
            }
        }
        state fill {
            entry action {
                assign ctl_1_valve := true;
                perform action : start_timer { in timer = wait_timer; }
            }
        }
        state paused {
            entry action {
                perform action : save_history;
            }
        }
        state history {
            doc /* resume target */
        }
        transition tr_start first idle accept start_cmd then fill {
            doc /* ir: tr_start | priority 1 */
        }
        transition tr_high first fill if ctl_1_level >= tk_1_high_level and not in_state(paused) do action : start_timer { in timer = wait_timer; } then idle;
        transition tr_stop first fill accept stop_cmd do action { action : save_history; action : clear_history; } then paused;
        transition tr_resume first paused accept start_cmd then history;
        transition tr_restart first paused accept stop_cmd do action { action : clear_history; action : start_timer { in timer = wait_timer; } } then fill;
        transition tr_done first idle if timer_expired(wait_timer) or true then fill;
    }

    part system {
        part tk_1 : Tank { attribute :>> high_level = 0.5 [m]; }
        part ctl_1 : Controller {
            attribute :>> wait = 10.0 [s];
            port ctl_1_level : ~RealSignal;
            port ctl_1_valve : BoolSignal;
            exhibit state sm_1_behaviour : sm_1 {
                in :>> ctl_1_level = ctl_1.ctl_1_level.value;
                in :>> tk_1_high_level = tk_1.high_level;
                out :>> ctl_1_valve = ctl_1.ctl_1_valve.value;
                attribute :>> wait_timer = ctl_1.wait;
            }
        }
    }
}
