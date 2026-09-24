# Purpose: pins the external-tool layer (R-FND-4) — every call is bounded by a timeout and comes
# back as a structured result, never an exception for a tool-reported failure; the omc and
# SysML-validator output parsers are tested on recorded text; real-tool probes run only when
# the tool is installed and are skipped with a stated reason otherwise, never silently passed.
import sys
from pathlib import Path

import pytest

from specalive.config import load_settings
from specalive.toolchain import omc, sysml_validate
from specalive.toolchain.process import ToolResult, run_tool

PY = sys.executable
FIXTURE = Path(__file__).parent / "fixtures" / "probe.sysml"


# --- run_tool: exercised against the Python interpreter, so no external tool is needed ------

def test_success_is_structured():
    r = run_tool([PY, "-c", "print('hi')"], timeout=30)
    assert isinstance(r, ToolResult)
    assert r.ok and r.returncode == 0 and r.stdout.strip() == "hi"
    assert r.command[0] == PY and r.duration >= 0
    assert "print" in r.command_line


def test_nonzero_exit_is_not_ok_and_does_not_raise():
    r = run_tool([PY, "-c", "import sys; sys.stderr.write('bad'); sys.exit(3)"], timeout=30)
    assert not r.ok and r.returncode == 3 and "bad" in r.stderr


def test_timeout_is_not_ok_and_does_not_raise():
    r = run_tool([PY, "-c", "import time; time.sleep(10)"], timeout=0.5)
    assert not r.ok and r.returncode is None and "timed out" in r.stderr


def test_missing_executable_is_not_ok_and_does_not_raise():
    r = run_tool(["definitely-not-a-real-tool-xyz"], timeout=5)
    assert not r.ok and r.returncode is None and "not found" in r.stderr


def test_stdin_and_non_ascii_output_survive():
    code = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
    r = run_tool([PY, "-c", code], timeout=30, stdin_text="µ-flow ≥ 0.5 m³/s")
    assert r.ok and r.stdout == "µ-flow ≥ 0.5 m³/s"


# --- omc probe parsing -----------------------------------------------------------------------

def test_probe_script_loads_pinned_msl_and_simulates_controlled_tanks():
    script = omc.probe_script("4.0.0")
    assert 'loadModel(Modelica, {"4.0.0"})' in script
    assert "simulate(Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks" in script
    assert "getErrorString()" in script


def test_probe_script_reads_record_fields_into_variables_before_printing():
    # omc 1.27 rejects `res.resultFile` inside a string expression ("Variable res.resultFile
    # not found in scope"); assigning the field to a variable first works.
    script = omc.probe_script("4.0.0")
    assert "resultFile := res.resultFile;" in script
    assert "simMessages := res.messages;" in script
    assert "+ res." not in script


def _omc_out(loaded="true", result_file="C:/w/ControlledTanks_res.mat", sim_err="", load_err="",
             messages=""):
    return (f"SPECALIVE_LOADED={loaded}\nSPECALIVE_RESULTFILE={result_file}\n"
            f"SPECALIVE_LOADERR={load_err}\nSPECALIVE_SIMERR={sim_err}\n"
            f"SPECALIVE_MESSAGES={messages}\nSPECALIVE_END\n")


# Messages omc 1.27.1 returned for ControlledTanks when the runtime gave up (captured by hand).
_RUNTIME_FAILURE = (
    "Simulation execution failed for model: Modelica.StateGraph.Examples.ControlledTanks\n"
    "LOG_SUCCESS       | info    | The initialization finished successfully without homotopy method.\n"
    "LOG_ASSERT        | debug   | Simulation terminated due to too many, i.e. 20, event iterations.\n")


def test_parse_probe_runtime_failure_reports_simulation_messages():
    ok, detail = omc.parse_probe_output(_omc_out(result_file="", messages=_RUNTIME_FAILURE))
    assert not ok
    assert "Simulation execution failed" in detail
    assert "too many, i.e. 20, event iterations" in detail


def test_parse_probe_success_ignores_informational_messages():
    ok, _ = omc.parse_probe_output(_omc_out(messages="LOG_SUCCESS | info | The simulation finished successfully.\n"))
    assert ok


def test_parse_probe_success():
    ok, detail = omc.parse_probe_output(_omc_out())
    assert ok and "ControlledTanks_res.mat" in detail


def test_parse_probe_msl_not_loaded():
    ok, detail = omc.parse_probe_output(_omc_out(loaded="false", result_file="",
                                                 load_err="Error: Failed to load package"))
    assert not ok and "Failed to load package" in detail


