# Purpose: the `specalive` command line. Phase 1 fixes the subcommand set (one per pipeline stage,
# plus `run`, `cache clear` and `doctor`); the stage commands are stubs until their phases land.
# `doctor` proves the toolchain — Python, omc + MSL, the SysML v2 validator, the OpenAI API — and
# must pass before any modelling phase starts (R-FND-1). `ingest` (phase 3) reads a bundle into
# evidence.json and lists every file it could not fully read. `extract` (phase 4) turns
# evidence.json, or plain text, into ir.json and extract_report.json. `generate --only sysml`
# (phase 5) writes model.sysml and `compile --only sysml` writes sysml_validation.json with the
# command that reproduces it. Phase 6: `generate` also writes model.mo, and `compile` runs the
# Modelica compile-and-repair loop (compile.log, repair_log.json, model.repaired.mo) and prints
# the omc command that reproduces the compile. Phase 7: `verify` simulates the compiled model to
# sim/result.csv and writes verification.json (variable map, reference comparison, acceptance
# criteria, tolerances with their source) and coverage.json (only with --golden). Phase 8:
# `report --run` writes report/summary.md, traceability.md, assumptions.md, correspondence.md and
# report/plots/*.png from whatever artefacts the run folder holds. Top of the layer stack; nothing
# imports it.
from __future__ import annotations

import argparse
import dataclasses
import io
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from specalive import __version__
from specalive.config import ConfigError, Settings, load_settings
from specalive.core.catalogue import CatalogueError, load_catalogue
from specalive.extract.extract import (
    IR_FILE,
    EvidenceError,
    ExtractError,
    load_evidence,
    run_extract,
    write_ir,
    write_report,
)
from specalive.extract.text_input import text_bundle
from specalive.generate import modelica, sysml
from specalive.ingest.evidence import EvidenceBundle
from specalive.ingest.ingest import EVIDENCE_FILE, InputNotFound, ingest, write_evidence
from specalive.llm.cache import ResponseCache
from specalive.llm.client import LLMClient, LLMError
from specalive.repair import compile_loop
from specalive.report import artefacts, assumptions, correspondence, plots, summary, traceability
from specalive.toolchain import omc, sysml_validate
from specalive.verify import acceptance, compare, coverage, simulate

# FR-09 exit codes: 0 all gates passed, 1 a gate failed, 2 input problem, 3 toolchain problem.
EXIT_OK, EXIT_FAILED, EXIT_INPUT, EXIT_TOOLCHAIN = 0, 1, 2, 3

PROBE_FIXTURE = Path("tests/fixtures/probe.sysml")

STAGES = {
    "ingest": "read an input bundle into evidence.json (phase 3)",
    "extract": "turn evidence.json into ir.json (phase 4)",
    "generate": "generate model.sysml and model.mo from ir.json (phases 5, 6)",
    "compile": "validate the SysML and compile the Modelica, with repair (phases 5, 6)",
    "verify": "simulate and check against references and acceptance criteria (phase 7)",
    "report": "write the summary, traceability and assumption reports (phase 8)",
    "run": "run every stage from an input bundle or text (phase 9)",
}
STAGE_INPUT = {"ingest": "bundle", "run": "input"}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


class DoctorPing(BaseModel):
    ok: bool


def check_python(version_info: Sequence[int] = tuple(sys.version_info)) -> Check:
    found = ".".join(str(n) for n in version_info[:3])
    return Check("Python", tuple(version_info[:2]) == (3, 12), f"{found} (3.12 required)")


def check_omc(settings: Settings) -> Check:
    result = omc.probe(settings)
    return Check("omc + MSL", result.ok, result.detail)


def check_validator(settings: Settings) -> Check:
    if not PROBE_FIXTURE.is_file():
        return Check("SysML v2 validator", False,
                     f"{PROBE_FIXTURE} not found; run doctor from the project root")
    result = sysml_validate.probe(settings, PROBE_FIXTURE)
    return Check("SysML v2 validator", result.ok, result.detail)


