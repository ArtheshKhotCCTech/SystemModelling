# Purpose: pins the unit table (R-IR-4) — every unit that appears in the benchmark inputs
# converts to SI with the right factor or offset, spelling variants (m^3/s, m³/s, °C) are
# accepted, and a unit not in the table raises UnknownUnit instead of being guessed.
import pytest

from specalive.core.units import SI_UNITS, UnknownUnit, to_si


@pytest.mark.parametrize(
    "value,unit,si_value,si_unit",
    [
        (0.80, "m", 0.80, "m"),
        (500, "mm", 0.5, "m"),
        (1.2, "m²", 1.2, "m2"),
        (1.2, "m^2", 1.2, "m2"),
        (3, "m³", 3, "m3"),
        (12, "s", 12, "s"),
        (2, "h", 7200, "s"),
        (0.5, "kg/s", 0.5, "kg/s"),
        (0.0045, "m^3/s", 0.0045, "m3/s"),
        (0.0045, "m³/s", 0.0045, "m3/s"),
        (400, "ppm", 400e-6, "1"),
        (0.01, "kg/kg", 0.01, "kg/kg"),
        (101325, "Pa", 101325, "Pa"),
        (1.5, "bar", 1.5e5, "Pa"),
        (25, "°C", 298.15, "K"),
        (25, "degC", 298.15, "K"),
        (300, "K", 300, "K"),
        (100, "W", 100, "W"),
        (2, "A", 2, "A"),
        (20, "mA", 0.02, "A"),
        (24, "V", 24, "V"),
        (50, "Hz", 50, "Hz"),
        (200, "turns", 200, "1"),
        (3.6, "1/h", 0.001, "1/s"),
    ],
)
def test_benchmark_units_convert_to_si(value, unit, si_value, si_unit):
    got_value, got_unit = to_si(value, unit)
    assert got_value == pytest.approx(si_value)
    assert got_unit == si_unit
    assert got_unit in SI_UNITS


def test_surrounding_whitespace_is_ignored():
    assert to_si(1, " m ") == (1, "m")


def test_lists_convert_elementwise():
    values, unit = to_si([1, 2], "h")
    assert values == [3600, 7200]
    assert unit == "s"


@pytest.mark.parametrize("unit", ["furlong", "C", "", "m/s/s/s"])
def test_unknown_unit_raises(unit):
    with pytest.raises(UnknownUnit) as exc:
        to_si(1.0, unit)
    assert exc.value.unit == unit
