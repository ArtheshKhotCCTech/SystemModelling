# Purpose: FR-10 acceptance for the hand-written L2 Room CO2 golden IR (phase 10): it validates
# against the IR and the catalogue, holds the effective values (300 ppm outdoor, peak 15, Kp 6.0,
# bias 3.5 ACH, limits 0.2-6.0 ACH, 8.18E-6 kg/s per person, in SI), keeps the superseded tuning
# with its conflicts, records the modelling devices as such (R-L2-2), quotes every source
# verbatim, generates SysML that validates and Modelica that compiles, and over 24 h stays
# under 1000 ppm within 1 % of the reference peak with supply positive and command negative.
import csv
import json
from pathlib import Path

import pytest

from _modelica_support import requires_omc, simulate_values
from specalive.config import load_settings
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel
from specalive.generate import modelica, sysml
from specalive.ingest.ingest import ingest
from specalive.toolchain import omc, sysml_validate

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "goldens" / "L2_co2.ir.json"
BUNDLE = ROOT / "Testcases" / "iaq_sysmlv2_full_dataset" / "iaq_sysmlv2_full_dataset"
REFERENCE = BUNDLE / "09_datasets" / "11_reference_run_24h.csv"
NOMINAL = 1.519e-3  # kg/kg that the project equates with 1000 ppm (IAQ-PER-005)
FR10_KINDS = {"room_volume", "mass_flow_source", "trace_substance_source", "pressure_boundary",
              "concentration_sensor", "gain", "p_controller", "schedule_table", "constant"}

requires_validator = pytest.mark.skipif(
    sysml_validate.find_jar(load_settings()) is None,
    reason="SysML v2 Pilot Implementation not found at SPECALIVE_SYSML_VALIDATOR")


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def model(data) -> SystemModel:
    return SystemModel.model_validate(data)


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


def _params(model):
    return {p.id: p for p in model.parameters}


# --- the IR ----------------------------------------------------------------------------------

def test_golden_validates_against_the_catalogue(model, catalogue):
    assert catalogue.check_model(model) == []
    assert {p.kind for p in model.parts} == FR10_KINDS


def test_every_input_is_wired(model):
    connected = {c.to_port for c in model.connections}
    open_inputs = [q.id for p in model.parts for q in p.ports
                   if q.direction == "in" and q.id not in connected]
    assert open_inputs == []


@pytest.mark.parametrize("pid, value, unit", [
    ("zon_201_volume", 100.0, "m3"),
    ("zon_201_density", 1.2, "kg/m3"),
    ("set_oa_201_value", 0.0004557, "kg/kg"),           # 300 ppm, not the legacy 350
    ("gain_peo_201_gain", 8.18e-8, "kg/s"),             # 8.18E-6 kg/s per person / 100
    ("src_co2_201_concentration", 100.0, "kg/kg"),
    ("ctl_co2_201_gain", 6.0 / 3600, "1/s"),            # 6.0 ACH per normalised error
    ("ctl_co2_201_bias", 3.5 / 3600, "1/s"),
    ("ctl_co2_201_output_min", 0.2 / 3600, "1/s"),
    ("ctl_co2_201_output_max", 6.0 / 3600, "1/s"),
    ("set_co2_201_value", 1.0, "1"),
    ("system_stop_time", 86400.0, "s"),
    ("system_output_interval", 60.0, "s"),
])
def test_effective_values_in_si(model, pid, value, unit):
    p = _params(model)[pid]
    assert p.status in ("effective", "verification_only") and p.unit == unit
    assert p.value == pytest.approx(value, rel=1e-6)


def test_occupancy_peaks_at_15_and_is_piecewise_constant(model):
    params = _params(model)
    times, values = params["sch_occ_201_times"].value, params["sch_occ_201_values"].value
    assert times == sorted(times) and len(times) == len(values) and times[0] == 0.0
    assert max(values) == 15.0 and values[times.index(13 * 3600.0)] == 15.0


def test_superseded_tuning_is_kept_and_named_in_conflicts(model):
    params = _params(model)
    assert params["ctl_co2_201_gain_cds_iaq_02"].status == "superseded"
    assert params["ctl_co2_201_gain_cds_iaq_02"].value == pytest.approx(4.0 / 3600)
    assert params["ctl_co2_201_bias_sim_legacy"].status == "superseded"
    subjects = {c.subject.element_id: c for c in model.conflicts}
    assert subjects["ctl_co2_201_gain"].resolution == "6 ACH/normalized"
    assert subjects["ctl_co2_201_bias"].resolution == "3.5 1/h"


