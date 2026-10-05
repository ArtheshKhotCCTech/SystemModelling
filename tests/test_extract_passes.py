# Purpose: pins the LLM extraction passes (FR-04 requirements 1-4, R-EXT-4) with the model faked:
# chunk ids and the fixed pass order, batching under a size cap, verbatim quote checking (a
# fragment whose quote is not in its chunk is discarded and counted, acceptance 8), chunk roles
# carried onto fragments, the catalogue in the prompt, the glossary handed to later passes, and
# the behaviour pass keeping only transitions whose guards, actions and ids check out.
import pytest

from _extract_support import (
    FakeLLM,
    bundle,
    chunk,
    empty_behaviour,
    empty_reply,
    part,
    source,
)
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import Part, Port
from specalive.extract.extract import (
    BehaviourContext,
    batches,
    build_state_machine,
    index_chunks,
    pass_order,
    run_structure_passes,
    structure_prompt,
    verify_quote,
)
from specalive.extract.fragments import BehaviourReply


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


def _two_sources():
    return bundle(
        [source("src_b", "requirement_spec"), source("src_a", "informal_note"),
         source("src_c", "register"), source("src_d", "design_note", status="unread")],
        [chunk("src_b", "line 1", "The tank TK-9 has an area of 2 m2."),
         chunk("src_a", "line 1", "Operator says TK-9 is often full."),
         chunk("src_b", "line 3", "Valve XV-9 fills TK-9."),
         chunk("src_c", "sheet S, row 2", "Tag: TK-9 | Alias: tankA", kind="table_row",
               role="change_record", fields={"Tag": "TK-9", "Alias": "tankA"})],
    )


def test_chunk_ids_are_source_and_position_within_source():
    refs = index_chunks(_two_sources())
    assert list(refs) == ["src_b#0", "src_a#0", "src_b#1", "src_c#0"]
    assert refs["src_b#1"].chunk.text == "Valve XV-9 fills TK-9."


def test_chunk_role_defaults_to_source_role():
    refs = index_chunks(_two_sources())
    assert refs["src_b#0"].role == "requirement_spec"
    assert refs["src_c#0"].role == "change_record"


def test_pass_order_is_fixed_register_first_and_skips_unread():
    order = [s.id for s in pass_order(_two_sources())]
    assert order == ["src_c", "src_b", "src_a"]


def test_batches_are_cut_under_the_size_cap():
    b = bundle([source("s", "design_note")],
               [chunk("s", f"line {i}", "x" * 40) for i in range(10)])
    refs = list(index_chunks(b).values())
    groups = batches(refs, cap=100)
    assert [len(g) for g in groups] == [2, 2, 2, 2, 2]
    assert [r for g in groups for r in g] == refs
    assert batches(refs, cap=10) == [[r] for r in refs]  # an oversized chunk still gets a batch


def test_verify_quote_exact_and_whitespace_tolerant_but_returns_the_source_text():
    text = "The tank  TK-9 has\nan area of 2 m2."
    assert verify_quote("TK-9 has", text) == "TK-9 has"
    assert verify_quote("tank TK-9 has an area", text) == "tank  TK-9 has\nan area"
    assert verify_quote("an area of 3 m2", text) is None
    assert verify_quote("", text) is None
    assert verify_quote("x" * 301, "x" * 400) is None  # longer than a TraceLink allows


def test_prompt_lists_catalogue_kinds_with_descriptions_and_roles(catalogue):
    prompt = structure_prompt(catalogue)
    for kind in catalogue.kinds:
        assert kind in prompt
        assert catalogue.entry(kind).description in prompt
    for role in ("change_record", "review_decision", "legacy_model"):
        assert role in prompt
    assert "verbatim" in prompt and "chunk_id" in prompt


def test_fragment_with_quote_not_in_its_chunk_is_discarded_and_counted(catalogue):
    b = _two_sources()
    reply = empty_reply(parts=[
        part("src_b#0", "The tank TK-9 has an area", "TK-9", "tank"),
        part("src_b#0", "The tank TK-9 holds 5 m3", "TK-9", "tank"),  # not in the chunk
        part("src_x#0", "The tank", "TK-9", "tank"),                  # no such chunk
    ])
    llm = FakeLLM({"FragmentReply": lambda text: reply if "src_b#0" in text else empty_reply()})
    passes = run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources})
    assert len(passes.parts) == 1
    assert passes.parts[0].quote == "The tank TK-9 has an area"
    reasons = sorted(d.reason for d in passes.discarded)
    assert len(reasons) == 2
    assert any("not found in chunk" in r for r in reasons)
    assert any("not in this pass" in r for r in reasons)
    assert all(d.kind == "part" for d in passes.discarded)


def test_fragments_carry_chunk_role_date_and_mapped_source_id(catalogue):
    b = bundle([source("src_c", "register", date="2026-01-02")],
               [chunk("src_c", "sheet S, row 2", "Tag: TK-9 | Alias: tankA", kind="table_row",
                      role="change_record")])
    llm = FakeLLM({"FragmentReply": [empty_reply(parts=[
        part("src_c#0", "Tag: TK-9 | Alias: tankA", "TK-9", "tank", aliases=["tankA"])])]})
    passes = run_structure_passes(b, llm, catalogue, {"src_c": "reg_1"})
    f = passes.parts[0]
    assert (f.role, f.date, f.source_id, f.locator) == ("change_record", "2026-01-02", "reg_1",
                                                         "sheet S, row 2")
    assert f.trace.source_id == "reg_1"


