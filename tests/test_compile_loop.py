# Purpose: FR-06 requirements 11-14 and acceptance 5 for the compile-and-repair loop. Topology is
# read from the generated text by IR id, so a rename holds it and a deleted component or connect
# breaks it; each deterministic fix is tested on the omc message that triggers it; the loop runs
# against a scripted compiler and a scripted LLM (clean, deterministic fix, rejected and accepted
# LLM repairs, exhaustion, LLM failure, NOT RUN); a real omc run repairs a missing import.
import json
import re

import pytest
from pydantic import BaseModel

from specalive.config import Settings, load_settings
from specalive.core.catalogue import load_catalogue
from specalive.generate import modelica
from specalive.llm.client import LLMError
from specalive.repair import compile_loop
from specalive.repair.compile_loop import OmcMessage
from specalive.toolchain import omc
from tests._modelica_support import golden_model, plant_model, requires_omc

AREA_DECL = 'parameter Real tank_area(unit = "m2")'
SI_FAULT = "parameter SI.Area tank_area"
SI_ERROR = OmcMessage("Error", "Class SI.Area not found in scope System.", "model.mo", 12, 5,
                      "[model.mo:12:5-12:40:writable] Error: Class SI.Area not found in scope "
                      "System.")


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


@pytest.fixture(scope="module")
def plant(catalogue):
    return modelica.render_modelica(plant_model(), catalogue)


@pytest.fixture(scope="module")
def golden_text(catalogue):
    return modelica.render_modelica(golden_model(), catalogue).text


# --- topology -------------------------------------------------------------------------------

def test_topology_reads_instances_and_connections_by_ir_id(golden_text):
    topo = compile_loop.topology(golden_text)
    assert len(topo.instances) == 13 and len(topo.connections) == 16
    assert ("SpecAlive.Components.Tank", "tk_101") in topo.instances
    assert ("Controller_plc_101_sequence", "plc_101") in topo.instances
    assert frozenset({("src_101", "outlet"), ("xv_101", "inlet")}) in topo.connections


def test_topology_holds_under_a_rename(plant):
    renamed = re.sub(r"\bdrain\b(?=[ .])", "sink_x", plant.text)
    assert "sink_x.inlet" in renamed
    assert compile_loop.topology(renamed) == compile_loop.topology(plant.text)


def test_topology_breaks_when_a_component_or_connection_changes(plant):
    base = compile_loop.topology(plant.text)
    no_tank = "\n".join(line for line in plant.text.splitlines()
                        if '[IR tank]"' not in line)
    no_connect = plant.text.replace("connect(tank.level, ctl.level)", "// removed", 1)
    other_class = plant.text.replace("SpecAlive.Components.FluidSink drain",
                                     "SpecAlive.Components.FluidSource drain")
    untagged = plant.text.replace('"Drain [IR drain]"', '"Drain"')
    for changed in (no_tank, no_connect, other_class, untagged):
        assert changed != plant.text
        assert compile_loop.topology(changed) != base
        assert compile_loop.topology_diff(base, compile_loop.topology(changed))


def test_model_name_comes_from_the_package(plant):
    assert compile_loop.model_name_of(plant.text) == plant.model_name


# --- deterministic fixes ----------------------------------------------------------------------

def test_missing_import_is_inserted_into_the_scope_the_error_names(plant):
    broken = plant.text.replace(AREA_DECL, SI_FAULT)
    fixed = compile_loop.fix_missing_import(broken, [SI_ERROR])
    assert fixed is not None
    lines = fixed.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("  model System "))
    assert lines[header + 1] == "    import SI = Modelica.Units.SI;"
    assert compile_loop.fix_missing_import(fixed, [SI_ERROR]) is None  # already there


def test_unknown_alias_is_not_guessed(plant):
    msg = OmcMessage("Error", "Class Foo.Bar not found in scope System.", None, None, None,
                     "Error: Class Foo.Bar not found in scope System.")
    assert compile_loop.fix_missing_import(plant.text, [msg]) is None


def test_reserved_word_name_is_renamed(plant):
    broken = re.sub(r"\bdrain\b(?=[ .])", "end", plant.text)
    msg = OmcMessage("Error", "No viable alternative near token: FluidSink", "model.mo", 80, 26,
                     "[model.mo:80:26-80:35:writable] Error: No viable alternative near token: "
                     "FluidSink")
    fixed = compile_loop.fix_reserved_name(broken, [msg])
    assert fixed is not None
    assert "SpecAlive.Components.FluidSink end_ " in fixed and "end_.inlet" in fixed
    assert fixed.rstrip().endswith("end small_plant;")
    assert compile_loop.topology(fixed) == compile_loop.topology(plant.text)