def _redact(text: str, settings: Settings) -> str:
    if settings.openai_api_key:
        text = text.replace(settings.openai_api_key, "***")
    return re.sub(r"sk-[A-Za-z0-9_*\-]{4,}", "sk-***", text)


def check_openai(settings: Settings) -> Check:
    if not settings.has_api_key:
        return Check("OpenAI API", False, "OPENAI_API_KEY is not set")
    client = LLMClient(settings)
    try:
        reply = client.complete(prompt="Health check. Reply with ok set to true.",
                                input_text="specalive doctor", schema=DoctorPing)
    except LLMError as exc:
        return Check("OpenAI API", False, _redact(str(exc), settings))
    source = "from cache" if client.usage and client.usage[-1].cached else "live call"
    return Check("OpenAI API", reply.ok, f"key present; {settings.model} replied ({source})")


def doctor_checks(settings: Settings) -> list[Check]:
    return [check_python(), check_omc(settings), check_validator(settings),
            check_openai(settings)]


def cmd_doctor(settings: Settings) -> int:
    checks = doctor_checks(settings)
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"{'OK  ' if c.ok else 'FAIL'}  {c.name:<{width}}  {c.detail}")
    return EXIT_OK if all(c.ok for c in checks) else EXIT_TOOLCHAIN


def cmd_cache_clear(settings: Settings) -> int:
    removed = ResponseCache(settings.cache_dir).clear()
    print(f"removed {removed} cached response(s) from {settings.cache_dir}")
    return EXIT_OK


def cmd_ingest(settings: Settings, bundle: str | None, out: Path | None) -> int:
    if not bundle:
        print("specalive ingest: input problem: give a bundle folder or a file", file=sys.stderr)
        return EXIT_INPUT
    path = Path(bundle)
    out = out or Path("out") / (path.stem or "run")
    try:
        evidence = ingest(path, settings, llm=LLMClient(settings))
    except InputNotFound as exc:
        print(f"specalive ingest: input problem: {exc}", file=sys.stderr)
        return EXIT_INPUT
    target = write_evidence(evidence, out)
    counts = {status: sum(1 for s in evidence.sources if s.status == status)
              for status in ("read", "partial", "unread")}
    print(f"{len(evidence.sources)} source(s): {counts['read']} read, {counts['partial']} partial, "
          f"{counts['unread']} unread; {len(evidence.chunks)} chunk(s)")
    for s in evidence.sources:
        if s.status != "read":
            print(f"  {s.status:<7}  {s.path}  {s.reason}")
    print(f"wrote {target}")
    if not evidence.sources or counts["unread"] == len(evidence.sources):
        print("specalive ingest: input problem: nothing in the input could be read",
              file=sys.stderr)
        return EXIT_INPUT
    return EXIT_OK


def _extract_input(evidence: Path | None, text: str | None, text_file: str | None,
                   out: Path | None) -> tuple[EvidenceBundle, Path] | str:
    """The evidence to extract from and the output folder, or the input problem."""
    if text is not None or text_file is not None:
        name = "text"
        if text_file is not None:
            try:
                text = Path(text_file).read_text(encoding="utf-8")
            except OSError as exc:
                return f"cannot read {text_file}: {exc.strerror or exc}"
            name = Path(text_file).name
        if not (text or "").strip():
            return "the text is empty"
        return text_bundle(text or "", name), out or Path("out") / (Path(name).stem or "text")
    if out is None:
        out = evidence.parent if evidence is not None else Path("out") / "run"
    try:
        bundle = load_evidence(evidence or out / EVIDENCE_FILE)
    except EvidenceError as exc:
        return str(exc)
    if not bundle.chunks:
        return "the evidence holds nothing that could be read"
    return bundle, out


