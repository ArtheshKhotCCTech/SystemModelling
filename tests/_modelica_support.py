# Purpose: shared builders for the phase 6 tests — a small complete plant IR (source, two valves,
# tank, sink, two buttons, a controller with a timer, pause and history resume), the golden L1 IR,
# the omc availability marker, and `simulate_values`, which runs a generated model under omc and
# reads variables at given times so controller behaviour can be checked, not just its text.
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from specalive.config import load_settings
from specalive.core.ir import SystemModel
from specalive.toolchain import omc
from specalive.toolchain.process import run_tool

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "goldens" / "L1_tank.ir.json"
TRACE = [{"source_id": "src_a", "locator": "line 1", "quote": "q"}]

requires_omc = pytest.mark.skipif(not omc.version(load_settings()).ok,
                                  reason="omc not installed or not on PATH/SPECALIVE_OMC")


def golden_model() -> SystemModel:
    return SystemModel.model_validate_json(GOLDEN.read_text(encoding="utf-8"))


def port(pid, role, direction, domain, unit=None):
    return {"id": pid, "role": role, "direction": direction, "domain": domain, "unit": unit}


def param(pid, owner, name, value, unit, status="effective", assumption_ids=()):
    return {"id": pid, "owner": owner, "name": name, "value": value, "unit": unit,
            "original": {"value": str(value), "unit": unit}, "status": status,
            "authority": "src_a", "trace": TRACE, "assumption_ids": list(assumption_ids)}


def plant_ir() -> dict:
    """source -> v_in -> tank -> v_out -> sink; a controller fills to `high`, holds for
    `hold` seconds, drains to `low`; `go` starts and resumes, `halt` pauses with history."""
    return {
        "name": "small_plant",
        "description": "A tank filled and drained through two valves by a sequence controller.",
        "sources": [{"id": "src_a", "title": "Spec", "path": "a.txt", "role": "requirement_spec"}],
        "parts": [
            {"id": "feed", "kind": "fluid_source", "name": "Feed",
             "ports": [port("feed_outlet", "outlet", "out", "fluid", "m3/s")], "trace": TRACE},
            {"id": "v_in", "kind": "on_off_valve", "name": "Inlet valve",
             "ports": [port("v_in_inlet", "inlet", "in", "fluid", "m3/s"),
                       port("v_in_outlet", "outlet", "out", "fluid", "m3/s"),
                       port("v_in_cmd_in", "cmd_in", "in", "signal_bool")], "trace": TRACE},
            {"id": "tank", "kind": "tank", "name": "Tank \"A\"",
             "ports": [port("tank_inlet", "inlet", "in", "fluid", "m3/s"),
                       port("tank_outlet", "outlet", "out", "fluid", "m3/s"),
                       port("tank_level_out", "level_out", "out", "signal_real", "m")],
             "trace": TRACE},
            {"id": "v_out", "kind": "on_off_valve", "name": "Outlet valve",
             "ports": [port("v_out_inlet", "inlet", "in", "fluid", "m3/s"),
                       port("v_out_outlet", "outlet", "out", "fluid", "m3/s"),
                       port("v_out_cmd_in", "cmd_in", "in", "signal_bool")], "trace": TRACE},
            {"id": "drain", "kind": "fluid_sink", "name": "Drain",
             "ports": [port("drain_inlet", "inlet", "in", "fluid", "m3/s")], "trace": TRACE},
            {"id": "pb_go", "kind": "command_button", "name": "Go button",
             "ports": [port("pb_go_cmd_out", "cmd_out", "out", "signal_bool")], "trace": TRACE},
            {"id": "pb_halt", "kind": "command_button", "name": "Halt button",
             "ports": [port("pb_halt_cmd_out", "cmd_out", "out", "signal_bool")],
             "trace": TRACE},
            {"id": "ctl", "kind": "sequence_controller", "name": "Controller",
             "ports": [port("ctl_level", "level", "in", "signal_real", "m"),
                       port("ctl_go", "go", "in", "signal_bool"),
                       port("ctl_halt", "halt", "in", "signal_bool"),
                       port("ctl_open_in", "open_in", "out", "signal_bool"),
                       port("ctl_open_out", "open_out", "out", "signal_bool")],
             "assumption_ids": ["as_ctl"]},
        ],
        "connections": [
            {"id": "c1", "from_port": "feed_outlet", "to_port": "v_in_inlet",
             "medium_or_signal": "water", "trace": TRACE},
            {"id": "c2", "from_port": "v_in_outlet", "to_port": "tank_inlet",
             "medium_or_signal": "water", "trace": TRACE},
            {"id": "c3", "from_port": "tank_outlet", "to_port": "v_out_inlet",
             "medium_or_signal": "water", "trace": TRACE},
            {"id": "c4", "from_port": "v_out_outlet", "to_port": "drain_inlet",
             "medium_or_signal": "water", "trace": TRACE},
            {"id": "c5", "from_port": "tank_level_out", "to_port": "ctl_level",
             "medium_or_signal": "level", "trace": TRACE},
            {"id": "c6", "from_port": "pb_go_cmd_out", "to_port": "ctl_go",
             "medium_or_signal": "command", "trace": TRACE},
            {"id": "c7", "from_port": "pb_halt_cmd_out", "to_port": "ctl_halt",
             "medium_or_signal": "command", "trace": TRACE},
            {"id": "c8", "from_port": "ctl_open_in", "to_port": "v_in_cmd_in",
             "medium_or_signal": "command", "trace": TRACE},
            {"id": "c9", "from_port": "ctl_open_out", "to_port": "v_out_cmd_in",
             "medium_or_signal": "command", "trace": TRACE},
        ],
        "parameters": [
            param("tank_area", "tank", "area", 1.0, "m2"),
            param("tank_initial_level", "tank", "initial_level", 0.0, "m"),
            param("tank_high", "tank", "high", 0.5, "m"),
            param("tank_high_old", "tank", "high", 0.4, "m", "superseded"),
            param("tank_low", "tank", "low", 0.1, "m"),
            param("v_in_nominal_flow", "v_in", "nominal_flow", 0.01, "m3/s",
                  assumption_ids=["as_flow"]),
            param("v_out_nominal_flow", "v_out", "nominal_flow", 0.02, "m3/s"),
            param("ctl_hold", "ctl", "hold", 10.0, "s"),
            param("pb_go_press_times", "pb_go", "press_times", [5.0, 80.0], "s",
                  "verification_only"),
            param("pb_halt_press_times", "pb_halt", "press_times", [60.0], "s",
                  "verification_only"),
            param("system_stop_time", "system", "stop_time", 200.0, "s", "verification_only"),
        ],
        "state_machines": [{
            "id": "ctl_seq", "owner": "ctl", "initial": "idle",
            "events": [{"id": "go_cmd", "port": "ctl_go", "edge": "rising"},
                       {"id": "halt_cmd", "port": "ctl_halt", "edge": "rising"}],
            "timers": [{"id": "hold_timer", "duration": "ctl_hold"}],
            "states": [
                {"id": "idle", "name": "IDLE", "outputs": {}},
                {"id": "filling", "name": "FILLING", "outputs": {"ctl_open_in": True}},
                {"id": "holding", "name": "HOLDING", "entry_actions": [], "outputs": {}},
                {"id": "draining", "name": "DRAINING", "outputs": {"ctl_open_out": True}},
                {"id": "paused", "name": "PAUSED", "outputs": {}},
            ],
            "transitions": [
                {"id": "t_start", "from": "idle", "to": "filling", "trigger": "go_cmd",
                 "priority": 1},
                {"id": "t_fill_halt", "from": "filling", "to": "paused", "trigger": "halt_cmd",
                 "actions": ["save_history"], "priority": 1},
                {"id": "t_full", "from": "filling", "to": "holding",
                 "guard": "ctl_level >= tank_high", "actions": ["start_timer(hold_timer)"],
                 "priority": 2},
                {"id": "t_hold_halt", "from": "holding", "to": "paused", "trigger": "halt_cmd",
                 "actions": ["save_history"], "priority": 1},
                {"id": "t_held", "from": "holding", "to": "draining",
                 "guard": "timer_expired(hold_timer)", "priority": 2},
                {"id": "t_empty", "from": "draining", "to": "idle",
                 "guard": "ctl_level <= tank_low", "actions": ["clear_history"],
                 "priority": 1},
                {"id": "t_resume", "from": "paused", "to": "history", "trigger": "go_cmd",
                 "priority": 1},
            ],
            "trace": TRACE,
        }],
        "acceptance_criteria": [
            {"id": "ac_never_both", "text": "The two valves are never open together.",
             "check": {"mode": "always", "condition": "not (ctl_open_in and ctl_open_out)"}},
            {"id": "ac_windowed", "text": "Valves closed while paused.",
             "check": {"mode": "always", "condition": "not ctl_open_in",
                       "start_s": 60.0, "end_s": 80.0}},
        ],
        "assumptions": [
            {"id": "as_ctl", "text": "The controller is assumed to exist.", "basis": "inferred",
             "affects": ["ctl"], "confidence": 0.6},
            {"id": "as_flow", "text": "Constant nominal flow when open.",
             "basis": "engineering_convention", "affects": ["v_in"], "confidence": 0.8},
        ],
    }