def test_modelling_devices_are_recorded_as_such(model):
    # R-L2-2: the carrier concentration and the source sign convention are devices, each with
    # its own trace, not physical quantities
    parts = {p.id: p for p in model.parts}
    carrier, supply = parts["src_co2_201"], parts["src_oa_201"]
    assert "modelling device" in carrier.attributes["carrier_concentration"]
    assert any("100 kg/kg" in t.quote for t in carrier.trace)
    assert "negative" in supply.attributes["sign_convention"]
    assert any("negative mass-flow sign" in t.quote for t in supply.trace)


def test_the_limit_is_absolute_and_checked(model):
    ac = {a.id: a for a in model.acceptance_criteria}["ac_01"]
    assert ac.check is not None and ac.check.mode == "always"
    assert ac.check.condition == "zon_201_concentration_out <= system_nominal_concentration"
    reqs = {r.id for r in model.requirements}
    assert {"iaq_ctl_007", "iaq_fun_003", "iaq_ver_002"} <= reqs


def test_every_quote_is_verbatim_in_its_own_source(model):
    evidence = ingest(BUNDLE, load_settings())
    paths = {s.id: s.path for s in model.sources if s.path}
    by_path: dict[str, str] = {}
    for src in evidence.sources:
        text = " ".join(c.text for c in evidence.chunks if c.source_id == src.id)
        by_path[src.path.replace("\\", "/")] = " ".join(text.split())
    links = [t for group in (model.parts, model.connections, model.parameters,
                             model.requirements, model.acceptance_criteria, model.assumptions)
             for element in group for t in element.trace]
    missing = [f"{t.source_id}: {t.quote!r}" for t in links
               if " ".join(t.quote.split()) not in by_path[paths[t.source_id]]]
    assert links and missing == []


# --- generated models (FR-10 acceptance 1-3) ----------------------------------------------------

@pytest.fixture(scope="module")
def generated(model, catalogue):
    return modelica.render_modelica(model, catalogue)


@requires_validator
@pytest.mark.slow
def test_sysml_validates(model, catalogue):
    v = sysml_validate.validate_text(load_settings(), sysml.render_sysml(model, catalogue))
    assert v.ok and not v.errors and not v.warnings, (v.detail, v.issues)


@requires_omc
@pytest.mark.slow
def test_modelica_compiles(generated, tmp_path):
    mo = tmp_path / modelica.MODEL_FILE
    mo.write_text(generated.text, encoding="utf-8", newline="\n")
    result = omc.compile_model(load_settings(), mo, generated.model_name, tmp_path / "build")
    assert result.ok and result.errors == [], [m.text for m in result.messages]


@requires_omc
@pytest.mark.slow
def test_24_hours_stay_under_1000_ppm_within_1_percent_of_the_reference(generated):
    rows = list(csv.DictReader(REFERENCE.open(encoding="utf-8")))
    times = [float(r["time_s"]) for r in rows][::10] + [53940.0, 54000.0]
    probes = ([("zon_201.C", t) for t in times]
              + [(v, t) for t in (0.0, 30000.0, 54000.0, 80000.0)
                 for v in ("src_oa_201.outlet.m_flow", "src_oa_201.m_flow_in")])
    got = simulate_values(generated.text, generated.model_name, probes)
    peak = max(got[("zon_201.C", t)] for t in times) / NOMINAL * 1000.0
    reference = max(float(r["room_co2_ppm"]) for r in rows)
    assert peak <= 1000.0
    assert abs(peak - reference) <= 0.01 * reference, (peak, reference)
    for t in (0.0, 30000.0, 54000.0, 80000.0):
        assert got[("src_oa_201.outlet.m_flow", t)] > 0.0   # physical supply into the room
        assert got[("src_oa_201.m_flow_in", t)] < 0.0       # source command, port convention


def test_an_attribute_whose_unit_differs_per_part_is_untyped_on_its_def(model, catalogue):
    # a gain's or a constant's value has the unit of its use: kg/kg on one constant, 1 on another
    text = sysml.render_sysml(model, catalogue)
    block = text[text.index("part def ConstantSignal"):]
    block = block[:block.index("}")]
    assert "attribute value;" in block
    assert "attribute :>> value = 0.0004557 [kg/kg]" in text
    assert "attribute :>> value = 1" in text
