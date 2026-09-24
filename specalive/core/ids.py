# Purpose: the only way IR element ids are made (R-IR-3). make_id() folds a canonical tag to a
# lowercase identifier legal in both Modelica and SysML v2 (AB-123 → ab_123), prefixing the kind
# when the result starts with a digit or is a reserved word. IdRegistry is a per-run object that
# refuses two different tags collapsing onto one id, so naming is stable and collision-free.
from __future__ import annotations

import re
import unicodedata

# Modelica 3.6 keywords and built-ins that cannot be component names, and SysML v2 textual
# keywords. Over-inclusion is harmless: it only adds a prefix.
RESERVED = frozenset("""
    algorithm and annotation block break class connect connector constant constrainedby der
    discrete each else elseif elsewhen encapsulated end enumeration equation expandable extends
    external false final flow for function if import impure in initial inner input loop model
    not operator or outer output package parameter partial protected public pure record
    redeclare replaceable return stream then time true type when while within
    about abstract accept action actor after alias all allocate allocation analysis as assert
    assign assume at attribute bind binding by calc case comment concern connection constraint
    crosses decide def default defined dependency derived do doc entry enum event exhibit exit
    expose filter first fork frame from hastype implies include individual inout interface
    istype item join language library locale merge message meta metadata nonunique null
    objective occurrence of ordered out parallel part perform port private redefines ref
    references render rendering rep require requirement satisfy send snapshot specializes
    stakeholder standard state subject subsets succession terminate timeslice to transition
    until use variant variation verification verify via view viewpoint xor
""".split())

_KIND = re.compile(r"^[a-z][a-z0-9_]*$")
_NON_WORD = re.compile(r"[^a-z0-9]+")


class IdCollision(ValueError):
    """Two different tags would produce the same id."""


def _fold(tag: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", tag).encode("ascii", "ignore").decode("ascii")
    return _NON_WORD.sub("_", ascii_text.lower()).strip("_")


def make_id(kind: str, tag: str) -> str:
    """Deterministic identifier for an element of `kind` whose canonical tag is `tag`."""
    if not _KIND.match(kind):
        raise ValueError(f"kind {kind!r} must be a lowercase identifier")
    folded = _fold(tag)
    if not folded:
        raise ValueError(f"tag {tag!r} has no letters or digits to make an id from")
    if folded[0].isdigit() or folded in RESERVED:
        folded = f"{kind}_{folded}"
    return folded


class IdRegistry:
    """Ids made during one run; the same tag may repeat, two tags may not share an id."""

    def __init__(self) -> None:
        self._tag_of: dict[str, str] = {}

    def make(self, kind: str, tag: str) -> str:
        new_id = make_id(kind, tag)
        canonical = tag.strip()
        seen = self._tag_of.setdefault(new_id, canonical)
        if seen != canonical:
            raise IdCollision(f"id {new_id!r} is already used by tag {seen!r}; "
                              f"tag {canonical!r} would collide with it")
        return new_id
