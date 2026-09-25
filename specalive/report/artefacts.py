# Purpose: every report is built from artefacts on disk, and a missing artefact must make its
# section say NOT RUN with the reason rather than disappear (R-REP-3). This module loads a run
# folder once into a `Run` of `Artefact`s, each loaded, missing or invalid with the reason, and
# holds the Markdown helpers the five reports share: escaped table cells and deterministic writes.
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from specalive.core.ir import SystemModel
from specalive.verify import simulate

REPORT_DIR = "report"
NOT_RUN = "NOT RUN"
LOADED, MISSING, INVALID = "loaded", "missing", "invalid"

IR_FILE = "ir.json"
SYSML_FILE = "model.sysml"
MODELICA_FILE = "model.mo"
SYSML_VALIDATION = "sysml_validation.json"
REPAIR_LOG = simulate.REPAIR_LOG
VERIFICATION = "verification.json"
COVERAGE = "coverage.json"
EVIDENCE = "evidence.json"
EXTRACT_REPORT = "extract_report.json"


@dataclass(frozen=True)
class Artefact:
    name: str
    state: str  # LOADED | MISSING | INVALID
    data: object = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == LOADED

    @property
    def not_run(self) -> str:
        """The text a section shows in place of what this artefact would have given."""
        return f"{NOT_RUN} — {self.reason}"


@dataclass(frozen=True)
class Run:
    run_dir: Path
    ir: Artefact  # data: SystemModel
    sysml: Artefact  # data: str
    modelica: Artefact  # data: str, the delivered model (the repaired file when there is one)
    sysml_validation: Artefact
    repair_log: Artefact
    verification: Artefact
    coverage: Artefact
    evidence: Artefact
    extract_report: Artefact

    @property
    def model(self) -> SystemModel | None:
        return self.ir.data if self.ir.ok else None


def _missing(name: str, why: str = "") -> Artefact:
    return Artefact(name, MISSING, reason=f"{name} not found{why}")


def _text(run_dir: Path, name: str) -> Artefact:
    path = run_dir / name
    if not path.is_file():
        return _missing(name)
    try:
        return Artefact(name, LOADED, path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return Artefact(name, INVALID, reason=f"{name} is unreadable: {exc}")


def _json(run_dir: Path, name: str) -> Artefact:
    got = _text(run_dir, name)
    if not got.ok:
        return got
    try:
        data = json.loads(got.data)
    except json.JSONDecodeError as exc:
        return Artefact(name, INVALID, reason=f"{name} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        return Artefact(name, INVALID, reason=f"{name} does not hold a JSON object")
    return Artefact(name, LOADED, data)


def _ir(run_dir: Path) -> Artefact:
    got = _text(run_dir, IR_FILE)
    if not got.ok:
        return got
    try:
        return Artefact(IR_FILE, LOADED, SystemModel.model_validate_json(got.data))
    except ValidationError as exc:
        lines = [e["msg"] for e in exc.errors()][:3]
        return Artefact(IR_FILE, INVALID, reason=f"{IR_FILE} is not a valid IR: "
                                                  + "; ".join(lines))


def _delivered_modelica(run_dir: Path, repair_log: Artefact) -> Artefact:
    """The model the compile stage delivered, else the generated file."""
    delivered = repair_log.data.get("delivered") if repair_log.ok else None
    if delivered and (run_dir / delivered).is_file():
        return _text(run_dir, delivered)
    return _text(run_dir, MODELICA_FILE)


def load_run(run_dir: Path) -> Run:
    run_dir = Path(run_dir)
    repair_log = _json(run_dir, REPAIR_LOG)
    return Run(run_dir=run_dir, ir=_ir(run_dir), sysml=_text(run_dir, SYSML_FILE),
               modelica=_delivered_modelica(run_dir, repair_log),
               sysml_validation=_json(run_dir, SYSML_VALIDATION), repair_log=repair_log,
               verification=_json(run_dir, VERIFICATION), coverage=_json(run_dir, COVERAGE),
               evidence=_json(run_dir, EVIDENCE), extract_report=_json(run_dir, EXTRACT_REPORT))


def source_label(model: SystemModel, source_id: str) -> str:
    """How the inputs cite a source: its first tag and revision, e.g. 'URS-001 Rev A'."""
    source = next((s for s in model.sources if s.id == source_id), None)
    if source is None:
        return source_id
    label = source.tags[0] if source.tags else source.id
    return f"{label} Rev {source.revision}" if source.revision else label


# --- Markdown -----------------------------------------------------------------------------

def cell(value: object) -> str:
    """One table cell: a single line, pipes escaped."""
    text = "" if value is None else str(value)
    return " ".join(text.split()).replace("|", "\\|")


def table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return lines


def write_report(out_dir: Path, name: str, text: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    target.write_text(text, encoding="utf-8", newline="\n")
    return target