def test_glossary_carries_names_from_earlier_passes(catalogue):
    b = _two_sources()
    first = empty_reply(parts=[part("src_c#0", "Tag: TK-9 | Alias: tankA", "TK-9", "tank",
                                    aliases=["tankA"])])
    llm = FakeLLM({"FragmentReply": [first, empty_reply(), empty_reply()]})
    run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources})
    assert len(llm.calls) == 3  # one per readable source, each fits one batch
    assert "tankA" not in llm.calls[0][1].split("GLOSSARY")[1].split("CHUNKS")[0]
    assert "tankA" in llm.calls[1][1]
    assert all(call[0] == llm.calls[0][0] for call in llm.calls)  # the prompt never varies


def test_behaviour_chunk_ids_are_collected_only_when_valid(catalogue):
    b = _two_sources()
    llm = FakeLLM({"FragmentReply": lambda text: empty_reply(
        behaviour_chunk_ids=["src_b#1", "src_zz#4"]) if "src_b#1" in text else empty_reply()})
    passes = run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources})
    assert [r.chunk_id for r in passes.behaviour_refs] == ["src_b#1"]


def test_system_name_comes_from_the_first_pass_that_gives_one(catalogue):
    b = _two_sources()
    llm = FakeLLM({"FragmentReply": [empty_reply(), empty_reply(system_name="Mixer"),
                                     empty_reply(system_name="Other")]})
    passes = run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources})
    assert passes.system_name == "Mixer"


# --- behaviour pass ----------------------------------------------------------------------

LOGIC = "In FILL the inlet valve is open until the level reaches high_level, then wait."


def _ctx():
    owner = Part(id="ctl", kind="sequence_controller", name="Controller", trace=[], ports=[
        Port(id="ctl_level", role="level", direction="in", domain="signal_real"),
        Port(id="ctl_go", role="go", direction="in", domain="signal_bool"),
        Port(id="ctl_valve", role="valve", direction="out", domain="signal_bool")])
    b = bundle([source("src_n", "design_note")], [chunk("src_n", "line 4", LOGIC)])
    return BehaviourContext(owner=owner, operands={"ctl_level", "ctl_go", "ctl_valve", "high",
                                                   "delay"},
                            parameters={"high", "delay"}, refs=index_chunks(b),
                            source_map={"src_n": "note"}, taken_ids={"ctl", "high", "delay"})


def _state(sid, outputs=None, legacy=()):
    return {"chunk_id": "src_n#0", "quote": "In FILL the inlet valve is open", "id": sid,
            "name": sid.upper(), "legacy_names": list(legacy), "entry_actions": [],
            "outputs": [{"port_id": k, "value": v} for k, v in (outputs or {}).items()]}


def _tr(frm, to, priority, guard=None, trigger=None, actions=(), quote=LOGIC[:40]):
    return {"chunk_id": "src_n#0", "quote": quote, "from_state": frm, "to_state": to,
            "trigger_event": trigger, "guard": guard, "actions": list(actions),
            "priority": priority}


def _machine(**overrides):
    reply = empty_behaviour(
        initial_state="idle",
        events=[{"id": "go_cmd", "port_id": "ctl_go", "edge": "rising"}],
        timers=[{"id": "delay_timer", "duration_parameter_id": "delay"}],
        states=[_state("idle", {"ctl_valve": False}), _state("fill", {"ctl_valve": True},
                                                             legacy=["FILLING"]),
                _state("hold")],
        transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                     _tr("fill", "hold", 1, guard="ctl_level >= high",
                         actions=["start_timer(delay_timer)"]),
                     _tr("hold", "idle", 1, guard="timer_expired(delay_timer)")])
    reply.update(overrides)
    return BehaviourReply.model_validate(reply)


def test_behaviour_reply_becomes_a_traced_state_machine():
    result = build_state_machine(_machine(), _ctx())
    sm = result.machine
    assert sm is not None and result.discarded == []
    assert sm.owner == "ctl" and sm.initial == "idle"
    assert [s.id for s in sm.states] == ["idle", "fill", "hold"]
    assert sm.states[1].tags == ["FILLING"]  # legacy name kept as an alias (requirement 7)
    assert sm.states[1].outputs == {"ctl_valve": True}
    assert [t.id for t in sm.transitions] == ["tr_idle_1", "tr_fill_1", "tr_hold_1"]
    assert sm.trace and sm.trace[0].source_id == "note"


def test_behaviour_items_that_do_not_check_out_are_discarded_not_repaired():
    reply = _machine(transitions=[
        _tr("idle", "fill", 1, trigger="go_cmd"),
        _tr("fill", "hold", 1, guard="ctl_level >= nowhere"),         # unknown operand
        _tr("fill", "hold", 2, guard="ctl_level >="),                 # does not parse
        _tr("fill", "idle", 3, actions=["start_timer(nope)"]),        # unknown timer
        _tr("hold", "idle", 1, trigger="go_cmd"),
        _tr("hold", "fill", 1, trigger="go_cmd"),                     # priority reused
        _tr("hold", "gone", 2, trigger="go_cmd"),                     # unknown state
        _tr("idle", "hold", 2, trigger="go_cmd", quote="not in the text at all"),
    ])
    result = build_state_machine(reply, _ctx())
    assert [t.id for t in result.machine.transitions] == ["tr_idle_1", "tr_hold_1"]
    assert len(result.discarded) == 6
    assert all(d.kind == "transition" for d in result.discarded)


def test_history_target_without_save_history_is_dropped():
    reply = _machine(transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                                  _tr("hold", "history", 1, trigger="go_cmd")])
    result = build_state_machine(reply, _ctx())
    assert [t.to for t in result.machine.transitions] == ["fill"]
    assert any("save_history" in d.reason for d in result.discarded)


