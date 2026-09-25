# Purpose: pins the external-tool layer (R-FND-4) — every call is bounded by a timeout and comes
# back as a structured result, never an exception for a tool-reported failure; the omc and
# SysML-validator output parsers are tested on recorded text; real-tool probes run only when
# the tool is installed and are skipped with a stated reason otherwise, never silently passed.
# Phase 5: a validation is ok, failed or NOT RUN, and its report names the command (R-SYS-6).
# Phase 6: the compile script, omc message parsing, and compile verdicts ok / failed / NOT RUN.
# Phase 7: the simulate script, simulation verdicts, and an assert stop read as data.
import json
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


# --- omc compile (phase 6) -------------------------------------------------------------------

def test_compile_script_loads_pinned_msl_checks_and_builds():
    # FR-06 requirement 10: getErrorString() after every step.
    script = omc.compile_script("../model.mo", "Pkg.System", "4.0.0")
    lines = script.splitlines()
    steps = ['loadModel(Modelica, {"4.0.0"})', 'loadFile("../model.mo")', "checkModel(Pkg.System)",
             "buildModel(Pkg.System)"]
    positions = [next(i for i, line in enumerate(lines) if step in line) for step in steps]
    assert positions == sorted(positions)
    for pos in positions:
        assert "getErrorString()" in lines[pos + 1]


def _compile_out(msl="true", loaded="true", check="Check of Pkg.System completed successfully.",
                 exe="C:/w/Pkg.System", msl_err="", load_err="", check_err="", build_err=""):
    return ("true\n"
            f"SPECALIVE_MSL={msl}\nSPECALIVE_FILE={loaded}\nSPECALIVE_CHECK={check}\n"
            f"SPECALIVE_EXE={exe}\nSPECALIVE_MSLERR={msl_err}\nSPECALIVE_LOADERR={load_err}\n"
            f"SPECALIVE_CHECKERR={check_err}\nSPECALIVE_BUILDERR={build_err}\nSPECALIVE_END\n")


OMC_ERROR = ("[C:/work dir/model.mo:138:5-138:57:writable] Error: Class SI.Area not found in "
             "scope System.\n")


def test_parse_messages_reads_location_severity_and_text():
    text = OMC_ERROR + "Warning: The initial conditions are not fully specified.\nsecond line\n"
    msgs = omc.parse_messages(text)
    assert [(m.severity, m.line, m.column) for m in msgs] == [("Error", 138, 5),
                                                              ("Warning", None, None)]
    assert msgs[0].file == "C:/work dir/model.mo"
    assert msgs[0].message == "Class SI.Area not found in scope System."
    assert msgs[0].text == OMC_ERROR.strip()
    assert msgs[1].message.endswith("second line")


def test_interpret_clean_compile():
    status, detail, msgs = omc.interpret_compile(_compile_out(build_err="Warning: minor\n"))
    assert status == omc.OK and "completed successfully" in detail
    assert [m.severity for m in msgs] == ["Warning"]


@pytest.mark.parametrize("kwargs,needle", [
    ({"check": "", "exe": "", "check_err": OMC_ERROR}, "SI.Area"),
    ({"loaded": "false", "check": "", "exe": "", "load_err": OMC_ERROR}, "did not load"),
    ({"exe": ""}, "no executable"),
    ({"check": "Something else"}, "checkModel"),
])
def test_interpret_failed_compile(kwargs, needle):
    status, detail, _ = omc.interpret_compile(_compile_out(**kwargs))
    assert status == omc.FAILED and needle in detail


def test_interpret_msl_missing_is_not_run():
    status, detail, _ = omc.interpret_compile(_compile_out(msl="false", msl_err="Error: no MSL"))
    assert status == omc.NOT_RUN and "MSL" in detail


def test_interpret_garbled_output_is_failure():
    status, detail, _ = omc.interpret_compile("Segmentation fault")
    assert status == omc.FAILED and "unexpected" in detail


def test_compile_model_without_omc_is_not_run(tmp_path):
    mo = tmp_path / "model.mo"
    mo.write_text("package P end P;\n", encoding="utf-8")
    s = load_settings({"SPECALIVE_OMC": str(tmp_path / "no-omc.exe")})
    result = omc.compile_model(s, mo, "P.System", tmp_path / "build")
    assert result.status == omc.NOT_RUN and "not found" in result.detail
    assert not result.ok and result.command is None
    assert (tmp_path / "build" / omc.COMPILE_SCRIPT).is_file()