def cmd_extract(settings: Settings, evidence: Path | None, text: str | None,
                text_file: str | None, out: Path | None) -> int:
    got = _extract_input(evidence, text, text_file, out)
    if isinstance(got, str):
        print(f"specalive extract: input problem: {got}", file=sys.stderr)
        return EXIT_INPUT
    bundle, out = got
    try:
        result = run_extract(bundle, LLMClient(settings))
    except LLMError as exc:
        print(f"specalive extract: infrastructure problem: {_redact(str(exc), settings)}",
              file=sys.stderr)
        return EXIT_TOOLCHAIN
    except ExtractError as exc:
        write_report(exc.report, out)
        print(f"specalive extract: the extracted IR failed its integrity check: {exc}",
              file=sys.stderr)
        return EXIT_FAILED
    target = write_ir(result, out)
    m, r = result.model, result.report
    print(f"{len(m.parts)} part(s), {len(m.connections)} connection(s), "
          f"{len(m.parameters)} parameter(s), {len(m.state_machines)} state machine(s), "
          f"{len(m.requirements)} requirement(s)")
    print(f"{len(m.conflicts)} conflict(s), {len(m.questions)} question(s), "
          f"{len(m.assumptions)} assumption(s)")
    print(f"{len(r.discarded_fragments)} fragment(s) discarded, {len(r.unresolved)} unresolved, "
          f"{len(r.rejected_untraced)} element(s) rejected as untraced, "
          f"{len(r.missing_information)} missing-information item(s)")
    print(f"wrote {target}")
    return EXIT_OK


def cmd_stub(name: str) -> int:
    print(f"specalive {name}: not implemented in this phase", file=sys.stderr)
    return EXIT_FAILED


def cmd_generate(ir: Path | None, out: Path | None, only: str | None) -> int:
    ir_path = ir or (out or Path("out") / "run") / IR_FILE
    out = out or ir_path.parent
    try:
        model = sysml.load_ir(ir_path)
    except sysml.IRError as exc:
        print(f"specalive generate: input problem: {exc}", file=sys.stderr)
        return EXIT_INPUT
    try:
        catalogue = load_catalogue()
    except CatalogueError as exc:
        print(f"specalive generate: infrastructure problem: {exc}", file=sys.stderr)
        return EXIT_TOOLCHAIN
    if only in (None, "sysml"):
        try:
            target = sysml.write_sysml(model, catalogue, out)
        except sysml.SysmlGenerationError as exc:
            print(f"specalive generate: input problem: {exc}", file=sys.stderr)
            return EXIT_INPUT
        print(f"wrote {target}")
    if only in (None, "modelica"):
        try:
            target, generated = modelica.write_modelica(model, catalogue, out)
        except modelica.ModelicaGenerationError as exc:
            print(f"specalive generate: input problem: {exc}", file=sys.stderr)
            return EXIT_INPUT
        for note in generated.notes:
            print(f"  generator default / note: {note}")
        print(f"wrote {target} (model {generated.model_name})")
    return EXIT_OK


def _compile_sysml(settings: Settings, out: Path) -> int:
    model = out / sysml.MODEL_FILE
    if not model.is_file():
        print(f"specalive compile: input problem: {model} not found; run specalive generate "
              "first", file=sys.stderr)
        return EXIT_INPUT
    v = sysml_validate.validate_file(settings, model)
    target = sysml_validate.write_report(v, model, out / sysml_validate.REPORT_FILE)
    print(f"SysML validation: {v.status}: {v.detail}")
    for issue in (*v.errors, *v.warnings):
        print(f"  {issue.severity:<7}  line {issue.line}:{issue.column}  {issue.message}")
    if v.run:
        print(f"command: {v.run.command_line}")
        print(f"  stdin: {sysml_validate.report(v, model)['stdin']}")
    print(f"wrote {target}")
    return (EXIT_OK if v.ok else
            EXIT_TOOLCHAIN if v.status == sysml_validate.NOT_RUN else EXIT_FAILED)


def _repair_summary(out: Path) -> str:
    """The IR as the repair LLM sees it, when ir.json is beside the model; else empty."""
    try:
        return compile_loop.ir_summary(sysml.load_ir(out / IR_FILE), load_catalogue())
    except (sysml.IRError, CatalogueError):
        return ""


