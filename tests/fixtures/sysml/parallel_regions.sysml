// Purpose: R-SYS-5 fixture. IR regions become the parallel sub-states of a `parallel` state
// def, each with its own initial state and the transitions between its own states; a guard
// names a state of another region by its region-qualified path (r_2.c).
package FixtureParallelRegions {
    private import ScalarValues::*;

    calc def in_state { in state_ref; return : Boolean; }

    state def sm_p parallel {
        state r_1 {
            doc /* ir: r_1 */
            entry; then a;
            state a;
            state b;
            transition tr_ab first a if in_state(r_2.c) then b;
        }
        state r_2 {
            entry; then c;
            state c;
        }
    }
}