# --- omc simulate (phase 7) ------------------------------------------------------------------

def test_simulate_script_loads_msl_and_file_then_simulates_to_csv():
    # FR-07 requirement 1: the experiment annotation gives stop time and interval; CSV output.
    script = omc.simulate_script("../model.mo", "Pkg.System", "4.0.0")
    lines = script.splitlines()
    steps = ['loadModel(Modelica, {"4.0.0"})', 'loadFile("../model.mo")',
             'simulate(Pkg.System, outputFormat="csv")']
    positions = [next(i for i, line in enumerate(lines) if step in line) for step in steps]
    assert positions == sorted(positions)
    for pos in positions:
        assert "getErrorString()" in lines[pos + 1]
    assert "stopTime" not in script and "numberOfIntervals" not in script


def test_simulate_script_without_file_simulates_an_msl_class():
    script = omc.simulate_script(None, "Modelica.Blocks.Examples.PID_Controller", "4.0.0")
    assert "loadFile" not in script
    assert 'simulate(Modelica.Blocks.Examples.PID_Controller, outputFormat="csv")' in script


def _simulate_out(msl="true", loaded="true", msl_err="", load_err="", sim_err="",
                  messages="LOG_SUCCESS       | info    | The simulation finished successfully.\n"):
    return ("true\n"
            f"SPECALIVE_MSL={msl}\nSPECALIVE_FILE={loaded}\nSPECALIVE_MSLERR={msl_err}\n"
            f"SPECALIVE_LOADERR={load_err}\nSPECALIVE_SIMERR={sim_err}\n"
            f"SPECALIVE_MESSAGES={messages}\nSPECALIVE_END\n")


# Runtime messages omc 1.27.1 returned when an assert stopped a run (captured by hand).
ASSERT_LOG = """Simulation execution failed for model: A
LOG_SUCCESS       | info    | The initialization finished successfully without homotopy method.
LOG_ASSERT        | info    | [C:/w/a.mo:4:3-4:44:writable]
|                 | |       | The following assertion has been violated at time 12.500000
|                 | |       | ((not y)) --> "ac_x: never y after 12.5"
LOG_ASSERT        | info    | Found event, previous asserts are ignored.
LOG_ASSERT        | info    | [C:/w/a.mo:4:3-4:44:writable]
|                 | |       | The following assertion has been violated at time 13.000000
|                 | |       | ((not y)) --> "ac_x: never y after 12.5"
LOG_ASSERT        | error   | No event found, but assert was triggered. Throwing now!
"""


def test_interpret_clean_simulation():
    status, detail, msgs, log, assertion = omc.interpret_simulate(
        _simulate_out(sim_err="Warning: The initial conditions are not fully specified.\n"))
    assert status == omc.OK and assertion is None
    assert "finished successfully" in detail and "finished successfully" in log
    assert [m.severity for m in msgs] == ["Warning"]


def test_interpret_assert_stop_is_a_failure_with_time_and_message():
    # FR-07 requirement 2: an interlock assert is data, with the time the run stopped.
    status, detail, _, log, assertion = omc.interpret_simulate(_simulate_out(messages=ASSERT_LOG))
    assert status == omc.FAILED
    # first reported at the event (12.5 s); the run threw at the next step (13 s)
    assert assertion == omc.AssertionStop(12.5, "ac_x: never y after 12.5", 13.0)
    assert "12.5" in detail and "ac_x" in detail
    assert log == ASSERT_LOG.strip()


def test_parse_assertion_of_a_clean_log_is_none():
    assert omc.parse_assertion("LOG_SUCCESS | info | The simulation finished successfully.") is None


@pytest.mark.parametrize("kwargs,status,needle", [
    ({"msl": "false", "msl_err": "Error: no MSL"}, omc.NOT_RUN, "MSL"),
    ({"loaded": "false", "load_err": OMC_ERROR}, omc.FAILED, "did not load"),
    ({"sim_err": OMC_ERROR, "messages": ""}, omc.FAILED, "SI.Area"),
    ({"messages": "Simulation execution failed for model: P.System\nLOG_STDOUT | error | "
                  "division by zero\n"}, omc.FAILED, "division by zero"),
])
def test_interpret_failed_simulation(kwargs, status, needle):
    got, detail, _, _, _ = omc.interpret_simulate(_simulate_out(**kwargs))
    assert got == status and needle in detail