def _compile_modelica(settings: Settings, out: Path) -> int:
    model = out / modelica.MODEL_FILE
    if not model.is_file():
        print(f"specalive compile: input problem: {model} not found; run specalive generate "
              "first", file=sys.stderr)
        return EXIT_INPUT
    result = compile_loop.run_compile_loop(model, out, settings=settings,
                                           llm=LLMClient(settings),
                                           ir_summary=_repair_summary(out))
    print(f"Modelica compile: {result.status}: {result.detail}")
    for error in result.errors:
        print(f"  {error}")
    if result.delivered is not None:
        print(f"delivered: {result.delivered}")
    if result.command:
        print(f"command: {result.command}")
    print(f"wrote {out / compile_loop.COMPILE_LOG} and {out / compile_loop.REPAIR_LOG}")
    return {compile_loop.OK: EXIT_OK, compile_loop.REPAIRED: EXIT_OK,
            compile_loop.NOT_RUN: EXIT_TOOLCHAIN}.get(result.status, EXIT_FAILED)


def cmd_compile(settings: Settings, out: Path | None, only: str | None) -> int:
    out = out or Path("out") / "run"
    codes = []
    if only in (None, "sysml"):
        codes.append(_compile_sysml(settings, out))
    if only in (None, "modelica"):
        codes.append(_compile_modelica(settings, out))
    return max(codes)


VERIFICATION_FILE = "verification.json"
COVERAGE_FILE = "coverage.json"
_TOLERANCES = ("event_time", "continuous_fraction")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


def _coverage_report(model, golden: Path | None) -> dict | str:
    """coverage.json content, or the input problem with the reference IR."""
    if golden is None:
        return {"status": "NOT RUN", "reason": "no reference IR given (--golden)"}
    try:
        reference = sysml.load_ir(golden)
    except sysml.IRError as exc:
        return f"the reference IR {golden}: {exc}"
    return {"status": "ok", "reference": str(golden), **coverage.coverage(model, reference)}


def _reference_section(model, out: Path, explicit: Path | None, sim, vm,
                       tol) -> tuple[dict, list[dict]]:
    """The reference part of verification.json and one result per reference column. A bad
    --reference raises VerifyInputError; a bad reference found by ingestion is NOT RUN."""
    path, how = compare.find_reference(out, explicit)
    if path is None:
        return {"status": "NOT RUN", "reason": how}, []
    try:
        ref = compare.load_reference(path)
    except simulate.VerifyInputError as exc:
        if explicit is not None:
            raise
        return {"status": "NOT RUN", "path": str(path), "reason": str(exc)}, []
    mappings = compare.map_columns(ref, model, vm)
    section = {"status": "ok", "path": str(path), "found": how,
               "mapping": [dataclasses.asdict(m) for m in mappings]}
    if sim is None or sim.trace is None:
        return section, [{"column": m.column, "variable": m.variable, "ir_id": m.ir_id,
                          "kind": m.kind, "status": compare.NOT_COMPARED,
                          "detail": "no simulation result to compare", "numbers": {}}
                         for m in mappings]
    signals = compare.compare_signals(ref, sim.trace, mappings, model, vm, tol)
    return section, [dataclasses.asdict(s) for s in signals]


def _overall(sim_status: str, signals: list[dict], criteria: list[dict]) -> str:
    """FAIL on any failure; PASS only when something passed and the simulation ran clean."""
    statuses = [s["status"] for s in signals] + [c["status"] for c in criteria]
    if sim_status == omc.FAILED or "FAIL" in statuses:
        return "FAIL"
    if sim_status != omc.OK:
        return "NOT RUN"
    return "PASS" if "PASS" in statuses else "NOT CHECKED"


def _simulation_section(sim) -> dict:
    r = sim.result
    return {"status": r.status, "detail": r.detail, "command": r.command,
            "result": str(sim.result_csv) if sim.result_csv else None,
            "assertion": dataclasses.asdict(r.assertion) if r.assertion else None,
            "messages": [m.text for m in r.messages], "log": r.log}