def plant_model(ir: dict | None = None) -> SystemModel:
    return SystemModel.model_validate(ir if ir is not None else plant_ir())


_VALUE = re.compile(r"^SPECALIVE_VAL (\S+) (\S+) = (.*)$", re.MULTILINE)


def simulate_values(text: str, model_name: str,
                    probes: list[tuple[str, float]]) -> dict[tuple[str, float], float]:
    """Simulate `text` with omc and read each (variable, time) from the result."""
    settings = load_settings()
    lines = ["echo(false);", f'loadModel(Modelica, {{"{settings.msl_version}"}});',
             'loadFile("model.mo");', f"res := simulate({model_name});", "err := getErrorString();",
             "echo(true);", 'print("SPECALIVE_ERR=" + err + "\\n");']
    for name, t in probes:
        lines.append(f'print("SPECALIVE_VAL {name} {t!r} = " + String(val({name}, {t!r})) + "\\n");')
    with tempfile.TemporaryDirectory(prefix="specalive-sim-") as work:
        Path(work, "model.mo").write_text(text, encoding="utf-8")
        Path(work, "sim.mos").write_text("\n".join(lines) + "\n", encoding="utf-8")
        run = run_tool([settings.omc_path, "sim.mos"], timeout=settings.omc_timeout_s,
                       cwd=Path(work))
    assert "Error" not in run.stdout.split("SPECALIVE_VAL")[0], run.stdout
    return {(name, float(t)): float(v) for name, t, v in _VALUE.findall(run.stdout)}
