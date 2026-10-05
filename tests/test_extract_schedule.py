# Purpose: pins the operator command schedule (phase 9): a verification procedure's command table
# (a time line, then a line that is exactly a button's alias), "<button> at <n> s" sentences and
# time/command table rows become each button's press_times, verification_only and traced to
# every verbatim match; sources that agree give one value, sources that disagree a Question and no
# value; informal notes, partial words and buttons that already have press times are left alone.
from _extract_support import bundle, chunk, source
from specalive.core.ir import OriginalValue, Parameter, Part, Port, TraceLink
from specalive.extract.schedule import press_schedules

TABLE = ("3. Operator Command Schedule\nTime (s)\nCommand\nExpected response\n20\nSTART\n"
         "Begin automatic operation.\n220\nSTOP\nClose all valves.\n280\nSTART\nResume.\n"
         "700\nSHUT\nControlled shutdown.")
SENTENCE = "The demonstration run shall apply START at 20 s, STOP at 220 s, START at 280 s and SHUT at 700 s."
T = [TraceLink(source_id="reg", locator="row 1", quote="PB-START")]


def button(pid, *tags):
    return Part(id=pid, kind="command_button", name=pid, tags=list(tags), trace=T,
                ports=[Port(id=f"{pid}_cmd_out", role="cmd_out", direction="out",
                            domain="signal_bool")])


BUTTONS = [button("pb_start", "PB-START", "start"), button("pb_stop", "PB-STOP", "stop"),
           button("pb_shut", "PB-SHUT", "shut")]


def run(chunks, sources, parameters=(), parts=BUTTONS):
    b = bundle(sources, chunks)
    return press_schedules(b, parts, list(parameters), {s.id: s.id for s in sources})


def values(result):
    return {p.owner: p.value for p in result.parameters}


def test_command_table_gives_each_button_its_press_times():
    r = run([chunk("tp", "page 1, lines 28-47", TABLE)], [source("tp", "verification_procedure")])
    assert values(r) == {"pb_start": [20.0, 280.0], "pb_stop": [220.0], "pb_shut": [700.0]}
    start = next(p for p in r.parameters if p.owner == "pb_start")
    assert (start.id, start.name, start.unit, start.status) == (
        "pb_start_press_times", "press_times", "s", "verification_only")
    assert start.original == OriginalValue(value="20, 280", unit="s")
    assert [t.quote for t in start.trace] == ["20\nSTART", "280\nSTART"]  # verbatim spans
    assert all(t.source_id == "tp" and t.locator == "page 1, lines 28-47" for t in start.trace)
    assert r.questions == []


def test_a_sentence_and_a_table_that_agree_give_one_value_traced_to_both():
    r = run([chunk("tp", "p.1", TABLE), chunk("reg", "row 36", SENTENCE, kind="table_row")],
            [source("tp", "verification_procedure"), source("reg", "requirement_spec")])
    assert values(r)["pb_start"] == [20.0, 280.0]
    start = next(p for p in r.parameters if p.owner == "pb_start")
    assert {t.source_id for t in start.trace} == {"tp", "reg"}
    assert "START at 20 s" in {t.quote for t in start.trace}


def test_sources_that_disagree_become_a_question_and_no_value():
    other = "The run shall apply START at 30 s and SHUT at 700 s."
    r = run([chunk("tp", "p.1", TABLE), chunk("reg", "row 36", other)],
            [source("tp", "verification_procedure"), source("reg", "requirement_spec")])
    assert "pb_start" not in values(r)
    assert values(r)["pb_shut"] == [700.0]  # agreeing buttons still get theirs
    [q] = r.questions
    assert q.affects == ["pb_start"] and q.default_if_unanswered is None
    assert "20, 280" in " ".join(q.options) and "30" in " ".join(q.options)


def test_informal_notes_are_not_a_schedule():
    r = run([chunk("note", "line 7", "09:07 - Stop at 220 s looked right.")],
            [source("note", "informal_note")])
    assert r.parameters == [] and r.questions == []


def test_whole_words_only_and_formal_tags_count():
    r = run([chunk("tp", "p.1", "RESTART at 5 s is not tested. PB-START at 20 s begins the run.")],
            [source("tp", "verification_procedure")])
    assert values(r) == {"pb_start": [20.0]}


def test_time_and_command_table_rows():
    rows = [chunk("tp", f"table 1, row {i}", f"Time (s): {t} | Command: {c}", kind="table_row",
                  fields={"Time (s)": t, "Command": c})
            for i, (t, c) in enumerate([("20", "START"), ("220", "STOP")], start=2)]
    r = run(rows, [source("tp", "verification_procedure")])
    assert values(r) == {"pb_start": [20.0], "pb_stop": [220.0]}
    assert next(p for p in r.parameters if p.owner == "pb_stop").trace[0].quote == \
        "Time (s): 220 | Command: STOP"


def test_a_button_with_press_times_already_is_left_alone():
    existing = Parameter(id="pb_start_press_times", owner="pb_start", name="press_times",
                         value=[5.0], unit="s", original=OriginalValue(value="5", unit="s"),
                         status="verification_only", authority="tp", trace=T)
    r = run([chunk("tp", "p.1", TABLE)], [source("tp", "verification_procedure")], [existing])
    assert "pb_start" not in values(r) and values(r)["pb_stop"] == [220.0]


def test_no_buttons_or_no_mention_gives_nothing():
    assert run([chunk("tp", "p.1", TABLE)], [source("tp", "verification_procedure")],
               parts=[]).parameters == []
    r = run([chunk("tp", "p.1", "20\nOPEN\n")], [source("tp", "verification_procedure")])
    assert r.parameters == [] and r.questions == []


def test_press_times_whose_quote_does_not_name_the_button_are_replaced():
    # fresh-run finding: START was given a sentence about every button's edges
    harness = [TraceLink(source_id="tp", locator="p.2",
                         quote="A test harness supplies button edges at 20, 220, 280 and 700 seconds.")]
    unnamed = Parameter(id="pb_start_press_times", owner="pb_start", name="press_times",
                        value=[20.0, 220.0, 280.0, 700.0], unit="s",
                        original=OriginalValue(value="20, 220, 280, 700", unit="s"),
                        status="verification_only", authority="tp", trace=harness)
    r = run([chunk("tp", "p.1", TABLE)], [source("tp", "verification_procedure")], [unnamed])
    assert values(r)["pb_start"] == [20.0, 280.0]
    assert [p.id for p in r.replaced] == ["pb_start_press_times"]
    assert next(p for p in r.parameters if p.owner == "pb_start").id == "pb_start_press_times"


def test_unnamed_press_times_stay_when_no_schedule_names_the_button():
    harness = [TraceLink(source_id="tp", locator="p.2", quote="Edges at 20 and 280 seconds.")]
    unnamed = Parameter(id="pb_start_press_times", owner="pb_start", name="press_times",
                        value=[20.0, 280.0], unit="s", original=OriginalValue(value="20, 280", unit="s"),
                        status="verification_only", authority="tp", trace=harness)
    r = run([chunk("tp", "p.1", "nothing here")], [source("tp", "verification_procedure")],
            [unnamed])
    assert r.replaced == [] and "pb_start" not in values(r)