def _print_verification(report: dict, cov: dict, out: Path) -> None:
    sim = report["simulation"]
    print(f"simulation: {sim['status']}: {sim['detail']}")
    if sim.get("command"):
        print(f"command: {sim['command']}")
    if report["reference"].get("status") != "ok":
        print(f"reference: NOT RUN: {report['reference'].get('reason')}")
    for s in report["signals"]:
        print(f"  signal     {s['status']:<12}  {s['column']}: {s['detail']}")
    for c in report["criteria"]:
        print(f"  criterion  {c['status']:<12}  {c['id']}: {c['detail']}")
    if cov.get("status") == "ok":
        print("coverage: " + ", ".join(f"{k} {cov[k]['percent']:g}%"
                                       for k in coverage.CATEGORIES))
    print(f"verification: {report['status']}")
    print(f"wrote {out / VERIFICATION_FILE} and {out / COVERAGE_FILE}")


def cmd_verify(settings: Settings, out: Path | None, reference: Path | None,
               golden: Path | None) -> int:
    out = out or Path("out") / "run"
    try:
        model = sysml.load_ir(out / IR_FILE)
    except sysml.IRError as exc:
        print(f"specalive verify: input problem: {exc}", file=sys.stderr)
        return EXIT_INPUT
    try:
        catalogue = load_catalogue()
    except CatalogueError as exc:
        print(f"specalive verify: infrastructure problem: {exc}", file=sys.stderr)
        return EXIT_TOOLCHAIN
    cov = _coverage_report(model, golden)
    if isinstance(cov, str):
        print(f"specalive verify: input problem: {cov}", file=sys.stderr)
        return EXIT_INPUT
    _write_json(out / COVERAGE_FILE, cov)

    tol = compare.tolerances(model, settings)
    report: dict = {
        "status": "NOT RUN", "model": None, "simulation": {}, "reference": {},
        "tolerances": [{"name": n, **dataclasses.asdict(getattr(tol, n))} for n in _TOLERANCES],
        "assumptions": [f"{n}: {getattr(tol, n).value:g} {getattr(tol, n).unit}, "
                        f"{getattr(tol, n).source}"
                        for n in _TOLERANCES if getattr(tol, n).declared_default],
        "variable_map": {}, "signals": [], "criteria": []}
    sim, vm, input_problem = None, simulate.VariableMap(), None
    try:
        choice = simulate.choose_model(out)
    except simulate.VerifyInputError as exc:
        input_problem = str(exc)
        report["simulation"] = {"status": omc.NOT_RUN, "detail": input_problem}
    else:
        sim = simulate.run_simulation(settings, choice, out)
        report["model"] = {"file": str(choice.path), "name": choice.name}
        report["simulation"] = _simulation_section(sim)
        vm = simulate.variable_map(model, catalogue, choice.path.read_text(encoding="utf-8"),
                                   choice.name)
        report["variable_map"] = {
            "ports": dict(sorted(vm.ports.items())),
            "states": {k: dataclasses.asdict(v) for k, v in sorted(vm.states.items())},
            "notes": vm.notes}
    try:
        report["reference"], report["signals"] = _reference_section(model, out, reference, sim,
                                                                    vm, tol)
    except simulate.VerifyInputError as exc:
        print(f"specalive verify: input problem: {exc}", file=sys.stderr)
        return EXIT_INPUT
    trace = sim.trace if sim else None
    criteria = acceptance.evaluate_criteria(
        model, trace, vm, complete=bool(sim and sim.result.ok),
        assertion=sim.result.assertion if sim else None,
        not_run_reason=input_problem or (sim.result.detail if sim and trace is None else None))
    report["criteria"] = [dataclasses.asdict(c) for c in criteria]
    sim_status = report["simulation"]["status"]
    report["status"] = _overall(sim_status, report["signals"], report["criteria"])
    _write_json(out / VERIFICATION_FILE, report)
    _print_verification(report, cov, out)

    if input_problem:
        print(f"specalive verify: input problem: {input_problem}", file=sys.stderr)
        return EXIT_INPUT
    if sim_status == omc.NOT_RUN:
        return EXIT_TOOLCHAIN
    return EXIT_FAILED if report["status"] == "FAIL" else EXIT_OK