def test_invalid_ids_events_timers_and_outputs_are_discarded():
    reply = _machine(
        events=[{"id": "go_cmd", "port_id": "ctl_go", "edge": "rising"},
                {"id": "bad", "port_id": "ctl_valve", "edge": "rising"}],   # an output port
        timers=[{"id": "delay_timer", "duration_parameter_id": "delay"},
                {"id": "t2", "duration_parameter_id": "missing"}],
        states=[_state("idle", {"ctl_valve": False, "ctl_level": True}),    # input port output
                _state("fill", {"ctl_valve": True}), _state("hold"), _state("Bad Name"),
                _state("ctl")])                                              # id already taken
    result = build_state_machine(reply, _ctx())
    sm = result.machine
    assert [e.id for e in sm.events] == ["go_cmd"]
    assert [t.id for t in sm.timers] == ["delay_timer"]
    assert [s.id for s in sm.states] == ["idle", "fill", "hold"]
    assert sm.states[0].outputs == {"ctl_valve": False}
    assert len(result.discarded) == 5


def test_no_machine_when_the_initial_state_is_not_kept():
    result = build_state_machine(_machine(initial_state="nowhere"), _ctx())
    assert result.machine is None
    assert any("initial" in d.reason for d in result.discarded)


def test_checks_are_kept_only_when_their_condition_checks_out():
    reply = _machine(checks=[
        {"criterion_tag": "AC-1", "mode": "always", "condition": "ctl_level <= high",
         "start_s": None, "end_s": None},
        {"criterion_tag": "AC-2", "mode": "at", "condition": "nowhere > 1", "start_s": 5.0,
         "end_s": None}])
    result = build_state_machine(reply, _ctx())
    assert set(result.checks) == {"AC-1"}
    assert result.checks["AC-1"].condition == "ctl_level <= high"
    assert any(d.kind == "check" for d in result.discarded)


def test_batch_whose_reply_is_cut_off_is_split_and_retried(catalogue):
    from specalive.llm.client import LLMIncomplete

    b = bundle([source("s", "design_note")],
               [chunk("s", "line 1", "Tank TK-1."), chunk("s", "line 2", "Tank TK-2."),
                chunk("s", "line 3", "Tank TK-3.")])

    def reply(text):
        ids = [c for c in ("s#0", "s#1", "s#2") if f"[{c}]" in text]
        if len(ids) > 1 or "s#2" in ids:  # too long unless alone; s#2 is too long even alone
            raise LLMIncomplete("incomplete reply (finish_reason=length)")
        n = int(ids[0][-1]) + 1
        return empty_reply(parts=[part(ids[0], f"Tank TK-{n}", f"TK-{n}", "tank")])

    passes = run_structure_passes(b, FakeLLM({"FragmentReply": reply}), catalogue, {"s": "s"})
    assert [f.fragment.tag for f in passes.parts] == ["TK-1", "TK-2"]
    assert [(d.chunk_id, d.kind) for d in passes.discarded] == [("s#2", "chunk")]
    assert "too long" in passes.discarded[0].reason


def test_behaviour_pass_asks_once_more_with_the_problems_and_keeps_the_better_answer(catalogue):
    from specalive.extract.extract import BEHAVIOUR_ATTEMPTS, Passes, run_behaviour_passes
    from specalive.extract.fragments import Draft, ExtractReport

    ctx = _ctx()
    draft = Draft(name="m", description="d", parts=[ctx.owner.model_copy(update={
        "trace": [{"source_id": "note", "locator": "line 4", "quote": LOGIC}]})])
    bad = _machine(transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                                _tr("fill", "hold", 1, guard="ctl_level >= nowhere")])
    good = _machine(transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                                 _tr("fill", "hold", 1, guard="ctl_level >= 1")])
    replies = [bad.model_dump(), good.model_dump()]
    llm = FakeLLM({"BehaviourReply": lambda text: replies[1] if "PROBLEMS" in text else replies[0]})
    passes = Passes(behaviour_refs=list(ctx.refs.values()))
    report = ExtractReport()
    run_behaviour_passes(passes, draft, llm, ctx.refs, ctx.source_map, report)
    # every attempt is used: the draft has no `delay` parameter, so each loses the timer
    assert len(llm.calls) == BEHAVIOUR_ATTEMPTS
    assert "nowhere" in llm.calls[1][1].split("PROBLEMS")[1]
    sm = draft.state_machines[0]
    assert [t.id for t in sm.transitions] == ["tr_idle_1", "tr_fill_1"]
    assert any("attempt 1" in d.reason for d in report.discarded_fragments)


# --- progress (FR-09 requirement 2) ------------------------------------------------------

def test_structure_passes_report_source_n_of_m(catalogue):
    b = _two_sources()
    seen = []
    llm = FakeLLM({"FragmentReply": [empty_reply()]})
    run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources}, progress=seen.append)
    assert [m.split(":")[0] for m in seen] == ["source 1 of 3", "source 2 of 3", "source 3 of 3"]
    assert "src_c" in seen[0]  # register first, named by its path


def test_behaviour_pass_reports_its_controller_and_attempt(catalogue):
    from specalive.extract.extract import Passes, run_behaviour_passes
    from specalive.extract.fragments import Draft, ExtractReport

    ctx = _ctx()
    draft = Draft(name="m", description="d", parts=[ctx.owner.model_copy(update={
        "trace": [{"source_id": "note", "locator": "line 4", "quote": LOGIC}]})])
    reply = _machine(transitions=[_tr("idle", "fill", 1, trigger="go_cmd")])
    llm = FakeLLM({"BehaviourReply": [reply.model_dump()]})
    seen = []
    run_behaviour_passes(Passes(behaviour_refs=list(ctx.refs.values())), draft, llm, ctx.refs,
                         ctx.source_map, ExtractReport(), progress=seen.append)
    # one line per LLM call, before the call, naming the controller
    assert seen == [f"behaviour of ctl: attempt {n}" for n in range(1, len(llm.calls) + 1)]


# --- reads through the wiring (phase 9) --------------------------------------------------

