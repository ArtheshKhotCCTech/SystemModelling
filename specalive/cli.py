# Purpose: the `specalive` command line. Phase 1 fixes the subcommand set (one per pipeline stage,
# plus `run`, `cache clear` and `doctor`); the stage commands are stubs until their phases land.
# `doctor` proves the toolchain — Python, omc + MSL, the SysML v2 validator, the OpenAI API — and
# must pass before any modelling phase starts (R-FND-1). `ingest` (phase 3) reads a bundle into
# evidence.json and lists every file it could not fully read. `extract` (phase 4) turns
# evidence.json, or plain text, into ir.json and extract_report.json. Top of the layer stack;
# nothing imports it.
from __future__ import annotations

import argparse
import io
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from specalive import __version__
from specalive.config import ConfigError, Settings, load_settings
from specalive.extract.extract import (
    EvidenceError,
    ExtractError,
    load_evidence,
    run_extract,
    write_ir,
    write_report,
)
from specalive.extract.text_input import text_bundle
from specalive.ingest.evidence import EvidenceBundle
from specalive.ingest.ingest import EVIDENCE_FILE, InputNotFound, ingest, write_evidence
from specalive.llm.cache import ResponseCache
from specalive.llm.client import LLMClient, LLMError
from specalive.toolchain import omc, sysml_validate

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
        p.add_argument("-o", "--out", type=Path, help="run output folder")
        if name == "extract":
            p.add_argument("-i", "--input", type=Path,
                           help="evidence.json to read (default: <out>/evidence.json)")
            p.add_argument("--text", help="extract from this paragraph instead of evidence")
            p.add_argument("--text-file", help="extract from this text file instead of evidence")
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
    return cmd_stub(args.command)


if __name__ == "__main__":
    sys.exit(main())
