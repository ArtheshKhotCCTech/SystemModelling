# Purpose: pins the component catalogue (FR-02 requirements 15–18) — the shipped file loads and
# covers the L1 kinds, every entry names its Modelica target and where it comes from, and a
# broken entry (unmapped connector, unmapped required attribute, default without assumption
# text, R-CAT-2) fails at load with the kind named, so a bad catalogue never reaches generation.
import copy

import pytest
import yaml

from specalive.core.catalogue import (
    DEFAULT_CATALOGUE_PATH,
    CatalogueError,
    UnknownKind,
    load_catalogue,
)

L1_KINDS = {"tank", "on_off_valve", "level_sensor", "command_button", "sequence_controller",
            "fluid_source", "fluid_sink"}

VALVE = {
    "description": "Two-position valve.",
    "ports": {
        "inlet": {"direction": "in", "domain": "fluid", "unit": "m3/s"},
        "outlet": {"direction": "out", "domain": "fluid", "unit": "m3/s"},
        "cmd_in": {"direction": "in", "domain": "signal_bool"},
    },
    "sysml": {"part_def": "OnOffValve",
              "ports": {"inlet": "FluidPort", "outlet": "FluidPort", "cmd_in": "BoolSignal"}},
    "modelica": {"source": "specalive", "class": "SpecAlive.Components.OnOffValve",
                 "parameters": {"nominal_flow": "q_nominal"},
                 "connectors": {"inlet": "inlet", "outlet": "outlet", "cmd_in": "open"}},
    "required": ["nominal_flow"],
    "defaults": {},
}


def _write(tmp_path, kinds: dict):
    path = tmp_path / "components.yaml"
    path.write_text(yaml.safe_dump({"kinds": kinds}), encoding="utf-8")
    return path


def _bad(tmp_path, mutate, *fragments):
    entry = copy.deepcopy(VALVE)
    mutate(entry)
    with pytest.raises(CatalogueError) as exc:
        load_catalogue(_write(tmp_path, {"on_off_valve": entry}))
    for fragment in ("on_off_valve", *fragments):
        assert fragment in str(exc.value), str(exc.value)


# --- the shipped catalogue ----------------------------------------------------------------

def test_shipped_catalogue_loads_and_covers_l1():
    cat = load_catalogue(DEFAULT_CATALOGUE_PATH)
    assert L1_KINDS <= set(cat.kinds)


def test_kinds_are_sorted():
    cat = load_catalogue()
    assert cat.kinds == sorted(cat.kinds)


def test_every_shipped_entry_names_its_modelica_source():
    cat = load_catalogue()
    for kind in cat.kinds:
        m = cat.entry(kind).modelica
        assert m.source in {"msl", "specalive", "generated"}
        if m.source == "msl":
            assert m.class_.startswith("Modelica.")
        elif m.source == "specalive":
            assert m.class_.startswith("SpecAlive.")
        else:
            assert m.class_ is None


def test_level_sensor_uses_msl_pass_through():
    entry = load_catalogue().entry("level_sensor")
    assert entry.modelica.class_ == "Modelica.Blocks.Routing.RealPassThrough"
    assert set(entry.modelica.connectors.values()) == {"u", "y"}


def test_every_shipped_default_carries_assumption_text():
    cat = load_catalogue()
    for kind in cat.kinds:
        for name, default in cat.entry(kind).defaults.items():
            assert default.assumption.strip(), f"{kind}.{name}"


def test_unknown_kind_raises():
    with pytest.raises(UnknownKind):
        load_catalogue().entry("flux_capacitor")


def test_contains():
    cat = load_catalogue()
    assert "tank" in cat and "flux_capacitor" not in cat


# --- load-time validation -----------------------------------------------------------------

def test_valid_entry_loads(tmp_path):
    cat = load_catalogue(_write(tmp_path, {"on_off_valve": VALVE}))
    assert cat.entry("on_off_valve").modelica.connectors["cmd_in"] == "open"


def test_connector_for_unknown_port_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e["modelica"]["connectors"].update(ghost="g"), "ghost")


def test_sysml_port_for_unknown_port_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e["sysml"]["ports"].update(ghost="FluidPort"), "ghost")


def test_port_without_connector_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e["modelica"]["connectors"].pop("cmd_in"), "cmd_in")


def test_required_attribute_without_mapping_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e["required"].append("stroke_time"), "stroke_time")


def test_default_without_assumption_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e["defaults"].update(
        nominal_flow={"value": 0.001, "unit": "m3/s", "assumption": " "}), "nominal_flow")


def test_default_without_mapping_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e["defaults"].update(
        stroke_time={"value": 1, "unit": "s", "assumption": "Typical."}), "stroke_time")


def test_default_unit_must_be_si(tmp_path):
    _bad(tmp_path, lambda e: e["defaults"].update(
        nominal_flow={"value": 1, "unit": "l/min", "assumption": "Typical."}), "l/min")


def test_msl_source_needs_modelica_class(tmp_path):
    _bad(tmp_path, lambda e: e["modelica"].update(source="msl"), "Modelica.")


def test_generated_source_has_no_class(tmp_path):
    _bad(tmp_path, lambda e: e["modelica"].update(source="generated"), "class")


def test_unknown_field_is_rejected(tmp_path):
    _bad(tmp_path, lambda e: e.update(colour="red"), "colour")


def test_missing_file_is_a_catalogue_error(tmp_path):
    with pytest.raises(CatalogueError):
        load_catalogue(tmp_path / "missing.yaml")


def test_malformed_yaml_is_a_catalogue_error(tmp_path):
    path = tmp_path / "components.yaml"
    path.write_text("kinds: [unclosed", encoding="utf-8")
    with pytest.raises(CatalogueError):
        load_catalogue(path)


# --- checking a model against the catalogue -----------------------------------------------

def test_check_model_reports_unknown_kind_and_port_role():
    from test_ir import minimal

    from specalive.core.ir import SystemModel

    data = minimal()
    data["parts"][0]["kind"] = "flux_capacitor"
    data["parts"][1]["ports"][0]["role"] = "side_door"
    problems = load_catalogue().check_model(SystemModel.model_validate(data))
    assert any("flux_capacitor" in p for p in problems)
    assert any("side_door" in p for p in problems)
