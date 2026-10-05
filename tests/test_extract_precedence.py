# Purpose: pins the precedence ladder (FR-04 requirements 8-12, R-EXT-5..7): ranks come from roles,
# a register row takes the rank of the record it cites, status columns in the evidence decide
# first, approval outranks recency, every loser is kept and named in a Conflict, configuration
# variants are not conflicts, and ties or provisional winners become Questions.
from _extract_support import bundle, chunk, found, param, source
from specalive.extract.fragments import DocumentFragment, ParameterFragment, RequirementFragment
from specalive.extract.precedence import (
    RANK,
    DocInfo,
    DocRegistry,
    build_registry,
    rank_of,
    resolve_parameters,
    resolve_requirements,
)
from specalive.extract.merge import ir_sources


def registry():
    docs = DocRegistry()
    docs.add("CR-9", DocInfo(source_id="cr_9", role="change_record", date="2026-03-11",
                             approved=True))
    docs.add("SPEC-1", DocInfo(source_id="spec_1", role="requirement_spec", date="2026-01-15",
                               approved=True))
    return docs


def cand(owner, name, value, unit, source_id="spec_1", role="requirement_spec", date=None,
         **kw):
    quote = f"{name} {value} {unit}"
    frag = ParameterFragment.model_validate(param(f"{source_id}#0", quote, owner, name, value,
                                                  unit, **kw))
    return owner, found(frag, source_id=source_id, role=role, date=date)


def by_id(result):
    return {p.id: p for p in result.parameters}


def test_rank_table_follows_the_adr_ladder():
    assert RANK["change_record"] == 1 and RANK["review_decision"] == 2
    assert RANK["requirement_spec"] == RANK["design_note"] == 3
    assert RANK["datasheet"] == 4
    assert RANK["legacy_model"] == RANK["legacy_architecture"] == 5
    assert RANK["correspondence"] == RANK["informal_note"] == 6
    assert rank_of("change_record", approved=False) > rank_of("change_record")


def test_approved_change_beats_spec_and_legacy_and_every_loser_is_kept():
    r = resolve_parameters([
        cand("tk", "high_level", "0.80", "m", source_id="cr_9", role="change_record"),
        cand("tk", "high_level", "0.78", "m"),
        cand("tk", "high_level", "0.78", "m", source_id="legacy", role="legacy_model"),
    ], registry())
    params = by_id(r)
    win = params["tk_high_level"]
    assert (win.value, win.status, win.authority) == (0.8, "effective", "cr_9")
    assert win.original.value == "0.80" and win.original.unit == "m"
    loser = params["tk_high_level_spec_1"]
    assert (loser.value, loser.status) == (0.78, "superseded")
    assert {t.source_id for t in loser.trace} == {"spec_1", "legacy"}
    assert len(r.conflicts) == 1
    c = r.conflicts[0]
    assert c.id == "cf_tk_high_level"
    assert (c.subject.element_id, c.subject.field) == ("tk_high_level", "value")
    assert [(x.value, x.source_id, x.authority_rank) for x in c.candidates] == [
        ("0.80 m", "cr_9", 1), ("0.78 m", "spec_1", 3), ("0.78 m", "legacy", 5)]
    assert c.candidates[0].element_id == "tk_high_level"
    assert c.candidates[2].element_id == "tk_high_level_spec_1"
    assert c.resolution == "0.80 m"
    assert c.rationale and "\n" not in c.rationale and "change_record" in c.rationale
    assert r.questions == []


def test_register_row_is_ranked_by_the_record_it_cites():
    r = resolve_parameters([
        cand("ctl", "wait", "12", "s", source_id="reg", role="register", cited="CR-9"),
        cand("ctl", "wait", "10", "s", source_id="reg", role="register", cited="SPEC-1"),
    ], registry())
    params = by_id(r)
    assert params["ctl_wait"].value == 12.0 and params["ctl_wait"].authority == "cr_9"
    assert params["ctl_wait_spec_1"].status == "superseded"
    assert [x.authority_rank for x in r.conflicts[0].candidates] == [1, 3]


def test_unknown_cited_record_is_reported_and_the_chunk_role_used():
    r = resolve_parameters([cand("ctl", "wait", "12", "s", source_id="reg", role="register",
                                 cited="XX-404")], registry())
    assert by_id(r)["ctl_wait"].authority == "reg"
    assert r.unresolved_citations == {"XX-404"}


def test_status_in_the_evidence_decides_before_the_ladder():
    r = resolve_parameters([
        cand("tk", "low", "0.1", "m", status="superseded"),
        cand("tk", "low", "0.05", "m", source_id="notes", role="informal_note",
             status="effective"),
    ], registry())
    params = by_id(r)
    assert params["tk_low"].value == 0.05 and params["tk_low"].authority == "notes"
    assert params["tk_low_spec_1"].status == "superseded"
    assert "evidence" in r.conflicts[0].rationale
    assert r.questions == []