def test_parse_probe_simulation_failed():
    ok, detail = omc.parse_probe_output(_omc_out(result_file="", sim_err="Error: build failed"))
    assert not ok and "build failed" in detail


def test_parse_probe_error_text_is_failure_even_with_result_file():
    ok, _ = omc.parse_probe_output(_omc_out(sim_err="Error: something went wrong"))
    assert not ok


def test_parse_probe_warnings_alone_are_not_failure():
    ok, detail = omc.parse_probe_output(_omc_out(sim_err="Warning: deprecated annotation"))
    assert ok and "Warning" in detail


def test_parse_probe_garbled_output_is_failure():
    ok, detail = omc.parse_probe_output("Segmentation fault")
    assert not ok and "unexpected" in detail.lower()


def test_omc_probe_reports_missing_tool_without_raising(tmp_path):
    s = load_settings({"SPECALIVE_OMC": str(tmp_path / "no-omc.exe")})
    result = omc.probe(s)
    assert not result.ok and "not found" in result.detail


# --- SysML validator output parsing ----------------------------------------------------------

PILOT_OK = "SysML v2 Pilot Implementation\n1> Package SpecAliveProbe (30842c66-9a56)\n2> \n"
PILOT_BAD = (
    "SysML v2 Pilot Implementation\n"
    "1> ERROR:Couldn't resolve reference to Type 'NoSuchType'. (1.sysml line : 2 column : 32)\n"
    "ERROR:An attribute must be typed by attribute definitions. (1.sysml line : 2 column : 18)\n"
    "WARNING:Bound features should have conforming types (1.sysml line : 8 column : 9)\n"
    "2> \n"
)


def test_parse_clean_output_has_no_issues():
    assert sysml_validate.parse_issues(PILOT_OK) == []


def test_parse_errors_and_warnings_with_locations():
    issues = sysml_validate.parse_issues(PILOT_BAD)
    assert [(i.severity, i.line, i.column) for i in issues] == [
        ("error", 2, 32), ("error", 2, 18), ("warning", 8, 9)]
    assert issues[0].message == "Couldn't resolve reference to Type 'NoSuchType'."


def test_interpret_clean_run_is_ok():
    r = ToolResult(True, ("java",), PILOT_OK, "", 1.0, 0)
    assert sysml_validate.interpret(r).ok


def test_interpret_errors_are_not_ok_even_with_exit_zero():
    r = ToolResult(True, ("java",), PILOT_BAD, "", 1.0, 0)
    v = sysml_validate.interpret(r)
    assert not v.ok and len(v.errors) == 2 and len(v.warnings) == 1


def test_interpret_java_exception_is_not_ok():
    r = ToolResult(True, ("java",), "SysML v2 Pilot Implementation\n",
                   'Exception in thread "main" java.io.FileNotFoundException: x', 1.0, 0)
    assert not sysml_validate.interpret(r).ok


def test_interpret_no_root_element_is_not_ok():
    r = ToolResult(True, ("java",), "SysML v2 Pilot Implementation\n1> \n", "", 1.0, 0)
    assert not sysml_validate.interpret(r).ok


def test_repl_input_wraps_model_in_block_and_exits():
    stdin = sysml_validate.repl_input("package P {}\n")
    assert stdin.splitlines() == ["%", "package P {}", "%", "%exit"]


def test_validator_missing_install_is_reported_without_raising(tmp_path):
    s = load_settings({"SPECALIVE_SYSML_VALIDATOR": str(tmp_path / "nowhere")})
    v = sysml_validate.validate_file(s, FIXTURE)
    assert not v.ok and "not found" in v.detail


# --- real tools: run only when installed ------------------------------------------------------

def _settings():
    return load_settings()


requires_omc = pytest.mark.skipif(not omc.version(_settings()).ok,
                                  reason="omc not installed or not on PATH/SPECALIVE_OMC")
requires_validator = pytest.mark.skipif(
    sysml_validate.find_jar(_settings()) is None,
    reason="SysML v2 Pilot Implementation not found at SPECALIVE_SYSML_VALIDATOR")


@requires_omc
@pytest.mark.slow
def test_real_omc_probe_simulates_controlled_tanks():
    result = omc.probe(_settings())
    assert result.ok, result.detail


@requires_validator
def test_real_validator_accepts_probe_fixture():
    v = sysml_validate.validate_file(_settings(), FIXTURE)
    assert v.ok, v.detail


@requires_validator
def test_real_validator_rejects_unresolved_type():
    text = "package Bad {\n    part def X { attribute a : NoSuchType; }\n}\n"
    v = sysml_validate.validate_text(_settings(), text)
    assert not v.ok and any("NoSuchType" in e.message for e in v.errors)
