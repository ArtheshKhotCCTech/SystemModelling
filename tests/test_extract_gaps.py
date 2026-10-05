# Purpose: pins gaps and honesty (FR-04 requirements 13-16, R-EXT-1, R-EXT-3): catalogue defaults
# fill missing values only with their recorded assumption, a missing value with no default becomes
# a Question, conventions come only from the explicit rule list, source-stated simplifications
# become traced Assumptions, missing documents are listed, and the honesty gate removes every
# untraced element (cascading) without ever adding a trace.
import pytest

from _extract_support import found
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import (
    AcceptanceCriterion,
    Assumption,
    Conflict,
    Connection,
    OriginalValue,
    Parameter,
    Part,
    Port,
    Question,
    Source,
    TraceLink,
)
from specalive.extract.fragments import AssumptionHint, Draft
from specalive.extract.gaps import (
    CATALOGUE_SOURCE_ID,
    CONVENTIONS,
    apply_catalogue,
    apply_conventions,
    hint_assumptions,
    honesty_gate,
    missing_documents,
)


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


T = [TraceLink(source_id="spec", locator="p.1", quote="Tank TK-9")]


def tank(pid="tk", trace=T):
    return Part(id=pid, kind="tank", name="Tank", trace=trace, ports=[
        Port(id=f"{pid}_inlet", role="inlet", direction="in", domain="fluid"),
        Port(id=f"{pid}_outlet", role="outlet", direction="out", domain="fluid"),
        Port(id=f"{pid}_level_out", role="level_out", direction="out", domain="signal_real")])


def valve(pid="xv", trace=T):
    return Part(id=pid, kind="on_off_valve", name="Valve", trace=trace, ports=[
        Port(id=f"{pid}_inlet", role="inlet", direction="in", domain="fluid"),
        Port(id=f"{pid}_outlet", role="outlet", direction="out", domain="fluid"),
        Port(id=f"{pid}_cmd_in", role="cmd_in", direction="in", domain="signal_bool")])


def prm(owner, name, value, unit="m", trace=T):
    return Parameter(id=f"{owner}_{name}", owner=owner, name=name, value=value, unit=unit,
                     original=OriginalValue(value=str(value), unit=unit), status="effective",
                     authority="spec", trace=trace)


def draft(**kw):
    d = Draft(name="m", description="d", sources=[Source(id="spec", title="Spec",
                                                         role="requirement_spec")])
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_catalogue_default_is_applied_with_its_assumption(catalogue):
    d = draft(parts=[tank()], parameters=[prm("tk", "area", 2.0, "m2")])
    missing = apply_catalogue(d, catalogue)
    p = next(p for p in d.parameters if p.name == "initial_level")
    default = catalogue.entry("tank").defaults["initial_level"]
    assert (p.value, p.unit, p.status, p.authority, p.trace) == (
        default.value, default.unit, "effective", CATALOGUE_SOURCE_ID, [])
    a = next(a for a in d.assumptions if a.id in p.assumption_ids)
    assert a.text == default.assumption and a.basis == "default" and p.id in a.affects
    assert any(s.id == CATALOGUE_SOURCE_ID and s.path is None for s in d.sources)
    assert missing == []


def test_required_value_without_default_is_a_question_and_missing(catalogue):
    d = draft(parts=[valve()])
    missing = apply_catalogue(d, catalogue)
    assert not any(p.name == "nominal_flow" for p in d.parameters)
    assert len(d.questions) == 1 and "nominal_flow" in d.questions[0].text
    assert d.questions[0].affects == ["xv"]
    assert missing and "nominal_flow" in missing[0]


def test_present_values_are_left_alone(catalogue):
    d = draft(parts=[tank()], parameters=[prm("tk", "area", 2.0, "m2"),
                                          prm("tk", "initial_level", 0.3)])
    apply_catalogue(d, catalogue)
    assert len(d.parameters) == 2 and d.assumptions == [] and d.questions == []


def test_conventions_are_an_explicit_list_each_with_an_assumption():
    assert CONVENTIONS and all(rule.name and rule.text for rule in CONVENTIONS)
    d = draft(parts=[tank()], parameters=[prm("tk", "area", 2.0, "m2"),
                                          prm("tk", "low_level", 0.05)])
    apply_conventions(d)
    init = next(p for p in d.parameters if p.name == "initial_level")
    assert init.value == 0.05 and init.trace == d.parameters[1].trace
    a = next(a for a in d.assumptions if a.id in init.assumption_ids)
    assert a.basis == "engineering_convention" and a.trace == d.parameters[1].trace


