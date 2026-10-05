# Purpose: turns the project's structural rules into tests so a violation fails CI rather than
# waiting for review — config and the LLM client import without an API key (FR-01 acceptance 4),
# only config.py reads the environment (R-FND-2), the layer import table in ARCHITECTURE.md
# holds, and no test-case tag or value appears in the package (FR-11 item 8).
import os
import re
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "specalive"
SOURCES = sorted(PKG.rglob("*.py"))

# Layer -> layers it may import (ARCHITECTURE.md, "Allowed imports").
ALLOWED = {
    "config": set(),
    "core": {"config"},
    "llm": {"config", "core"},
    "ingest": {"config", "core", "llm"},
    "extract": {"config", "core", "llm", "ingest"},
    "generate": {"config", "core"},
    "toolchain": {"config"},
    "repair": {"config", "core", "llm", "generate", "toolchain"},
    "verify": {"config", "core", "toolchain"},
    "report": {"config", "core", "verify"},
}
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+specalive\.(\w+)", re.MULTILINE)


def _layer(path: Path) -> str:
    rel = path.relative_to(PKG)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def test_package_has_sources():
    assert SOURCES


def test_config_and_client_import_without_api_key():
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    r = subprocess.run([sys.executable, "-c", "import specalive.config, specalive.llm.client"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_only_config_reads_the_environment():
    offenders = [p.name for p in SOURCES
                 if p.name != "config.py" and re.search(r"os\.environ|os\.getenv|getenv\(",
                                                        p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_layer_imports_follow_the_architecture():
    violations = []
    for p in SOURCES:
        layer = _layer(p)
        if layer in ("cli", "__init__"):
            continue
        for target in IMPORT_RE.findall(p.read_text(encoding="utf-8")):
            if target != layer and target not in ALLOWED.get(layer, set()):
                violations.append(f"{p.relative_to(PKG)} imports specalive.{target}")
    assert violations == []


def test_nothing_imports_cli():
    offenders = [p.name for p in SOURCES if p.name != "cli.py"
                 and re.search(r"specalive\.cli|from \. import cli|from \.cli",
                               p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_no_case_specific_values_in_package():
    # L1 tags and values, and L2's (phase 10, FR-10 acceptance 5): the -201 tags, the 1000 ppm
    # mass fraction, the per-person emission, the legacy model name. Scanned: the package's
    # Python, Modelica and template files, and the catalogue, which is data but not test data.
    pattern = re.compile(r"TK-10|XV-10|RM-201|\bB[1-7]\b|0\.78|0\.80|_sysmlv2_"
                         r"|-201\b|1\.519|0\.001519|8\.18|RoomCO2")
    files = SOURCES + sorted(PKG.rglob("*.mo")) + sorted(PKG.rglob("*.j2"))
    files.append(PKG.parent / "catalogue" / "components.yaml")
    hits = [f"{p.relative_to(PKG.parent)}: {m.group(0)}" for p in files
            for m in pattern.finditer(p.read_text(encoding="utf-8"))]
    assert hits == []