def test_guard_reading_a_wired_output_reads_the_controller_input_instead():
    import dataclasses

    ctx = dataclasses.replace(_ctx(), operands=_ctx().operands | {"lt_9_out"},
                              via={"lt_9_out": "ctl_level"})
    reply = _machine(transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                                  _tr("fill", "hold", 1, guard="lt_9_out >= high")])
    sm = build_state_machine(reply, ctx).machine
    assert next(t for t in sm.transitions if t.from_ == "fill").guard == "ctl_level >= high"


def test_guard_rewrite_touches_whole_ids_only():
    from specalive.extract.extract import through_wiring

    via = {"lt_9_out": "ctl_level"}
    assert through_wiring("lt_9_out >= high and lt_9_out_b < 1", via) == \
        "ctl_level >= high and lt_9_out_b < 1"
    assert through_wiring("in_state(lt_9_out)", {}) == "in_state(lt_9_out)"


def test_wiring_map_holds_only_outputs_wired_to_exactly_one_controller_input():
    from specalive.core.ir import Connection
    from specalive.extract.extract import controller_inputs_by_source

    owner = _ctx().owner
    wire = [Connection(id="a", from_port="lt_9_out", to_port="ctl_level", medium_or_signal="s"),
            Connection(id="b", from_port="pb_out", to_port="ctl_go", medium_or_signal="s"),
            Connection(id="c", from_port="pb_out", to_port="ctl_level", medium_or_signal="s"),
            Connection(id="d", from_port="ctl_valve", to_port="xv_cmd", medium_or_signal="s")]
    assert controller_inputs_by_source(owner, wire) == {"lt_9_out": "ctl_level"}


def test_a_history_return_loses_its_clear_history_but_keeps_the_resume():
    # clear_history before going back to the saved state would resume nothing (phase 9, L1)
    reply = _machine(states=[_state("idle", {"ctl_valve": False}),
                             _state("fill", {"ctl_valve": True}), _state("paused")],
                     transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                                  _tr("fill", "paused", 1, actions=["save_history"]),
                                  _tr("paused", "history", 1, trigger="go_cmd",
                                      actions=["clear_history"])])
    result = build_state_machine(reply, _ctx())
    # phase 9 closure: the action goes, the resume stays (it was the whole transition before,
    # which lost the L1 resume on every attempt)
    [back] = [t for t in result.machine.transitions if t.to == "history"]
    assert back.actions == []
    assert any("clear_history" in d.reason and d.kind == "action" for d in result.discarded)


# --- honest checks and priority collisions (phase 9 closure) -----------------------------

def _ctx_with_criteria(**criteria):
    import dataclasses

    from specalive.extract.fragments import name_key

    return dataclasses.replace(_ctx(), criteria={name_key(k): v for k, v in criteria.items()})


def test_a_check_window_the_criterion_does_not_state_is_discarded():
    # the L1 finding: "before the first transfer begins" came back as "at 20 s"
    ctx = _ctx_with_criteria(ac_1="The valve shall be closed from 220 s until 280 s.",
                             ac_2="The level shall reach high before the transfer begins.",
                             ac_3="After the drain the valve shall stay closed.")
    reply = _machine(checks=[
        {"criterion_tag": "AC-1", "mode": "always", "condition": "ctl_valve == false",
         "start_s": 220.0, "end_s": 280.0},
        {"criterion_tag": "AC-2", "mode": "at", "condition": "ctl_level >= high",
         "start_s": 20.0, "end_s": None},
        {"criterion_tag": "AC-3", "mode": "always", "condition": "ctl_valve == false",
         "start_s": None, "end_s": 900.0}])
    result = build_state_machine(reply, ctx)
    assert set(result.checks) == {"AC-1"}
    assert not any(d.kind == "check" for d in result.discarded)  # omitted, nothing to fix
    dropped = {d.quote: d.reason for d in result.omitted if d.kind == "check"}
    assert set(dropped) == {"ctl_level >= high", "ctl_valve == false"}
    assert "20 s" in dropped["ctl_level >= high"] and "900 s" in dropped["ctl_valve == false"]


def test_a_stated_time_matches_as_a_number_not_as_part_of_an_id():
    ctx = _ctx_with_criteria(ac_1="T1 shall be full at 20.0 s.", ac_2="T1 shall be full.")
    reply = _machine(checks=[
        {"criterion_tag": "ac_1", "mode": "at", "condition": "ctl_level >= high",
         "start_s": 20.0, "end_s": None},
        {"criterion_tag": "ac_2", "mode": "at", "condition": "ctl_level >= high",
         "start_s": 1.0, "end_s": None}])  # the 1 of "T1" is not a stated time
    assert set(build_state_machine(reply, ctx).checks) == {"ac_1"}


def test_checks_without_criterion_text_keep_the_old_rules():
    reply = _machine(checks=[{"criterion_tag": "AC-9", "mode": "at", "condition": "ctl_level >= high",
                              "start_s": 20.0, "end_s": None}])
    assert set(build_state_machine(reply, _ctx()).checks) == {"AC-9"}


def test_the_prompt_leaves_event_timed_criteria_unchecked():
    from specalive.extract.extract import BEHAVIOUR_PROMPT

    assert "only an event" in BEHAVIOUR_PROMPT and "never stand in the" in BEHAVIOUR_PROMPT
    assert "holds for the whole run" in BEHAVIOUR_PROMPT


def _commands_ctx():
    import dataclasses

    ctx = _ctx()
    owner = ctx.owner.model_copy(update={"ports": ctx.owner.ports + [
        Port(id="ctl_halt", role="halt", direction="in", domain="signal_bool")]})
    return dataclasses.replace(ctx, owner=owner, operands=ctx.operands | {"ctl_halt"})


