# Purpose: pins entity resolution (FR-04 requirements 5-7): one part per real component when the
# evidence equates names (same tag, a tag/alias row, an alias cross-reference), a similar-looking
# but unlinked name merged only with an Assumption and lower confidence, unknown kinds as
# Questions, catalogue ports, connections resolved through aliases (controller ports made from
# them), unresolvable endpoints reported, and the evidence -> IR source mapping.
import pytest

from _extract_support import bundle, chunk, connection, found, part, source
from specalive.core.catalogue import load_catalogue
from specalive.core.ids import make_id
from specalive.extract.fragments import AliasFragment, ConnectionFragment, PartFragment
from specalive.extract.merge import ir_sources, name_key, resolve_connections, resolve_parts


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


def pf(quote, tag, kind, aliases=(), source_id="src_a", role="design_note", name=None,
       attributes=None):
    return found(PartFragment.model_validate(part(f"{source_id}#0", quote, tag, kind, aliases,
                                                  name, attributes)),
                 source_id=source_id, role=role)


def af(quote, names, source_id="src_x"):
    return found(AliasFragment(chunk_id=f"{source_id}#0", quote=quote, names=list(names)),
                 source_id=source_id, role="register")


def test_name_key_ignores_case_and_separators():
    assert name_key("TK-101") == name_key("tk_101") == name_key("Tk 101") == "tk101"


def test_same_tag_in_two_sources_is_one_part_with_both_traces(catalogue):
    ps = resolve_parts([pf("Tank TK-9 receives feed", "TK-9", "tank"),
                        pf("TK-9 area 2 m2", "TK-9", "tank", source_id="src_b")], [], catalogue)
    assert [p.id for p in ps.parts] == [make_id("tank", "TK-9")]
    assert {t.source_id for t in ps.parts[0].trace} == {"src_a", "src_b"}
    assert ps.parts[0].confidence == 1.0 and ps.assumptions == []


def test_alias_row_unifies_names_and_keeps_every_alias(catalogue):
    ps = resolve_parts([pf("tank1 fills first", "tank1", "tank"),
                        pf("T1 high level", "T1", "tank", source_id="src_b"),
                        pf("TK-101 is the receiving tank", "TK-101", "tank", source_id="src_c")],
                       [af("TK-101 | tank1 | T1", ["TK-101", "tank1", "T1"])], catalogue)
    assert len(ps.parts) == 1
    p = ps.parts[0]
    assert p.id == "tk_101" and p.tags[0] == "TK-101"
    assert set(p.tags) == {"TK-101", "tank1", "T1"}
    assert {t.source_id for t in p.trace} == {"src_a", "src_b", "src_c", "src_x"}
    assert ps.lookup("t1") == ps.lookup("TANK1") == "tk_101"


def test_names_listed_together_in_one_fragment_link_later_mentions(catalogue):
    ps = resolve_parts([pf("XV-7 (valve7 / V7)", "XV-7", "on_off_valve", aliases=["valve7", "V7"]),
                        pf("open V7", "V7", "on_off_valve", source_id="src_b")], [], catalogue)
    assert [p.id for p in ps.parts] == ["xv_7"]
    assert ps.parts[0].tags == ["XV-7", "valve7", "V7"]


def test_similar_unlinked_names_merge_only_with_an_assumption(catalogue):
    ps = resolve_parts([pf("valve1 opens", "valve1", "on_off_valve"),
                        pf("V1 closes", "V1", "on_off_valve", source_id="src_b")], [], catalogue)
    assert len(ps.parts) == 1
    p = ps.parts[0]
    assert p.confidence < 1.0
    assert len(ps.assumptions) == 1
    a = ps.assumptions[0]
    assert a.basis == "inferred" and a.confidence < 1.0 and p.id in a.affects
    assert "valve1" in a.text and "V1" in a.text
    assert a.id in p.assumption_ids


def test_similar_names_of_different_kinds_are_not_merged(catalogue):
    ps = resolve_parts([pf("valve1 opens", "valve1", "on_off_valve"),
                        pf("V1 tank", "V1", "tank", source_id="src_b")], [], catalogue)
    assert len(ps.parts) == 2 and ps.assumptions == []


