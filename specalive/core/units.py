# Purpose: explicit table from the units written in engineering inputs to SI (R-IR-4). Each
# entry is (SI unit, scale, offset), so °C → K is an offset and mm → m a scale. Spelling
# variants (m^3/s, m³/s, degC) normalise to one key. A unit not in the table raises UnknownUnit,
# which extraction turns into a Question — a unit is never guessed. Phase 10: a compound of table
# units ("kg/s per ACH", "1/(kg/kg)", "kg/(s.person)") is reduced by dimension to the one SI
# unit with that dimension; a part that is unknown, or has an offset (degC), keeps it unknown.
from __future__ import annotations

import re
from typing import overload

# written unit -> (SI unit, scale, offset): si = value * scale + offset
_TABLE: dict[str, tuple[str, float, float]] = {
    "m": ("m", 1.0, 0.0),
    "mm": ("m", 1e-3, 0.0),
    "cm": ("m", 1e-2, 0.0),
    "m2": ("m2", 1.0, 0.0),
    "m3": ("m3", 1.0, 0.0),
    "s": ("s", 1.0, 0.0),
    "min": ("s", 60.0, 0.0),
    "h": ("s", 3600.0, 0.0),
    "kg": ("kg", 1.0, 0.0),
    "kg/m3": ("kg/m3", 1.0, 0.0),
    "kg/s": ("kg/s", 1.0, 0.0),
    "m3/s": ("m3/s", 1.0, 0.0),
    # Mole/volume fraction; converting ppm to a mass fraction needs molar masses, not a unit table.
    "ppm": ("1", 1e-6, 0.0),
    "kg/kg": ("kg/kg", 1.0, 0.0),
    "pa": ("Pa", 1.0, 0.0),
    "kpa": ("Pa", 1e3, 0.0),
    "bar": ("Pa", 1e5, 0.0),
    "degc": ("K", 1.0, 273.15),
    "k": ("K", 1.0, 0.0),
    "w": ("W", 1.0, 0.0),
    "kw": ("W", 1e3, 0.0),
    "a": ("A", 1.0, 0.0),
    "ma": ("A", 1e-3, 0.0),
    "v": ("V", 1.0, 0.0),
    "hz": ("Hz", 1.0, 0.0),
    "turns": ("1", 1.0, 0.0),
    "1": ("1", 1.0, 0.0),
    "1/h": ("1/s", 1.0 / 3600.0, 0.0),
    "1/s": ("1/s", 1.0, 0.0),
    "ach": ("1/s", 1.0 / 3600.0, 0.0),  # air changes per hour
    # counts and normalised signals are dimensionless
    "person": ("1", 1.0, 0.0),
    "persons": ("1", 1.0, 0.0),
    "people": ("1", 1.0, 0.0),
    "count": ("1", 1.0, 0.0),
    "normalized": ("1", 1.0, 0.0),
    "normalised": ("1", 1.0, 0.0),
}

# SI unit -> exponents of (kg, m, s, K, A). A mass fraction (kg/kg) is dimensionless inside a
# compound. Ordered: the first unit of a dimension is the one a compound reduces to.
_DIMENSIONS: dict[str, tuple[int, ...]] = {
    "1": (0, 0, 0, 0, 0), "kg/kg": (0, 0, 0, 0, 0),
    "m": (0, 1, 0, 0, 0), "m2": (0, 2, 0, 0, 0), "m3": (0, 3, 0, 0, 0), "s": (0, 0, 1, 0, 0),
    "kg": (1, 0, 0, 0, 0), "kg/m3": (1, -3, 0, 0, 0), "kg/s": (1, 0, -1, 0, 0),
    "m3/s": (0, 3, -1, 0, 0), "1/s": (0, 0, -1, 0, 0), "Hz": (0, 0, -1, 0, 0),
    "Pa": (1, -1, -2, 0, 0), "K": (0, 0, 0, 1, 0), "W": (1, 2, -3, 0, 0),
    "A": (0, 0, 0, 0, 1), "V": (1, 2, -3, 0, -1),
}
_BY_DIMENSION: dict[tuple[int, ...], str] = {}
for _unit, _dim in _DIMENSIONS.items():
    _BY_DIMENSION.setdefault(_dim, "1" if not any(_dim) else _unit)
