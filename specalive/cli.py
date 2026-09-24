# Purpose: the `specalive` command line. Phase 1 fixes the subcommand set (one per pipeline stage,
# plus `run`, `cache clear` and `doctor`); the stage commands are stubs until their phases land.
# `doctor` proves the toolchain — Python, omc + MSL, the SysML v2 validator, the OpenAI API — and
# must pass before any modelling phase starts (R-FND-1). Top of the layer stack; nothing imports it.
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
from specalive.llm.cache import ResponseCache
from specalive.llm.client import LLMClient, LLMError
from specalive.toolchain import omc, sysml_validate

# FR-09 exit codes: 0 all gates passed, 1 a gate failed, 2 input problem, 3 toolchain problem.
EXIT_OK, EXIT_FAILED, EXIT_TOOLCHAIN = 0, 1, 3

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
    return cmd_stub(args.command)


if __name__ == "__main__":
    sys.exit(main())