def _commands_machine(stop_priority):
    return _machine(
        events=[{"id": "go_cmd", "port_id": "ctl_go", "edge": "rising"},
                {"id": "halt_cmd", "port_id": "ctl_halt", "edge": "rising"}],
        transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                     _tr("fill", "idle", 1, trigger="halt_cmd"),
                     _tr("fill", "hold", stop_priority, trigger="go_cmd"),
                     _tr("hold", "idle", 1, guard="timer_expired(delay_timer)")])


def test_a_priority_collision_names_the_transition_it_collides_with():
    result = build_state_machine(_commands_machine(stop_priority=1), _commands_ctx())
    [d] = [d for d in result.discarded if d.kind == "transition"]
    assert "halt_cmd -> idle" in d.reason and "precedence" in d.reason
    assert result.collisions == [("fill", 1, "halt_cmd -> idle", "go_cmd -> hold")]


def test_a_collision_left_after_every_attempt_becomes_a_question(catalogue):
    from specalive.extract.extract import BEHAVIOUR_ATTEMPTS, Passes, run_behaviour_passes
    from specalive.extract.fragments import Draft, ExtractReport

    ctx = _commands_ctx()
    draft = Draft(name="m", description="d", parts=[ctx.owner.model_copy(update={
        "trace": [{"source_id": "note", "locator": "line 4", "quote": LOGIC}]})])
    llm = FakeLLM({"BehaviourReply": lambda text: _commands_machine(1).model_dump()})
    run_behaviour_passes(Passes(behaviour_refs=list(ctx.refs.values())), draft, llm, ctx.refs,
                         ctx.source_map, ExtractReport())
    assert BEHAVIOUR_ATTEMPTS == 3 and len(llm.calls) == 3
    [q] = draft.questions
    assert q.affects == ["ctl"] and set(q.options) == {"halt_cmd -> idle", "go_cmd -> hold"}
    assert "fill" in q.text and q.default_if_unanswered is None


def test_a_collision_fixed_on_retry_leaves_no_question(catalogue):
    from specalive.extract.extract import Passes, run_behaviour_passes
    from specalive.extract.fragments import Draft, ExtractReport

    ctx = _commands_ctx()
    draft = Draft(name="m", description="d", parts=[ctx.owner.model_copy(update={
        "trace": [{"source_id": "note", "locator": "line 4", "quote": LOGIC}]})])
    llm = FakeLLM({"BehaviourReply": lambda text: _commands_machine(
        2 if "PROBLEMS" in text else 1).model_dump()})
    run_behaviour_passes(Passes(behaviour_refs=list(ctx.refs.values())), draft, llm, ctx.refs,
                         ctx.source_map, ExtractReport())
    assert len(llm.calls) >= 2 and draft.questions == []
    assert [t.priority for t in draft.state_machines[0].transitions if t.from_ == "fill"] == [1, 2]


# --- command precedence numbers the priorities (F2b) -------------------------------------

PRECEDENCE = "In FILL the inlet valve is open"  # a verbatim piece of LOGIC


def _precedence_machine(events, quote=PRECEDENCE, halt=1, go=1, guard=1):
    return _machine(
        events=[{"id": "go_cmd", "port_id": "ctl_go", "edge": "rising"},
                {"id": "halt_cmd", "port_id": "ctl_halt", "edge": "rising"}],
        command_precedence={"chunk_id": "src_n#0", "quote": quote, "events": events},
        transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                     _tr("fill", "hold", guard, guard="ctl_level >= high",
                         actions=["start_timer(delay_timer)"]),
                     _tr("fill", "idle", halt, trigger="halt_cmd"),
                     _tr("fill", "idle", go, trigger="go_cmd")])


def test_stated_command_precedence_numbers_commands_then_guards():
    result = build_state_machine(_precedence_machine(["halt_cmd", "go_cmd"]), _commands_ctx())
    assert result.discarded == [] and result.collisions == []
    fill = sorted((t.priority, t.trigger or t.guard) for t in result.machine.transitions
                  if t.from_ == "fill")
    assert fill == [(1, "halt_cmd"), (2, "go_cmd"), (3, "ctl_level >= high")]
    assert [t.id for t in result.machine.transitions if t.from_ == "fill"] == [
        "tr_fill_3", "tr_fill_1", "tr_fill_2"]  # in reply order, named by the new numbers
    assert any(t.quote == PRECEDENCE for t in result.machine.trace)


def test_a_precedence_naming_an_unkept_event_drops_that_name_only():
    result = build_state_machine(_precedence_machine(["halt_cmd", "nope", "go_cmd"]),
                                 _commands_ctx())
    assert [d.quote for d in result.discarded] == ["nope"]
    assert result.collisions == []


def test_an_untraced_precedence_is_discarded_and_the_reply_numbers_stand():
    result = build_state_machine(_precedence_machine(["halt_cmd", "go_cmd"], quote="not there"),
                                 _commands_ctx())
    assert any(d.kind == "command precedence" for d in result.discarded)
    assert [c[:2] for c in result.collisions] == [("fill", 1), ("fill", 1)]


def test_commands_the_precedence_leaves_out_keep_their_reply_order_after_listed_ones():
    result = build_state_machine(_precedence_machine(["halt_cmd"], go=2, guard=3),
                                 _commands_ctx())
    fill = sorted((t.priority, t.trigger or t.guard) for t in result.machine.transitions
                  if t.from_ == "fill")
    assert fill == [(1, "halt_cmd"), (2, "go_cmd"), (3, "ctl_level >= high")]


# --- where a check's window comes from (F1b) ---------------------------------------------

def _check(start_s, end_s, start_basis, end_basis, mode="always"):
    return {"criterion_tag": "AC-1", "mode": mode, "condition": "ctl_valve == false",
            "start_s": start_s, "end_s": end_s, "start_basis": start_basis,
            "end_basis": end_basis}