def test_unit_spelling_is_normalised(plant):
    broken = plant.text.replace('tank_area(unit = "m2")', 'tank_area(unit = "m^2")')
    msg = OmcMessage("Notification", "Invalid unit expression 'm^2'.", "model.mo", 40, 5,
                     "[model.mo:40:5-40:60:writable] Notification: Invalid unit expression 'm^2'.")
    fixed = compile_loop.fix_unit_spelling(broken, [msg])
    assert fixed == plant.text


# --- the loop, with a scripted compiler and LLM ----------------------------------------------

class ScriptedCompiler:
    """Fails on the SI fault and on a BROKEN marker; records every file it compiled."""

    def __init__(self, status=omc.OK):
        self.status = status
        self.compiled = []

    def __call__(self, mo_path, model_name, work_dir):
        text = mo_path.read_text(encoding="utf-8")
        self.compiled.append(mo_path.name)
        if self.status == omc.NOT_RUN:
            return omc.CompileResult(omc.NOT_RUN, model_name, (), "omc not found", None)
        errors = []
        if SI_FAULT in text and "import SI = Modelica.Units.SI;" not in text:
            errors.append(SI_ERROR)
        if "BROKEN" in text:
            errors.append(OmcMessage("Error", "Missing token: SEMICOLON", None, None, None,
                                     "Error: Missing token: SEMICOLON"))
        status = omc.FAILED if errors else omc.OK
        return omc.CompileResult(status, model_name, tuple(errors), "scripted",
                                 f"cd {work_dir} && omc compile.mos")


class ScriptedLLM:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def complete(self, *, prompt, input_text, schema, **kwargs):
        self.calls.append((prompt, input_text, schema.__name__))
        reply = self.texts.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return schema.model_validate({"modelica": reply, "explanation": "scripted"})


def write_model(tmp_path, text):
    mo = tmp_path / modelica.MODEL_FILE
    mo.write_text(text, encoding="utf-8", newline="\n")
    return mo


def run(tmp_path, text, llm=None, compiler=None, attempts=3):
    compiler = compiler or ScriptedCompiler()
    result = compile_loop.run_compile_loop(
        write_model(tmp_path, text), tmp_path, settings=Settings(repair_attempts=attempts),
        llm=llm, ir_summary="parts: tank (tank)", compiler=compiler)
    log = json.loads((tmp_path / compile_loop.REPAIR_LOG).read_text(encoding="utf-8"))
    return result, log, compiler


def test_clean_model_stops_after_one_compile(tmp_path, plant):
    result, log, compiler = run(tmp_path, plant.text)
    assert result.status == compile_loop.OK
    assert result.delivered == tmp_path / modelica.MODEL_FILE
    assert compiler.compiled == ["model.mo"]
    assert [a["kind"] for a in log["attempts"]] == ["generated"]
    assert not (tmp_path / compile_loop.REPAIRED_FILE).exists()
    compile_log = (tmp_path / compile_loop.COMPILE_LOG).read_text(encoding="utf-8")
    assert "ok" in compile_log and result.command in compile_log


def test_deterministic_fix_repairs_a_missing_import(tmp_path, plant):
    # Acceptance 5, first half.
    result, log, _ = run(tmp_path, plant.text.replace(AREA_DECL, SI_FAULT))
    assert result.status == compile_loop.REPAIRED
    first, fix = log["attempts"]
    assert first["result"] == "failed" and "SI.Area" in first["errors_out"][0]
    assert fix["kind"] == "deterministic" and fix["fixes"] == ["missing_import"]
    assert fix["topology_held"] is True and fix["result"] == "ok"
    assert "+    import SI = Modelica.Units.SI;" in fix["change"]
    repaired = (tmp_path / compile_loop.REPAIRED_FILE).read_text(encoding="utf-8")
    assert "import SI = Modelica.Units.SI;" in repaired
    assert result.delivered == tmp_path / compile_loop.REPAIRED_FILE
    assert (tmp_path / compile_loop.ATTEMPTS_DIR / fix["file"].split("/")[-1]).is_file()