def test_unknown_kind_is_a_question_never_a_part(catalogue):
    frag = PartFragment.model_validate({**part("src_a#0", "a centrifugal pump P-1", "P-1",
                                               "unknown"), "description": "centrifugal pump"})
    ps = resolve_parts([found(frag)], [], catalogue)
    assert ps.parts == []
    assert len(ps.questions) == 1
    assert "P-1" in ps.questions[0].text and "no catalogue component" in ps.questions[0].text


def test_kind_conflict_goes_to_the_higher_authority(catalogue):
    ps = resolve_parts([pf("S-1 source", "S-1", "fluid_source", role="informal_note"),
                        pf("S-1 sink", "S-1", "fluid_sink", role="requirement_spec",
                           source_id="src_b")], [], catalogue)
    assert [p.kind for p in ps.parts] == ["fluid_sink"]


def test_kind_disagreement_at_equal_rank_is_a_question(catalogue):
    ps = resolve_parts([pf("S-1 source", "S-1", "fluid_source"),
                        pf("S-1 sink", "S-1", "fluid_sink", source_id="src_b")], [], catalogue)
    assert len(ps.parts) == 1 and len(ps.questions) == 1
    assert set(ps.questions[0].options) == {"fluid_source", "fluid_sink"}


def test_catalogue_ports_are_added_and_inherit_the_part_trace(catalogue):
    ps = resolve_parts([pf("Tank TK-9", "TK-9", "tank", name="Tank 9",
                           attributes={"service": "feed"})], [], catalogue)
    p = ps.parts[0]
    assert [(q.id, q.role, q.direction, q.domain) for q in p.ports] == [
        ("tk_9_inlet", "inlet", "in", "fluid"), ("tk_9_level_out", "level_out", "out",
                                                 "signal_real"),
        ("tk_9_outlet", "outlet", "out", "fluid")]
    assert all(q.trace == [] for q in p.ports)
    assert p.name == "Tank 9" and p.attributes == {"service": "feed"}


def _plant(catalogue):
    return resolve_parts([
        pf("XV-1 (valve1)", "XV-1", "on_off_valve", aliases=["valve1"]),
        pf("TK-1 (tank1)", "TK-1", "tank", aliases=["tank1"]),
        pf("PLC-1 (ctl)", "PLC-1", "sequence_controller", aliases=["ctl"]),
        pf("LT-1", "LT-1", "level_sensor")], [], catalogue)


def cf(quote, frm, to, **kw):
    return found(ConnectionFragment.model_validate(connection("src_a#0", quote, frm, to, **kw)))


def test_connection_resolved_through_aliases_with_roles_inferred(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("valve1 discharges into tank1", "valve1", "tank1")], ps,
                             catalogue)
    assert [(c.from_port, c.to_port) for c in cs.connections] == [("xv_1_outlet", "tk_1_inlet")]
    assert cs.connections[0].trace[0].quote == "valve1 discharges into tank1"
    assert cs.problems == []


def test_connection_tag_names_the_connection_and_duplicates_merge(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("IF-1 valve to tank", "XV-1", "TK-1", tag="IF-1"),
                              cf("valve1 into tank1", "valve1", "tank1")], ps, catalogue)
    assert [c.id for c in cs.connections] == ["if_1"]
    assert len(cs.connections[0].trace) == 2


def test_controller_ports_are_made_from_its_connections(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("PLC-1 commands XV-1", "ctl", "XV-1", to_role="cmd_in",
                                 medium="command", signal="valve1"),
                              cf("LT-1 to PLC-1", "LT-1", "PLC-1", from_role="level_out",
                                 signal="level1")], ps, catalogue)
    ctl = next(p for p in ps.parts if p.id == "plc_1")
    assert [(q.id, q.direction, q.domain) for q in ctl.ports] == [
        ("plc_1_level1", "in", "signal_real"), ("plc_1_valve1", "out", "signal_bool")]
    assert {(c.from_port, c.to_port) for c in cs.connections} == {
        ("plc_1_valve1", "xv_1_cmd_in"), ("lt_1_level_out", "plc_1_level1")}


def test_invalid_role_is_ignored_and_the_port_inferred_from_domains(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("TK-1 level to LT-1", "TK-1", "LT-1", from_role="bogus",
                                 medium="level")], ps, catalogue)
    assert [(c.from_port, c.to_port) for c in cs.connections] == [("tk_1_level_out",
                                                                   "lt_1_level_in")]


