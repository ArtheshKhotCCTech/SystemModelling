# Purpose: explicit table from the units written in engineering inputs to SI (R-IR-4). Each
# entry is (SI unit, scale, offset), so °C → K is an offset and mm → m a scale. Spelling
# variants (m^3/s, m³/s, degC) normalise to one key. A unit not in the table raises UnknownUnit,
# which extraction turns into a Question — a unit is never guessed.
from __future__ import annotations

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
}

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


def to_si(value, unit):
    """Convert `value` (a number or a list of numbers) written in `unit` to SI."""
    key = _key(unit)
    if key is None:
        raise UnknownUnit(unit)
    si_unit, scale, offset = _TABLE[key]
    if isinstance(value, list):
        return [v * scale + offset for v in value], si_unit
    return value * scale + offset, si_unit