@pytest.mark.parametrize("check, kept", [
    (_check(220.0, 280.0, "stated_time", "stated_time"), True),
    (_check(None, None, "run_bound", "run_bound"), True),
    (_check(None, 280.0, "event", "stated_time"), False),        # after the drain ... 280 s
    (_check(220.0, None, "stated_time", "event"), False),
    (_check(None, 280.0, "stated_time", "stated_time"), False),  # a stated time needs a value
    (_check(5.0, 280.0, "run_bound", "stated_time"), False),     # a run bound has no value
    # an 'at' check has no end: its end basis is not judged (the L1 START at 280 s)
    (_check(280.0, None, "stated_time", "event", mode="at"), True),
    (_check(None, None, "event", "event", mode="at"), False),
])
def test_a_check_is_kept_only_when_each_bound_is_a_stated_time_or_the_run(check, kept):
    ctx = _ctx_with_criteria(ac_1="The valve shall be closed from 220 s until 280 s.")
    result = build_state_machine(_machine(checks=[check]), ctx)
    assert (set(result.checks) == {"AC-1"}) is kept
    if not kept:
        assert any(d.kind == "check" for d in result.discarded + result.omitted)
    # an event-timed bound is a correct omission: reported, but never sent back to be fixed
    judged = (check["start_basis"],) if check["mode"] == "at" else (
        check["start_basis"], check["end_basis"])
    if "event" in judged:
        assert [d.kind for d in result.omitted] == ["check"] and result.discarded == []


def test_the_prompt_asks_for_precedence_and_window_bases():
    from specalive.extract.extract import BEHAVIOUR_PROMPT

    assert "command_precedence" in BEHAVIOUR_PROMPT
    assert "start_basis" in BEHAVIOUR_PROMPT and "end_basis" in BEHAVIOUR_PROMPT


# --- a controller output or event on another part's port wires it (F4) -------------------

VALVE_LOGIC = "PLC opens XV-7 when the operator presses GO-7, then waits."


def _foreign_parts():
    valve = Part(id="xv_7", kind="on_off_valve", name="Valve", tags=["XV-7", "inlet valve"],
                 trace=[], ports=[Port(id="xv_7_cmd_in", role="cmd_in", direction="in",
                                       domain="signal_bool")])
    button = Part(id="go_7", kind="command_button", name="Go", tags=["GO-7"], trace=[],
                  ports=[Port(id="go_7_cmd_out", role="cmd_out", direction="out",
                              domain="signal_bool")])
    other = Part(id="xv_8", kind="on_off_valve", name="Valve", tags=["XV-8"], trace=[],
                 ports=[Port(id="xv_8_cmd_in", role="cmd_in", direction="in",
                             domain="signal_bool")])
    return [valve, button, other]


def _foreign_ctx(connected=()):
    import dataclasses

    b = bundle([source("src_n", "design_note")], [chunk("src_n", "line 4", LOGIC),
                                                  chunk("src_n", "line 5", VALVE_LOGIC)])
    ctx = _ctx()
    return dataclasses.replace(
        ctx, refs=index_chunks(b),
        operands=ctx.operands | {"xv_7_cmd_in", "go_7_cmd_out", "xv_8_cmd_in"},
        others={q.id: (p, q) for p in _foreign_parts() for q in p.ports},
        connected=set(connected))


def _foreign_machine():
    return _machine(
        events=[{"id": "go_cmd", "port_id": "go_7_cmd_out", "edge": "rising"}],
        timers=[],
        states=[_state("idle", {"xv_7_cmd_in": False, "xv_8_cmd_in": False}),
                _state("fill", {"xv_7_cmd_in": True})],
        transitions=[{**_tr("idle", "fill", 1, trigger="go_cmd", quote=VALVE_LOGIC),
                      "chunk_id": "src_n#1"}])


def test_a_named_part_whose_port_the_reply_uses_is_wired_to_a_new_controller_port():
    result = build_state_machine(_foreign_machine(), _foreign_ctx())
    assert [(p.id, p.direction) for p in result.ports] == [("ctl_go_7", "in"),
                                                            ("ctl_inlet_valve", "out")]
    assert sorted((c.from_port, c.to_port) for c in result.connections) == [
        ("ctl_inlet_valve", "xv_7_cmd_in"), ("go_7_cmd_out", "ctl_go_7")]
    assert all(any(VALVE_LOGIC == t.quote for t in c.trace) for c in result.connections)
    sm = result.machine
    assert [e.port for e in sm.events] == ["ctl_go_7"]
    assert sm.states[1].outputs == {"ctl_inlet_valve": True}
    # XV-8 is never named by a kept quote: its output is dropped, not wired
    assert any("xv_8_cmd_in" in d.quote for d in result.discarded)


def test_an_already_connected_foreign_port_is_not_wired_again():
    result = build_state_machine(_foreign_machine(), _foreign_ctx(connected={"xv_7_cmd_in"}))
    assert all(c.to_port != "xv_7_cmd_in" for c in result.connections)
    assert any("xv_7_cmd_in" in d.quote for d in result.discarded)


def test_the_behaviour_pass_adds_the_new_ports_and_connections_to_the_draft(catalogue):
    from specalive.extract.extract import Passes, run_behaviour_passes
    from specalive.extract.fragments import Draft, ExtractReport

    ctx = _foreign_ctx()
    trace = [{"source_id": "note", "locator": "line 5", "quote": VALVE_LOGIC}]
    parts = [ctx.owner.model_copy(update={"trace": trace})]
    parts += [p.model_copy(update={"trace": trace}) for p in _foreign_parts()]
    draft = Draft(name="m", description="d", parts=parts)
    llm = FakeLLM({"BehaviourReply": lambda text: _foreign_machine().model_dump()})
    run_behaviour_passes(Passes(behaviour_refs=list(ctx.refs.values())), draft, llm, ctx.refs,
                         ctx.source_map, ExtractReport())
    owner = next(p for p in draft.parts if p.id == "ctl")
    assert {"ctl_go_7", "ctl_inlet_valve"} <= {q.id for q in owner.ports}
    assert {"xv_7_cmd_in", "ctl_go_7"} <= {c.to_port for c in draft.connections}
    assert draft.state_machines[0].states[1].outputs == {"ctl_inlet_valve": True}


