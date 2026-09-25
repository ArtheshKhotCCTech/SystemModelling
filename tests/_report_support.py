# Purpose: shared builders for the phase 8 report tests — a run folder as the pipeline leaves it
# for the golden L1 IR: the real generated model.sysml and model.mo, a successful repair_log.json
# and sysml_validation.json, and verification.json written by the real `specalive verify` over a
# scripted simulation and a small reference CSV, so the reports read artefacts of the true shape.
from __future__ import annotations

import json
from pathlib import Path

from specalive import cli
from specalive.core.catalogue import load_catalogue
from specalive.core.ir import SystemModel
from specalive.generate import modelica, sysml
from specalive.toolchain import omc
from specalive.verify import simulate

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "goldens" / "L1_tank.ir.json"
COMPILE_COMMAND = "cd build && omc compile.mos"

# 0..900 s every 10 s: T1 fills from 0.05 m, the controller leaves IDLE for FILL_T1 at 20 s.
TIMES = [float(t) for t in range(0, 901, 10)]
_FILL = [0.05 if t < 20 else min(0.05 + 0.005 * (t - 20), 0.8) for t in TIMES]
_STATE = [1.0 if t < 20 else 2.0 for t in TIMES]  # enumeration order: idle, fill_t1, ...
_VALVE1 = [0.0 if t < 20 else 1.0 for t in TIMES]
SIM_VALUES = {"tk_101.level": _FILL, "tk_102.level": [0.05] * len(TIMES),
              "xv_101.open": _VALVE1, "plc_101.valve1": _VALVE1, "plc_101.state": _STATE}


def golden_ir() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def write_reference(path: Path) -> Path:
    lines = ["time_s,tank1_level_m,valve1_open,controller_state"]
    for t, h, v in zip(TIMES, _FILL, _VALVE1):
        lines.append(f"{t:g},{h:g},{int(v)},{'IDLE' if t < 20 else 'FILL_T1'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _scripted_simulation(settings, choice, run_dir):
    csv = Path(run_dir) / simulate.SIM_DIR / simulate.RESULT_FILE
    csv.parent.mkdir(parents=True, exist_ok=True)
    names = list(SIM_VALUES)
    rows = [",".join(["time", *names])]
    rows += [",".join(f"{v:g}" for v in [t, *(SIM_VALUES[n][i] for n in names)])
             for i, t in enumerate(TIMES)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    trace = simulate.Trace(list(TIMES), {n: list(v) for n, v in SIM_VALUES.items()})
    result = omc.SimulateResult(omc.OK, choice.name, csv, (), "", "scripted ok",
                                "cd sim && omc simulate.mos", None)
    return simulate.Simulation(result, choice, trace, csv)


def build_run(folder: Path, monkeypatch=None, ir: dict | None = None, *,
              reference: bool = True) -> Path:
    """A run folder for `ir` (default: the golden IR). With `monkeypatch`, `specalive verify`
    runs over the scripted simulation; without, the folder stops after compile."""
    folder.mkdir(parents=True, exist_ok=True)
    ir_text = json.dumps(ir if ir is not None else golden_ir(), indent=2)
    (folder / "ir.json").write_text(ir_text, encoding="utf-8")
    model = SystemModel.model_validate_json(ir_text)
    catalogue = load_catalogue()
    sysml.write_sysml(model, catalogue, folder)
    generated = modelica.render_modelica(model, catalogue)
    (folder / modelica.MODEL_FILE).write_text(generated.text, encoding="utf-8")
    log = {"status": "ok", "model": generated.model_name, "delivered": "model.mo",
           "command": COMPILE_COMMAND, "detail": "Check of the model completed successfully.",
           "errors": [], "attempts": []}
    (folder / "repair_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    validation = {"status": "ok", "ok": True, "detail": "no errors, no warnings",
                  "model": str(folder / "model.sysml"), "errors": [], "warnings": [],
                  "command": "java -jar sysml.jar", "stdin": "the model text"}
    (folder / "sysml_validation.json").write_text(json.dumps(validation, indent=2),
                                                  encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setattr(cli.simulate, "run_simulation", _scripted_simulation)
        args = ["verify", "-o", str(folder)]
        if reference:
            args += ["--reference", str(write_reference(folder.parent / "reference.csv"))]
        cli.main(args)
    return folder


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")
