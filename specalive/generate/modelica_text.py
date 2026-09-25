# Purpose: the Modelica lexical rules shared by the Modelica generator, the controller generator
# and the repair loop, so all three agree on what a legal name is: the Modelica 3.6 keywords
# (plus `time`, which a component must not shadow), IR ids made legal by a trailing underscore,
# string literals escaped for description strings and assert messages, and numbers written as
# Python's shortest round-trip repr. Also the one error type Modelica generation raises.
from __future__ import annotations

import re

KEYWORDS = frozenset("""
    algorithm and annotation block break class connect connector constant constrainedby der
    discrete each else elseif elsewhen encapsulated end enumeration equation expandable extends
    external false final flow for function if import impure in initial inner input loop model
    not operator or outer output package parameter partial protected public pure record
    redeclare replaceable return stream then time true type when while within
""".split())

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NON_WORD = re.compile(r"[^A-Za-z0-9_]+")
_WHITESPACE = re.compile(r"\s+")


class ModelicaGenerationError(ValueError):
    """The IR and the catalogue cannot be rendered as Modelica; the message names the element."""


def modelica_name(name: str) -> str:
    """`name` as a Modelica identifier: unchanged when legal, a keyword gets a trailing `_`."""
    if not _IDENT.match(name):
        raise ModelicaGenerationError(f"{name!r} is not a legal Modelica identifier")
    return f"{name}_" if name in KEYWORDS else name


def package_name(name: str) -> str:
    """A free-text model name folded to a legal package identifier."""
    folded = _NON_WORD.sub("_", name.strip()).strip("_") or "model"
    if folded[0].isdigit():
        folded = f"m_{folded}"
    return modelica_name(folded)


def one_line(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def string(text: str) -> str:
    """A Modelica string literal on one line."""
    return '"' + one_line(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def number(value: float) -> str:
    text = repr(float(value))
    if text in ("inf", "-inf", "nan"):
        raise ModelicaGenerationError(f"value {value!r} has no Modelica literal")
    return text