def cmd_report(run: Path | None) -> int:
    run = run or Path("out") / "run"
    if not run.is_dir():
        print(f"specalive report: input problem: run folder {run} not found", file=sys.stderr)
        return EXIT_INPUT
    try:
        catalogue = load_catalogue()
    except CatalogueError as exc:
        print(f"specalive report: catalogue not loaded, ports not checked: {exc}",
              file=sys.stderr)
        catalogue = None
    loaded = artefacts.load_run(run)
    out = run / artefacts.REPORT_DIR
    figures = plots.write_plots(loaded, out / plots.PLOTS_DIR)
    table = correspondence.correspond(loaded, catalogue)
    written = [summary.write_summary(loaded, out, figures),
               traceability.write_traceability(loaded, out),
               assumptions.write_assumptions(loaded, out),
               correspondence.write_correspondence(loaded, catalogue, out)]
    for target in written:
        print(f"wrote {target}")
    counts = table.counts()
    print(f"correspondence: {len(table.rows)} element(s), {counts.get(correspondence.OK, 0)} OK, "
          f"{counts.get(correspondence.MISSING, 0)} MISSING, "
          f"{counts.get(artefacts.NOT_RUN, 0)} NOT RUN")
    if figures.status == "ok":
        print(f"plots: {len(figures.figures)} figure(s) in {out / plots.PLOTS_DIR}")
    else:
        print(f"plots: {figures.status}: {figures.reason}")
    for note in figures.notes:
        print(f"  {note}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specalive",
        description="Messy engineering inputs to a traced IR, SysML v2 and compiling Modelica.")
    parser.add_argument("--version", action="version", version=f"specalive {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    for name, help_text in STAGES.items():
        p = sub.add_parser(name, help=help_text)
        if name in STAGE_INPUT:
            p.add_argument(STAGE_INPUT[name], nargs="?")
        if name == "report":
            p.add_argument("--run", "-o", "--out", dest="out", type=Path,
                           help="run folder to report on (default: out/run)")
        else:
            p.add_argument("-o", "--out", type=Path, help="run output folder")
        if name == "extract":
            p.add_argument("-i", "--input", type=Path,
                           help="evidence.json to read (default: <out>/evidence.json)")
            p.add_argument("--text", help="extract from this paragraph instead of evidence")
            p.add_argument("--text-file", help="extract from this text file instead of evidence")
        if name == "generate":
            p.add_argument("--ir", type=Path, help="ir.json to read (default: <out>/ir.json)")
        if name == "verify":
            p.add_argument("--reference", type=Path,
                           help="reference trace CSV (default: ingestion's reference_data CSV)")
            p.add_argument("--golden", type=Path,
                           help="reference IR to score structural coverage against")
        if name in ("generate", "compile"):
            p.add_argument("--only", choices=("sysml", "modelica"),
                           help="run one model only (default: both)")
    cache = sub.add_parser("cache", help="manage the LLM response cache")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True, metavar="<action>")
    cache_sub.add_parser("clear", help="delete every cached LLM response")
    sub.add_parser("doctor", help="check Python, omc + MSL, the SysML validator and the OpenAI API")
    return parser


def _reconfigure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, io.UnsupportedOperation):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _reconfigure_streams()
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"specalive: configuration error: {exc}", file=sys.stderr)
        return EXIT_TOOLCHAIN
    if args.command == "doctor":
        return cmd_doctor(settings)
    if args.command == "cache":
        return cmd_cache_clear(settings)
    if args.command == "ingest":
        return cmd_ingest(settings, args.bundle, args.out)
    if args.command == "extract":
        return cmd_extract(settings, args.input, args.text, args.text_file, args.out)
    if args.command == "generate":
        return cmd_generate(args.ir, args.out, args.only)
    if args.command == "compile":
        return cmd_compile(settings, args.out, args.only)
    if args.command == "verify":
        return cmd_verify(settings, args.out, args.reference, args.golden)
    if args.command == "report":
        return cmd_report(args.out)
    return cmd_stub(args.command)


if __name__ == "__main__":
    sys.exit(main())