# --- a rule "from any state" is expanded by code (phase 9 closure, option A) -------------

def _any_machine(except_states):
    return _machine(
        states=[_state("idle", {"ctl_valve": False}), _state("fill", {"ctl_valve": True}),
                _state("hold"), _state("stopped")],
        transitions=[_tr("idle", "fill", 2, trigger="go_cmd"),
                     {**_tr("*", "stopped", 1, trigger="go_cmd"),
                      "except_states": except_states},
                     _tr("stopped", "idle", 1, guard="ctl_level <= high")])


def test_a_from_any_state_rule_becomes_one_transition_per_other_state():
    result = build_state_machine(_any_machine(["hold"]), _ctx())
    assert result.discarded == []
    into = sorted(t.from_ for t in result.machine.transitions if t.to == "stopped")
    # every kept state except the listed one and the rule's own target
    assert into == ["fill", "idle"]
    assert {t.priority for t in result.machine.transitions if t.to == "stopped"} == {1}


def test_an_except_state_that_is_not_kept_is_reported_and_the_rest_expands():
    result = build_state_machine(_any_machine(["nowhere"]), _ctx())
    assert [d.quote for d in result.discarded] == ["nowhere"]
    into = sorted(t.from_ for t in result.machine.transitions if t.to == "stopped")
    assert into == ["fill", "hold", "idle"]


def test_the_prompt_offers_the_from_any_state_form():
    from specalive.extract.extract import BEHAVIOUR_PROMPT

    assert '"*"' in BEHAVIOUR_PROMPT and "except_states" in BEHAVIOUR_PROMPT


def test_an_omitted_check_is_reported_but_never_asked_about_again(catalogue):
    from specalive.extract.extract import Passes, run_behaviour_passes
    from specalive.extract.fragments import Draft, ExtractReport

    ctx = _ctx()
    draft = Draft(name="m", description="d", parameters=[], parts=[ctx.owner.model_copy(update={
        "trace": [{"source_id": "note", "locator": "line 4", "quote": LOGIC}]})])
    reply = _machine(timers=[], transitions=[_tr("idle", "fill", 1, trigger="go_cmd")],
                     checks=[_check(None, 280.0, "event", "stated_time")])
    llm = FakeLLM({"BehaviourReply": lambda text: reply.model_dump()})
    report = ExtractReport()
    run_behaviour_passes(Passes(behaviour_refs=list(ctx.refs.values())), draft, llm, ctx.refs,
                         ctx.source_map, report)
    assert len(llm.calls) == 1
    assert [d.kind for d in report.discarded_fragments] == ["check"]


# --- adversarial findings: events and timers that cannot mean what they say ---------------

def test_an_event_on_a_real_input_is_discarded():
    # heated-tank finding: "level reaches 0.9" as an event on the level input gave edge() of a
    # continuous signal; a threshold is a guard, an event needs a Boolean command input
    reply = _machine(events=[{"id": "go_cmd", "port_id": "ctl_go", "edge": "rising"},
                             {"id": "level_up", "port_id": "ctl_level", "edge": "rising"}])
    result = build_state_machine(reply, _ctx())
    assert [e.id for e in result.machine.events] == ["go_cmd"]
    [d] = [d for d in result.discarded if d.kind == "event"]
    assert "signal_real" in d.reason


def test_a_timer_whose_duration_is_not_a_time_is_discarded():
    # contradiction-spec finding: a timer timed by the tank's area
    import dataclasses

    ctx = dataclasses.replace(_ctx(), parameters={"high", "delay"},
                              parameter_units={"high": "m", "delay": "s"})
    reply = _machine(timers=[{"id": "delay_timer", "duration_parameter_id": "delay"},
                             {"id": "area_timer", "duration_parameter_id": "high"}])
    result = build_state_machine(reply, ctx)
    assert [t.id for t in result.machine.timers] == ["delay_timer"]
    assert any(d.kind == "timer" and "not a time" in d.reason for d in result.discarded)


# --- a register row names its own quantity (fresh-run finding R2) ------------------------

ROW1 = "Parameter: Wait after Tank 1 low | Tag / Scope: Controller | Value: 12 | Units: s"
ROW2 = "Parameter: Wait after Tank 2 low | Tag / Scope: Controller | Value: 8 | Units: s"
ROW3 = "Parameter: Tank area | Tag / Scope: TK-9 | Value: 2 | Units: m2"
ROW4 = "Tag: TK-9 | Cross-section Area (m2): 2 | Height (m): 3"


def _register():
    def row(n, text):
        fields = dict(f.split(": ", 1) for f in text.split(" | "))
        return chunk("reg", f"sheet P, row {n}", text, kind="table_row", fields=fields)
    return bundle([source("reg", "register"), source("spec", "requirement_spec")],
                  [row(2, ROW1), row(3, ROW2), row(4, ROW3), row(5, ROW4),
                   chunk("spec", "line 1", "The inter-cycle wait shall be 8 s.")])