def test_hints_become_traced_assumptions_affecting_resolved_parts():
    hint = AssumptionHint(chunk_id="ds#0", quote="each valve is treated as an ideal switch",
                          text="Valves are ideal Boolean flow switches.",
                          affects_tags=["XV-9", "P-404"])
    out = hint_assumptions([found(hint, source_id="ds", role="datasheet")],
                           {"xv9": "xv_9"}.get)
    assert len(out) == 1
    a = out[0]
    assert a.basis == "engineering_convention" and a.affects == ["xv_9"]
    assert a.trace[0].quote == "each valve is treated as an ideal switch"


def test_missing_documents_lists_cited_records_and_unresolved_citations():
    sources = [Source(id="spec", title="Spec", role="requirement_spec", path="a.pdf"),
               Source(id="cr_9", title="CR-9", role="change_record", path=None, tags=["CR-9"]),
               Source(id=CATALOGUE_SOURCE_ID, title="Catalogue", role="other", path=None)]
    out = missing_documents(sources, {"XX-404"})
    assert len(out) == 2
    assert any("CR-9" in m for m in out) and any("XX-404" in m for m in out)


def test_honesty_gate_removes_untraced_elements_and_cascades():
    good, bad = tank("tk"), valve("xv", trace=[])
    d = draft(
        parts=[good, bad],
        connections=[Connection(id="c1", from_port="xv_outlet", to_port="tk_inlet",
                                medium_or_signal="liquid", trace=T),
                     Connection(id="c2", from_port="tk_outlet", to_port="tk_inlet",
                                medium_or_signal="liquid", trace=[])],
        parameters=[prm("xv", "nominal_flow", 0.1, "m3/s"), prm("tk", "area", 2.0, "m2")],
        acceptance_criteria=[AcceptanceCriterion(id="ac1", text="ok", reason="prose")],
        assumptions=[Assumption(id="as1", text="t", basis="inferred", affects=["xv", "tk"],
                                confidence=0.5)],
        questions=[Question(id="q1", text="?", affects=["xv_nominal_flow"])],
        conflicts=[Conflict(id="cf1", subject={"element_id": "xv_nominal_flow",
                                                "field": "value"},
                            candidates=[{"value": "1", "source_id": "spec", "authority_rank": 1},
                                        {"value": "2", "source_id": "spec", "authority_rank": 3}],
                            resolution="1", rationale="r")])
    traces_before = good.trace.copy()
    rejected = honesty_gate(d)
    assert [p.id for p in d.parts] == ["tk"] and good.trace == traces_before
    assert [c.id for c in d.connections] == []
    assert [p.id for p in d.parameters] == ["tk_area"]
    assert d.acceptance_criteria == [] and d.conflicts == []
    assert d.assumptions[0].affects == ["tk"] and d.questions[0].affects == []
    kinds = {(r.kind, r.id) for r in rejected}
    assert {("part", "xv"), ("connection", "c1"), ("connection", "c2"),
            ("parameter", "xv_nominal_flow"), ("acceptance criterion", "ac1"),
            ("conflict", "cf1")} <= kinds
    assert all(r.reason for r in rejected)


def test_honesty_gate_keeps_assumption_backed_elements():
    p = tank("tk", trace=[])
    p.assumption_ids = ["as1"]
    d = draft(parts=[p], assumptions=[Assumption(id="as1", text="t", basis="inferred",
                                                 confidence=0.5)])
    assert honesty_gate(d) == [] and [x.id for x in d.parts] == ["tk"]


# --- run parameter names (phase 9) -------------------------------------------------------

def _run(name, value, status="verification_only", owner="system"):
    return prm(owner, name, value, "s").model_copy(update={"status": status})


def test_a_system_value_named_for_a_run_parameter_is_given_that_name_with_an_assumption():
    from specalive.extract.gaps import apply_run_names

    d = draft(parameters=[_run("simulation_stop_time", 900.0)])
    assert apply_run_names(d) == []
    stop = next(p for p in d.parameters if p.name == "stop_time")
    assert stop.owner == "system" and stop.value == 900.0 and stop.status == "verification_only"
    assert stop.trace == d.parameters[0].trace
    a = next(a for a in d.assumptions if a.id in stop.assumption_ids)
    assert a.basis == "engineering_convention" and "simulation_stop_time" in a.text
    assert any(p.name == "simulation_stop_time" for p in d.parameters)  # the original is kept