def test_interpret_garbled_simulation_output_is_failure():
    status, detail, *_ = omc.interpret_simulate("Segmentation fault")
    assert status == omc.FAILED and "unexpected" in detail


def test_simulate_without_omc_is_not_run(tmp_path):
    mo = tmp_path / "model.mo"
    mo.write_text("package P end P;\n", encoding="utf-8")
    s = load_settings({"SPECALIVE_OMC": str(tmp_path / "no-omc.exe")})
    result = omc.simulate(s, "P.System", tmp_path / "sim", mo)
    assert result.status == omc.NOT_RUN and "not found" in result.detail
    assert result.command is None and result.result_file is None
    assert (tmp_path / "sim" / omc.SIMULATE_SCRIPT).is_file()


def test_simulate_timeout_is_a_failure_not_a_crash(tmp_path, monkeypatch):
    mo = tmp_path / "model.mo"
    mo.write_text("package P end P;\n", encoding="utf-8")
    monkeypatch.setattr(omc, "run_tool", lambda *a, **k: ToolResult(
        False, ("omc",), "", "timed out after 5 s", 5.0, None))
    result = omc.simulate(load_settings({}), "P.System", tmp_path / "sim", mo)
    assert result.status == omc.FAILED and "timed out" in result.detail


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


# Recorded from the Pilot (kernel 0.62.0): after a warning the root echo loses its "1> " prefix.
PILOT_WARN_ONLY = (
    "SysML v2 Pilot Implementation\r\n"
    "1> WARNING:Duplicate of inherited member name 'start' from Part (1.sysml line : 30 column : 18)\n"
    "Package FixturePartDefAttributes (0e0e3b6a-7c65-473c-a143-a399386bffed)\n2> "
)


def test_interpret_warnings_only_is_ok_when_root_follows_the_warning():
    v = sysml_validate.interpret(ToolResult(True, ("java",), PILOT_WARN_ONLY, "", 1.0, 0))
    assert v.ok and v.status == sysml_validate.OK and len(v.warnings) == 1


def test_status_distinguishes_failed_from_not_run(tmp_path):
    bad = sysml_validate.interpret(ToolResult(True, ("java",), PILOT_BAD, "", 1.0, 0))
    assert bad.status == sysml_validate.FAILED
    no_java = sysml_validate.interpret(
        ToolResult(False, ("java",), "", "executable not found: java", 0.0, None))
    assert no_java.status == sysml_validate.NOT_RUN and not no_java.ok
    crash = sysml_validate.interpret(ToolResult(True, ("java",), "SysML v2 Pilot Implementation\n",
                                                'Exception in thread "main" boom', 1.0, 0))
    assert crash.status == sysml_validate.NOT_RUN
    missing = sysml_validate.validate_file(
        load_settings({"SPECALIVE_SYSML_VALIDATOR": str(tmp_path / "nowhere")}), FIXTURE)
    assert missing.status == sysml_validate.NOT_RUN and "not found" in missing.detail


def test_unreadable_model_is_not_run(tmp_path):
    v = sysml_validate.validate_file(load_settings(), tmp_path / "missing.sysml")
    assert v.status == sysml_validate.NOT_RUN and "cannot read" in v.detail


def test_report_carries_status_issues_and_the_command(tmp_path):
    run = ToolResult(True, ("java", "-cp", "pilot all.jar", "Main"), PILOT_BAD, "", 1.0, 0)
    v = sysml_validate.interpret(run)
    target = sysml_validate.write_report(v, tmp_path / "model.sysml", tmp_path / "v.json")
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["ok"] is False
    assert report["errors"][0] == {"line": 2, "column": 32,
                                   "message": "Couldn't resolve reference to Type 'NoSuchType'."}
    assert len(report["warnings"]) == 1
    assert report["command"] == run.command_line and "%exit" in report["stdin"]
    assert report["model"].endswith("model.sysml")


def test_report_of_a_run_that_did_not_happen_says_not_run(tmp_path):
    v = sysml_validate.Validation(sysml_validate.NOT_RUN, "SysML v2 Pilot Implementation not found")
    report = sysml_validate.report(v, tmp_path / "model.sysml")
    assert report["status"] == "NOT RUN" and report["ok"] is False
    assert report["command"] is None and "not found" in report["detail"]


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