def test_approval_outranks_recency():
    r = resolve_parameters([
        cand("tk", "high", "0.8", "m", source_id="cr_9", role="change_record", date="2026-03-11"),
        cand("tk", "high", "0.9", "m", source_id="mail", role="correspondence", date="2026-06-01"),
    ], registry())
    assert by_id(r)["tk_high"].value == 0.8


def test_within_one_rank_the_later_date_wins():
    r = resolve_parameters([
        cand("tk", "high", "0.8", "m", source_id="a", role="design_note", date="2026-01-01"),
        cand("tk", "high", "0.85", "m", source_id="b", role="design_note", date="2026-02-01"),
    ], registry())
    assert by_id(r)["tk_high"].value == 0.85 and r.questions == []
    assert "later" in r.conflicts[0].rationale


def test_equal_rank_disagreement_is_a_question_with_the_ladder_choice_as_default():
    r = resolve_parameters([
        cand("tk", "high", "0.8", "m", source_id="a", role="design_note"),
        cand("tk", "high", "0.85", "m", source_id="b", role="design_note"),
    ], registry())
    params = by_id(r)
    assert sum(p.status == "effective" for p in params.values()) == 1
    assert len(r.questions) == 1
    q = r.questions[0]
    assert set(q.options) == {"0.8 m", "0.85 m"}
    assert q.default_if_unanswered == params["tk_high"].original.value + " m"
    assert "tk_high" in q.affects
    assert r.conflicts[0].resolution == "unresolved"


def test_provisional_winner_is_a_question():
    r = resolve_parameters([
        cand("tk", "high", "0.8", "m", source_id="cr_9", role="change_record", provisional=True),
        cand("tk", "high", "0.78", "m"),
    ], registry())
    assert by_id(r)["tk_high"].value == 0.8
    assert len(r.questions) == 1 and "provisional" in r.questions[0].text


def test_configuration_variants_are_kept_but_are_not_conflicts():
    r = resolve_parameters([
        cand("tk", "area", "1.2", "m2"),
        cand("tk", "area", "1.25", "m2", source_id="asb", role="design_note",
             configuration="as_built"),
        cand("tk", "area", "1.3", "m2", source_id="tp", role="design_note",
             configuration="verification"),
    ], registry())
    params = by_id(r)
    assert params["tk_area"].value == 1.2 and params["tk_area"].status == "effective"
    statuses = sorted(p.status for p in params.values())
    assert statuses == ["as_built_only", "effective", "verification_only"]
    assert r.conflicts == [] and r.questions == []


def test_verification_documents_are_never_design_authority():
    r = resolve_parameters([
        cand("system", "stop_time", "900", "s", source_id="tp", role="verification_procedure"),
    ], registry())
    assert [(p.id, p.status) for p in r.parameters] == [("system_stop_time", "verification_only")]


def test_agreeing_values_are_one_parameter_traced_to_every_source():
    r = resolve_parameters([
        cand("tk", "area", "1.2", "m^2"),
        cand("tk", "area", "1200000", "mm2", source_id="b", role="design_note"),
    ], registry())
    assert r.problems  # mm2 is not in the unit table: reported, never guessed
    r = resolve_parameters([
        cand("tk", "area", "1.2", "m^2"),
        cand("tk", "area", "1.20", "m2", source_id="b", role="datasheet"),
    ], registry())
    assert [p.id for p in r.parameters] == ["tk_area"]
    assert {t.source_id for t in r.parameters[0].trace} == {"spec_1", "b"}
    assert r.conflicts == []


def test_values_are_converted_to_si_with_the_original_kept():
    r = resolve_parameters([cand("tk", "height", "900", "mm")], registry())
    p = r.parameters[0]
    assert (p.value, p.unit, p.original.value, p.original.unit) == (0.9, "m", "900", "mm")


def test_unknown_unit_is_a_question_and_no_parameter():
    r = resolve_parameters([cand("tk", "mass", "3", "stone")], registry())
    assert r.parameters == []
    assert len(r.questions) == 1 and "stone" in r.questions[0].text


def test_lists_and_plus_minus_values_parse():
    r = resolve_parameters([
        cand("pb", "press_times", "20, 280", "s", source_id="tp", role="verification_procedure"),
        cand("system", "tolerance", "+/-2", "s", source_id="tp", role="verification_procedure"),
        cand("system", "note", "about right", "s"),
    ], registry())
    params = by_id(r)
    assert params["pb_press_times"].value == [20.0, 280.0]
    assert params["system_tolerance"].value == 2.0
    assert "system_note" not in params and r.problems