def test_an_existing_run_parameter_is_not_duplicated():
    from specalive.extract.gaps import apply_run_names

    d = draft(parameters=[_run("stop_time", 900.0), _run("simulation_stop_time", 600.0)])
    apply_run_names(d)
    assert [p.name for p in d.parameters].count("stop_time") == 1 and d.assumptions == []


def test_two_candidates_are_reported_not_chosen_between():
    from specalive.extract.gaps import apply_run_names

    d = draft(parameters=[_run("simulation_stop_time", 900.0), _run("test_stop_time", 600.0)])
    missing = apply_run_names(d)
    assert all(p.name != "stop_time" for p in d.parameters)
    assert any("stop_time" in m and "simulation_stop_time" in m for m in missing)


def test_part_owned_and_superseded_values_are_not_run_parameters():
    from specalive.extract.gaps import apply_run_names

    d = draft(parts=[tank()], parameters=[_run("fill_stop_time", 50.0, owner="tk"),
                                          _run("old_stop_time", 600.0, status="superseded")])
    apply_run_names(d)
    assert all(p.name != "stop_time" for p in d.parameters)


# --- inputs wired to nothing (phase 9 closure) -------------------------------------------

def test_an_input_connected_to_nothing_is_a_question_before_compile():
    from specalive.extract.gaps import unconnected_inputs

    wire = Connection(id="c1", from_port="xv_outlet", to_port="tk_inlet", medium_or_signal="water",
                      trace=T)
    questions = unconnected_inputs(draft(parts=[tank(), valve()], connections=[wire]))
    # xv_inlet and xv_cmd_in feed nothing into the model; an output left open is not a gap
    assert [(q.affects, q.id) for q in questions] == [
        (["xv"], "q_unconnected_xv_cmd_in"), (["xv"], "q_unconnected_xv_inlet")]
    assert "xv_cmd_in" in questions[0].text and "connected to nothing" in questions[0].text
    assert all(q.default_if_unanswered is None and q.options == [] for q in questions)


def test_a_fully_wired_model_has_no_wiring_question():
    from _modelica_support import golden_model
    from specalive.extract.gaps import unconnected_inputs

    g = golden_model()
    d = draft(parts=list(g.parts), connections=list(g.connections))
    assert unconnected_inputs(d) == []


def test_candidates_that_agree_on_the_value_are_not_ambiguous():
    # fresh-run finding: the stop time came back twice (effective and verification-only, both
    # 900 s), was reported as ambiguous, and the run fell back to 1 s
    from specalive.extract.gaps import apply_run_names

    d = draft(parameters=[_run("simulation_stop_time", 900.0, status="effective"),
                          _run("simulation_stop_time", 900.0).model_copy(
                              update={"id": "system_simulation_stop_time_verification"})])
    assert apply_run_names(d) == []
    assert [p.value for p in d.parameters if p.name == "stop_time"] == [900.0]


# --- ids unique across element kinds (phase 10, L2 finding) -------------------------------

def test_a_source_whose_id_another_element_has_is_renamed_everywhere():
    # L2: a cited record "RM-201" and the room part RM-201 both became rm_201, and the URS
    # document and a requirement tagged with its number both became urs_iaq_001
    from specalive.core.ir import Candidate, ConflictSubject, Requirement
    from specalive.extract.gaps import unique_ids

    link = [TraceLink(source_id="tk", locator="p.1", quote="Tank TK-9")]
    d = draft(sources=[Source(id="tk", title="TK record", role="change_record")],
              parts=[tank(trace=link)], parameters=[prm("tk", "area", 2.0, "m2", trace=link)],
              requirements=[Requirement(id="tk_r", text="t", category="c", status="active",
                                        trace=link)])
    d.parameters[0] = d.parameters[0].model_copy(update={"authority": "tk"})
    d.conflicts = [Conflict(id="cf", subject=ConflictSubject(element_id="tk_area", field="value"),
                            candidates=[Candidate(value="2", source_id="tk", authority_rank=1),
                                        Candidate(value="3", source_id="tk", authority_rank=2)],
                            resolution="2", rationale="r")]
    notes = unique_ids(d)
    assert [s.id for s in d.sources] == ["doc_tk"] and d.parts[0].id == "tk"
    assert d.parts[0].trace[0].source_id == "doc_tk"
    assert d.parameters[0].authority == "doc_tk" and d.parameters[0].trace[0].source_id == "doc_tk"
    assert d.requirements[0].trace[0].source_id == "doc_tk"
    assert {c.source_id for c in d.conflicts[0].candidates} == {"doc_tk"}
    assert notes and "tk" in notes[0]


