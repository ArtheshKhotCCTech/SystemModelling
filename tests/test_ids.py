# Purpose: pins deterministic id construction (R-IR-3) — a canonical tag becomes a lowercase
# identifier legal in both Modelica and SysML v2, the same tag always gives the same id, reserved
# words and leading digits are prefixed with the kind, and a registry refuses two different tags
# that would collapse onto one id; sysml_name() quotes a name SysML v2 would read as a keyword.
import re

import pytest

from specalive.core.ids import IdCollision, IdRegistry, make_id, sysml_name

LEGAL = re.compile(r"^[a-z_][a-z0-9_]*$")


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("TK-101", "tk_101"),
        ("XV-101", "xv_101"),
        ("URS-FUN-004", "urs_fun_004"),
        ("PB-START", "pb_start"),
        ("  Fill T1  ", "fill_t1"),
        ("WAIT_AFTER_FILL", "wait_after_fill"),
        ("a--b__c", "a_b_c"),
        ("Température °C", "temperature_c"),
    ],
)
def test_make_id_normalises_tags(tag, expected):
    assert make_id("part", tag) == expected


def test_make_id_is_deterministic():
    assert make_id("part", "LT-102") == make_id("part", "LT-102")


@pytest.mark.parametrize("tag", ["101", "3-way valve"])
def test_leading_digit_gets_kind_prefix(tag):
    result = make_id("part", tag)
    assert result.startswith("part_")
    assert LEGAL.match(result)


@pytest.mark.parametrize("word", ["model", "end", "in", "out", "part", "state", "time", "flow"])
def test_reserved_words_get_kind_prefix(word):
    assert make_id("state", word) == f"state_{word}"


@pytest.mark.parametrize("tag", ["", "   ", "---", "°"])
def test_tag_without_letters_or_digits_is_rejected(tag):
    with pytest.raises(ValueError):
        make_id("part", tag)


def test_kind_must_be_an_identifier():
    with pytest.raises(ValueError):
        make_id("Part Kind", "TK-101")


def test_registry_returns_same_id_for_same_tag():
    reg = IdRegistry()
    assert reg.make("part", "TK-101") == reg.make("part", "TK-101") == "tk_101"


def test_registry_rejects_two_tags_collapsing_to_one_id():
    reg = IdRegistry()
    reg.make("part", "TK-101")
    with pytest.raises(IdCollision) as exc:
        reg.make("part", "TK_101")
    assert "tk_101" in str(exc.value)
    assert "TK-101" in str(exc.value) and "TK_101" in str(exc.value)


def test_registry_rejects_same_id_across_kinds():
    reg = IdRegistry()
    reg.make("part", "IDLE")
    with pytest.raises(IdCollision):
        reg.make("state", "idle ")


def test_registries_are_independent():
    a, b = IdRegistry(), IdRegistry()
    a.make("part", "TK-101")
    assert b.make("part", "TK_101") == "tk_101"


# --- SysML names (FR-05 requirement 6: escaping lives here, not in the templates) -----------

@pytest.mark.parametrize("name", ["tk_101", "FluidPort", "_x1"])
def test_sysml_name_leaves_plain_identifiers_alone(name):
    assert sysml_name(name) == name


@pytest.mark.parametrize("name,expected", [
    ("state", "'state'"), ("part", "'part'"), ("in", "'in'"), ("level-1", "'level-1'"),
    ("1st", "'1st'"), ("it's", "'it\\'s'"), ("a\\b", "'a\\\\b'"),
])
def test_sysml_name_quotes_keywords_and_illegal_names(name, expected):
    assert sysml_name(name) == expected


def test_sysml_name_rejects_empty():
    with pytest.raises(ValueError):
        sysml_name("")