def test_unresolvable_or_ambiguous_endpoints_are_reported_not_guessed(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("pump feeds tank", "P-9", "TK-1"),
                              cf("sensor to valve", "LT-1", "XV-1", medium="signal")],
                             ps, catalogue)
    assert cs.connections == []
    assert len(cs.problems) == 2
    assert any("P-9" in p for p in cs.problems)


def test_ir_sources_use_the_document_number_when_the_header_states_one():
    b = bundle([source("src_01_spec_pdf", "requirement_spec", document="SPEC-7", date="2026-01-01",
                       title="Spec", revision="A"),
                source("src_02_notes_txt", "informal_note")],
               [chunk("src_01_spec_pdf", "p.1", "x"), chunk("src_02_notes_txt", "line 1", "y")])
    sources, mapping = ir_sources(b)
    assert mapping == {"src_01_spec_pdf": "spec_7", "src_02_notes_txt": "src_02_notes_txt"}
    spec = next(s for s in sources if s.id == "spec_7")
    assert (spec.role, spec.date, spec.revision, spec.title, spec.tags) == (
        "requirement_spec", "2026-01-01", "A", "Spec", ["SPEC-7"])
    assert spec.path == "src_01_spec_pdf.txt"


def test_part_tag_without_letters_or_digits_falls_back_to_an_alias(catalogue):
    ps = resolve_parts([pf("tank9 (-)", "-", "tank", aliases=["tank9"])], [], catalogue)
    assert [p.id for p in ps.parts] == ["tank9"] and ps.parts[0].tags == ["tank9"]


def test_two_different_formal_tags_are_never_one_part(catalogue):
    ps = resolve_parts([pf("valve1 (XV-1)", "XV-1", "on_off_valve",
                           aliases=["valve1", "V1", "XV-2", "XV-3"]),
                        pf("valve2 (XV-2)", "XV-2", "on_off_valve", aliases=["valve2", "XV-1"],
                           source_id="src_b"),
                        pf("XV-3", "XV-3", "on_off_valve", source_id="src_c")],
                       [af("XV-1 | valve1 | XV-2", ["XV-1", "valve1", "XV-2"])], catalogue)
    assert [p.id for p in ps.parts] == ["xv_1", "xv_2", "xv_3"]
    tags = {p.id: set(p.tags) for p in ps.parts}
    assert tags["xv_1"] == {"XV-1", "valve1", "V1"} and tags["xv_2"] == {"XV-2", "valve2"}


def test_one_static_port_reaches_a_controller_once_whatever_the_signal_is_called(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("LT-1 to PLC-1 as level1", "LT-1", "PLC-1", signal="level1"),
                              cf("LT-1 to PLC-1 as AI-1", "LT-1", "PLC-1", signal="AI-1")],
                             ps, catalogue)
    assert [(c.from_port, c.to_port) for c in cs.connections] == [("lt_1_level_out",
                                                                   "plc_1_level1")]
    assert len(cs.connections[0].trace) == 2
    assert [q.id for q in ps.part("plc_1").ports] == ["plc_1_level1"]


def test_controller_port_is_named_after_the_short_alias_of_what_it_connects_to(catalogue):
    ps = _plant(catalogue)
    cs = resolve_connections([cf("DO-9 drives XV-1", "PLC-1", "XV-1", signal="DO-9"),
                              cf("valve1 command", "PLC-1", "XV-1", signal="valve1")],
                             ps, catalogue)
    assert [q.id for q in ps.part("plc_1").ports] == ["plc_1_valve1"]
    assert [(c.from_port, c.to_port) for c in cs.connections] == [("plc_1_valve1",
                                                                   "xv_1_cmd_in")]


def test_controller_port_takes_the_alias_alone_when_one_signal_port_faces_it(catalogue):
    ps = resolve_parts([pf("LT-1 (level1)", "LT-1", "level_sensor", aliases=["level1"]),
                        pf("PLC-1", "PLC-1", "sequence_controller")], [], catalogue)
    resolve_connections([cf("LT-1 to PLC-1", "LT-1", "PLC-1", signal="AI-1")], ps, catalogue)
    assert [q.id for q in ps.part("plc_1").ports] == ["plc_1_level1"]