def test_build_registry_from_headers_and_document_fragments():
    b = bundle([source("src_spec", "requirement_spec", document="SPEC-1", date="2026-01-15")],
               [chunk("src_spec", "p.1", "x")])
    sources, _ = ir_sources(b)
    doc = DocumentFragment(chunk_id="src_log#0", quote="CR-9 Approved", tag="CR-9",
                           title="Change request CR-9", role="change_record", approved=True,
                           date="2026-03-11", revision="1", file_name=None)
    docs, cited = build_registry(sources, [found(doc, source_id="log", role="change_record")])
    assert docs.get("spec-1").source_id == "spec_1"
    assert docs.get("CR 9") == DocInfo(source_id="cr_9", role="change_record",
                                       date="2026-03-11", approved=True)
    assert [(s.id, s.path, s.role, s.tags) for s in cited] == [
        ("cr_9", None, "change_record", ["CR-9"])]


def test_requirements_keep_status_and_superseded_by():
    def rf(tag, status="active", by=None, text="The tank shall not overflow."):
        return found(RequirementFragment(chunk_id="spec_1#0", quote=text, tag=tag, text=text,
                                         category="safety", status=status, superseded_by=by),
                     source_id="spec_1", role="requirement_spec")
    reqs = resolve_requirements([rf("REQ-1", "superseded", "REQ-2"), rf("REQ-2"),
                                 rf("REQ-3", "superseded", "REQ-404")])
    got = {r.id: (r.status, r.superseded_by) for r in reqs}
    assert got == {"req_1": ("superseded", "req_2"), "req_2": ("active", None),
                   "req_3": ("superseded", None)}
    assert all(r.trace for r in reqs)


def test_identifiers_without_letters_or_digits_are_ignored_not_fatal():
    b = bundle([source("src_spec", "requirement_spec", document="SPEC-1")],
               [chunk("src_spec", "p.1", "x")])
    sources, _ = ir_sources(b)
    doc = DocumentFragment(chunk_id="log#0", quote="-", tag="-", title=None, role="other",
                           approved=False, date=None, revision=None, file_name=None)
    docs, cited = build_registry(sources, [found(doc, source_id="log", role="register")])
    assert cited == []
    r = resolve_parameters([cand("tk", "-", "1", "m")], registry())
    assert r.parameters == [] and r.problems
    reqs = resolve_requirements([found(RequirementFragment(
        chunk_id="spec_1#0", quote="shall", tag="-", text="The tank shall hold.",
        category="functional", status="active", superseded_by="--"),
        source_id="spec_1", role="requirement_spec")])
    assert reqs[0].tags == [] and reqs[0].id.startswith("req_")


def test_cited_documents_match_bundle_files_by_file_name_or_source_id():
    b = bundle([source("src_05_mail_eml", "correspondence", path="05_mail.eml"),
                source("src_12_notes_txt", "informal_note", path="12_notes.txt")],
               [chunk("src_05_mail_eml", "m1", "x"), chunk("src_12_notes_txt", "l1", "y")])
    sources, _ = ir_sources(b)

    def doc(tag, file_name):
        return found(DocumentFragment(chunk_id="idx#0", quote=tag, tag=tag, title=None,
                                      role="correspondence", approved=True, date=None,
                                      revision=None, file_name=file_name),
                     source_id="idx", role="register")
    docs, cited = build_registry(sources, [doc("IDX-5", "05_mail.eml"),
                                           doc("src_12_notes_txt", None)])
    assert cited == []
    assert docs.get("IDX-5").source_id == "src_05_mail_eml"
    assert docs.get("src_12_notes_txt").source_id == "src_12_notes_txt"


def test_cited_document_matches_a_bundle_file_named_in_its_quote():
    b = bundle([source("src_05_mail_eml", "correspondence", path="dir/05_mail.eml")],
               [chunk("src_05_mail_eml", "m1", "x")])
    sources, _ = ir_sources(b)
    frag = DocumentFragment(chunk_id="idx#0", quote="Source ID: IDX-5 | Filename: 05_mail.eml",
                            tag="IDX-5", title=None, role="correspondence", approved=True,
                            date=None, revision=None, file_name=None)
    docs, cited = build_registry(sources, [found(frag, source_id="idx", role="register")])
    assert cited == [] and docs.get("IDX-5").source_id == "src_05_mail_eml"


def test_a_system_value_named_like_one_parts_value_joins_that_part():
    # fresh-run finding: one register's controller rows came back owned by the system in one
    # batch and by the controller in another, so 10 s and 12 s were never compared
    from specalive.core.ir import SYSTEM_OWNER
    from specalive.extract.precedence import adopt_system_values

    cands = [cand("plc", "wait_low", "10", "s"), cand(SYSTEM_OWNER, "wait_low", "12", "s"),
             cand(SYSTEM_OWNER, "stop_time", "900", "s"),
             cand("tk_1", "high", "1", "m"), cand("tk_2", "high", "2", "m"),
             cand(SYSTEM_OWNER, "high", "3", "m")]  # two parts own "high": not adopted
    owners = [o for o, _ in adopt_system_values(cands)]
    assert owners == ["plc", "plc", SYSTEM_OWNER, "tk_1", "tk_2", SYSTEM_OWNER]