def test_llm_repair_that_deletes_a_component_is_rejected(tmp_path, plant):
    # Acceptance 5, second half / R-MO-4, R-MO-5.
    broken = plant.text.replace("  equation\n", "  equation\n    BROKEN\n", 1)
    assert broken != plant.text
    deletes_tank = "\n".join(line for line in plant.text.splitlines()
                             if '[IR tank]"' not in line) + "\n"
    llm = ScriptedLLM([deletes_tank, plant.text])
    result, log, _ = run(tmp_path, broken, llm=llm)
    kinds = [(a["kind"], a["topology_held"], a["result"]) for a in log["attempts"]]
    assert kinds == [("generated", True, "failed"), ("llm", False, "rejected"),
                     ("llm", True, "ok")]
    rejected = log["attempts"][1]
    assert any("tank" in line for line in rejected["topology_changes"])
    assert result.status == compile_loop.REPAIRED
    assert "rejected" in llm.calls[1][1]  # the second request is told why the first failed
    assert "Missing token" in llm.calls[0][1] and "parts: tank" in llm.calls[0][1]
    assert len(list((tmp_path / compile_loop.ATTEMPTS_DIR).glob("*.mo"))) == 2


def test_loop_gives_up_after_the_attempt_limit(tmp_path, plant):
    # Requirement 13 / R-MO-6: FAILED with the last errors; every attempt's file is kept.
    broken = plant.text.replace("  equation\n", "  equation\n    BROKEN\n", 1)
    llm = ScriptedLLM([broken, broken, broken, broken])
    result, log, _ = run(tmp_path, broken, llm=llm, attempts=3)
    assert result.status == compile_loop.FAILED
    assert len(llm.calls) == 3
    assert result.errors and "Missing token" in result.errors[0]
    assert len(list((tmp_path / compile_loop.ATTEMPTS_DIR).glob("*.mo"))) == 3
    assert not (tmp_path / compile_loop.REPAIRED_FILE).exists()
    assert result.delivered is None and log["status"] == compile_loop.FAILED


def test_llm_failure_stops_the_loop_and_is_logged(tmp_path, plant):
    broken = plant.text.replace("  equation\n", "  equation\n    BROKEN\n", 1)
    llm = ScriptedLLM([LLMError("rate limited", request_id="req_1")])
    result, log, _ = run(tmp_path, broken, llm=llm)
    assert result.status == compile_loop.FAILED
    assert log["attempts"][-1]["result"] == "error" and "rate limited" in result.detail


def test_without_an_llm_only_deterministic_fixes_run(tmp_path, plant):
    broken = plant.text.replace("  equation\n", "  equation\n    BROKEN\n", 1)
    result, log, _ = run(tmp_path, broken, llm=None)
    assert result.status == compile_loop.FAILED
    assert [a["kind"] for a in log["attempts"]] == ["generated"]
    assert "LLM" in result.detail


def test_compiler_not_run_is_reported_not_run(tmp_path, plant):
    result, log, _ = run(tmp_path, plant.text, compiler=ScriptedCompiler(omc.NOT_RUN))
    assert result.status == compile_loop.NOT_RUN
    assert log["status"] == compile_loop.NOT_RUN and result.command is None


def test_repair_reply_schema_is_strict_compatible():
    from specalive.llm.client import strict_json_schema
    schema = strict_json_schema(compile_loop.RepairReply)
    assert sorted(schema["required"]) == ["explanation", "modelica"]
    assert issubclass(compile_loop.RepairReply, BaseModel)


def test_ir_summary_lists_parts_and_connections(catalogue):
    summary = compile_loop.ir_summary(plant_model(), catalogue)
    assert "tank (tank) -> SpecAlive.Components.Tank" in summary
    assert "c1: feed_outlet -> v_in_inlet" in summary


# --- real omc ---------------------------------------------------------------------------------

@requires_omc
@pytest.mark.slow
def test_real_omc_repairs_an_injected_missing_import(tmp_path, golden_text):
    broken = golden_text.replace('parameter Real tk_101_area(unit = "m2")',
                                 "parameter SI.Area tk_101_area")
    assert broken != golden_text
    result = compile_loop.run_compile_loop(write_model(tmp_path, broken), tmp_path,
                                           settings=load_settings(), llm=None)
    assert result.status == compile_loop.REPAIRED, result.errors
    assert [a.kind for a in result.attempts] == ["generated", "deterministic"]
    assert result.attempts[1].fixes == ["missing_import"]
    assert "compile.mos" in result.command
    assert result.command in (tmp_path / compile_loop.COMPILE_LOG).read_text(encoding="utf-8")
