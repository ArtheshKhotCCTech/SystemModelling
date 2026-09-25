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
    from specalive.extract.extract import Passes, run_behaviour_passes
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
    assert len(llm.calls) == 2
    assert "nowhere" in llm.calls[1][1].split("PROBLEMS")[1]
    sm = draft.state_machines[0]
    assert [t.id for t in sm.transitions] == ["tr_idle_1", "tr_fill_1"]
    assert any("attempt 1" in d.reason for d in report.discarded_fragments)