def test_unique_ids_leaves_a_clean_draft_alone():
    from specalive.extract.gaps import unique_ids

    d = draft(parts=[tank()], parameters=[prm("tk", "area", 2.0, "m2")])
    assert unique_ids(d) == [] and [s.id for s in d.sources] == ["spec"]


# --- a one-parameter kind's only stated value (phase 10 follow-up, L2 finding) ---------------

def _constant(pid="ca"):
    return Part(id=pid, kind="constant", name="Constant", trace=T, ports=[
        Port(id=f"{pid}_y", role="y", direction="out", domain="signal_real")])


def test_a_one_parameter_kinds_only_value_is_its_parameter_with_an_assumption(catalogue):
    # L2: the outdoor-air constant's 0.0004557 kg/kg came back named "concentration"
    d = draft(parts=[_constant()], parameters=[prm("ca", "concentration", 0.0004557, "kg/kg")])
    missing = apply_catalogue(d, catalogue)
    value = next(p for p in d.parameters if p.name == "value")
    assert value.value == 0.0004557 and value.unit == "kg/kg" and value.trace == T
    [a] = [a for a in d.assumptions if a.id in value.assumption_ids]
    assert "concentration" in a.text and a.basis == "inferred"
    assert missing == [] and d.questions == []


def test_two_unnamed_values_are_still_a_question(catalogue):
    d = draft(parts=[_constant()], parameters=[prm("ca", "low", 1.0, "1"), prm("ca", "high", 2.0, "1")])
    apply_catalogue(d, catalogue)
    assert all(p.name != "value" for p in d.parameters)
    assert len(d.questions) == 1 and "value" in d.questions[0].text


# --- the run spans the reference trace when no source states its length ---------------------

SUMMARY = ("file: ref.csv\ncolumns: time_s, level_m\nrows: 1441\n"
           "time span: time_s from 0 to 86400")


def _with_reference(*summaries):
    from _extract_support import bundle, chunk, source as ev_source

    srcs = [ev_source(f"ref{i}", "reference_data", path=f"ref{i}.csv", fmt="csv")
            for i in range(len(summaries))]
    return bundle(srcs, [chunk(f"ref{i}", "file summary", text, kind="data_summary")
                         for i, text in enumerate(summaries)])


def test_the_run_spans_the_one_reference_trace_with_an_assumption():
    from specalive.extract.gaps import run_span_from_reference

    d = draft()
    missing = run_span_from_reference(d, _with_reference(SUMMARY), {"ref0": "ref0"})
    params = {p.name: p for p in d.parameters}
    assert params["stop_time"].value == 86400.0 and params["stop_time"].unit == "s"
    assert params["output_interval"].value == 60.0
    assert all(p.status == "verification_only" for p in params.values())
    assert params["stop_time"].trace[0].quote == "time span: time_s from 0 to 86400"
    [a] = d.assumptions
    assert set(a.affects) == {params["stop_time"].id, params["output_interval"].id}
    assert missing == []


def test_a_stated_stop_time_wins_and_two_traces_that_differ_are_not_chosen_between():
    from specalive.extract.gaps import run_span_from_reference

    stated = draft(parameters=[_run("stop_time", 900.0)])
    assert run_span_from_reference(stated, _with_reference(SUMMARY), {"ref0": "ref0"}) == []
    assert [p.value for p in stated.parameters if p.name == "stop_time"] == [900.0]
    other = SUMMARY.replace("86400", "3600")
    d = draft()
    missing = run_span_from_reference(d, _with_reference(SUMMARY, other),
                                      {"ref0": "ref0", "ref1": "ref1"})
    assert d.parameters == [] and missing and "stop_time" in missing[0]