def test_a_register_row_with_a_label_column_names_its_parameter(catalogue):
    from _extract_support import param

    replies = {"FragmentReply": lambda text: empty_reply(parameters=[
        param("reg#0", ROW1, "PLC-9", "inter_cycle_wait", "12", "s"),
        param("reg#1", ROW2, "PLC-9", "inter_cycle_wait", "8", "s"),   # the LLM merged them
        param("reg#2", ROW3, "TK-9", "area", "2", "m2"),               # a catalogue name stays
        param("reg#3", ROW4, "TK-9", "cross_section", "2", "m2"),      # no label column
    ]) if "SOURCE reg" in text else empty_reply()}
    llm = FakeLLM(replies)
    passes = run_structure_passes(_register(), llm, catalogue, {"reg": "reg", "spec": "spec"})
    assert [f.fragment.name for f in passes.parameters] == [
        "wait_after_tank_1_low", "wait_after_tank_2_low", "area", "cross_section"]
    # the next pass's glossary carries the register's own names
    spec_input = next(c[1] for c in llm.calls if "SOURCE spec" in c[1])
    assert "wait_after_tank_2_low" in spec_input and "inter_cycle_wait" not in spec_input


# --- registers first, the rest in parallel (fresh-run finding R3) ------------------------

def _many_sources():
    sources = [source("reg", "register")] + [source(f"n{i}", "design_note") for i in range(5)]
    chunks = [chunk("reg", "row 1", "Tag: TK-9 | Alias: tankA", kind="table_row",
                    fields={"Tag": "TK-9", "Alias": "tankA"})]
    chunks += [chunk(f"n{i}", "line 1", f"Valve XV-{i} feeds TK-9.") for i in range(5)]
    return bundle(sources, chunks)


def _reply_for(text):
    for i in range(5):
        if f"[n{i}#0]" in text:
            return empty_reply(parts=[part(f"n{i}#0", f"Valve XV-{i}", f"XV-{i}", "on_off_valve")])
    return empty_reply(parts=[part("reg#0", "Tag: TK-9 | Alias: tankA", "TK-9", "tank",
                                   aliases=["tankA"])])


def test_parallel_passes_give_the_same_result_and_inputs_as_sequential(catalogue):
    b = _many_sources()
    runs = []
    for workers in (1, 4):
        llm = FakeLLM({"FragmentReply": _reply_for})
        passes = run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources},
                                      workers=workers)
        runs.append(([f.fragment.tag for f in passes.parts], sorted(c[1] for c in llm.calls)))
    assert runs[0] == runs[1]
    assert runs[0][0] == ["TK-9", "XV-0", "XV-1", "XV-2", "XV-3", "XV-4"]  # fixed source order


def test_other_sources_read_against_the_registers_glossary_only(catalogue):
    b = _many_sources()
    llm = FakeLLM({"FragmentReply": _reply_for})
    run_structure_passes(b, llm, catalogue, {s.id: s.id for s in b.sources})
    later = [c[1] for c in llm.calls[1:]]
    assert all("tankA" in text for text in later)          # the register's names reach them
    assert all("XV-0" not in text.split("CHUNKS")[0] for text in later)  # not each other's


def test_a_registers_requirement_rows_are_read_against_its_glossary(catalogue):
    # fresh-run finding: a register's requirement rows, read in the first wave with no glossary,
    # named "post-transfer waiting time" apart from the register's own parameter row
    b = bundle([source("reg", "register")],
               [chunk("reg", "sheet E, row 2", "Tag: TK-9 | Alias: tankA", kind="table_row",
                      fields={"Tag": "TK-9", "Alias": "tankA"}),
                chunk("reg", "sheet R, row 2", "Req: R-1 | Text: TK-9 shall hold 2 m.",
                      kind="table_row", role="requirement_spec",
                      fields={"Req": "R-1", "Text": "TK-9 shall hold 2 m."})])
    llm = FakeLLM({"FragmentReply": lambda text: empty_reply(parts=[
        part("reg#0", "Tag: TK-9 | Alias: tankA", "TK-9", "tank", aliases=["tankA"])])
        if "[reg#0]" in text else empty_reply()})
    run_structure_passes(b, llm, catalogue, {"reg": "reg"})
    requirement_call = next(c[1] for c in llm.calls if "[reg#1]" in c[1])
    assert "[reg#0]" not in requirement_call  # its own batch, in the second wave
    assert "tankA" in requirement_call.split("CHUNKS")[0]


def test_a_quote_cited_from_the_wrong_chunk_says_where_it_is_and_is_still_dropped():
    # fresh-run finding: the stated command precedence was quoted from the review minutes but
    # cited to a design-note chunk on every attempt; the reply is re-asked, never repaired
    b = bundle([source("src_n", "design_note"), source("src_r", "review_decision")],
               [chunk("src_n", "line 4", LOGIC),
                chunk("src_r", "line 9", "D-01: Command precedence is HALT > GO.")])
    import dataclasses

    ctx = dataclasses.replace(_commands_ctx(), refs=index_chunks(b),
                              source_map={"src_n": "note", "src_r": "minutes"})
    reply = _machine(
        events=[{"id": "go_cmd", "port_id": "ctl_go", "edge": "rising"},
                {"id": "halt_cmd", "port_id": "ctl_halt", "edge": "rising"}],
        command_precedence={"chunk_id": "src_n#0",
                            "quote": "D-01: Command precedence is HALT > GO.",
                            "events": ["halt_cmd", "go_cmd"]})
    result = build_state_machine(reply, ctx)
    [d] = [d for d in result.discarded if d.kind == "command precedence"]
    assert "src_n#0" in d.reason and "it is in chunk src_r#0" in d.reason


def test_a_timer_tested_but_never_started_is_reported_so_the_reply_is_asked_again():
    # fresh-run finding: the fill transition lost its start_timer, so the wait never ended
    reply = _machine(transitions=[_tr("idle", "fill", 1, trigger="go_cmd"),
                                  _tr("fill", "hold", 1, guard="ctl_level >= high"),
                                  _tr("hold", "idle", 1, guard="timer_expired(delay_timer)")])
    result = build_state_machine(reply, _ctx())
    assert len(result.machine.transitions) == 3  # nothing is dropped or repaired
    [d] = result.discarded
    assert d.kind == "timer" and "delay_timer" in d.reason and "hold" in d.reason
    assert "never started" in d.reason