# one token of a compound unit: a bracket, an operator, the word "per", or a unit (which may hold
# spaces, as "kg/s per ACH" does not, but stops before the next operator)
_TOKEN = re.compile(r"""\s*(
      \( | \) | / | \* | · | \.
    | \bper\b
    | [^\s()/*·.]+ (?:\s+[^\s()/*·.]+)*? (?=\s*(?:[()/*·.]|\bper\b|$))
)""", re.IGNORECASE | re.VERBOSE)

# Keys whose case carries meaning are matched case-sensitively before lower-casing, so "C"
# (coulomb) never reads as Celsius and "K" / "k" stay unambiguous.
_CASE_SENSITIVE = {"m", "mm", "cm", "m2", "m3", "s", "min", "h", "kg", "kg/m3", "kg/s", "m3/s",
                   "ppm", "kg/kg", "turns", "1", "1/h", "1/s"}

SI_UNITS = frozenset(si for si, _, _ in _TABLE.values())


class UnknownUnit(ValueError):
    """A unit that is not in the table."""

    def __init__(self, unit: str) -> None:
        super().__init__(f"unknown unit {unit!r}")
        self.unit = unit


def _key(unit: str) -> str | None:
    text = (unit.strip().replace("²", "2").replace("³", "3").replace("^", "")
            .replace("°C", "degC").replace("℃", "degC"))
    if text in _CASE_SENSITIVE:
        return text
    lowered = text.lower()
    if lowered in _TABLE and lowered not in _CASE_SENSITIVE:
        return lowered
    return None


@overload
def to_si(value: float, unit: str) -> tuple[float, str]: ...
@overload
def to_si(value: list[float], unit: str) -> tuple[list[float], str]: ...


def _compound(unit: str) -> tuple[str, float]:
    """(SI unit, scale) of a product/quotient of table units, or UnknownUnit."""
    tokens: list[str] = []
    pos, text = 0, unit.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or not m.group(1):
            raise UnknownUnit(unit)
        tokens.append(m.group(1).strip())
        pos = m.end()

    def atom(tok: str) -> tuple[tuple[int, ...], float]:
        if tok == "1":
            return (0,) * 5, 1.0
        key = _key(tok)
        if key is None:
            raise UnknownUnit(unit)
        si, scale, offset = _TABLE[key]
        if offset or si not in _DIMENSIONS:
            raise UnknownUnit(unit)
        return _DIMENSIONS[si], scale

    def combine(a, b, sign: int):
        return tuple(x + sign * y for x, y in zip(a[0], b[0])), a[1] * b[1] ** sign

    def expr(i: int):
        left, i = term(i)
        while i < len(tokens) and tokens[i].lower() in ("/", "per"):
            right, i = term(i + 1)
            left = combine(left, right, -1)
        return left, i

    def term(i: int):
        left, i = factor(i)
        while i < len(tokens) and tokens[i] in ("*", ".", "·"):
            right, i = factor(i + 1)
            left = combine(left, right, 1)
        return left, i

    def factor(i: int):
        if i >= len(tokens):
            raise UnknownUnit(unit)
        if tokens[i] == "(":
            inner, i = expr(i + 1)
            if i >= len(tokens) or tokens[i] != ")":
                raise UnknownUnit(unit)
            return inner, i + 1
        if tokens[i] in ("(", ")", "/", "*", ".", "·") or tokens[i].lower() == "per":
            raise UnknownUnit(unit)
        return atom(tokens[i]), i + 1

    (dim, scale), end = expr(0)
    if end != len(tokens) or dim not in _BY_DIMENSION:
        raise UnknownUnit(unit)
    return _BY_DIMENSION[dim], scale


def to_si(value, unit):
    """Convert `value` (a number or a list of numbers) written in `unit` to SI."""
    key = _key(unit)
    if key is None:
        si_unit, scale = _compound(unit)
        offset = 0.0
    else:
        si_unit, scale, offset = _TABLE[key]
    if isinstance(value, list):
        return [v * scale + offset for v in value], si_unit
    return value * scale + offset, si_unit
