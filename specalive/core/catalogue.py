# Purpose: loads catalogue/components.yaml — the only place that decides which SysML part def,
# which Modelica class (MSL, SpecAlive component, or generated) and which connector names an IR
# kind maps to (FR-02 requirements 15–18). Validation runs at load, so an unmapped connector or
# required attribute, or a default without its assumption text (R-CAT-2), fails before any
# generation; check_model() reports IR parts whose kind or port role the catalogue does not know.
# `measures` (phase 9) names the output of another kind that an instrument's input reads, so
# extraction can wire a sensor to the part its evidence names.
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from specalive.core.ir import Direction, Domain, SystemModel
from specalive.core.units import SI_UNITS

DEFAULT_CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "catalogue" / "components.yaml"


class CatalogueError(ValueError):
    """The catalogue file is missing, malformed, or has an inconsistent entry."""


class UnknownKind(KeyError):
    """An IR kind the catalogue does not define (R-CAT-1)."""


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True)


class PortSpec(_Entry):
    direction: Direction
    domain: Domain
    unit: str | None = None


class SysmlSpec(_Entry):
    part_def: str
    ports: dict[str, str] = Field({}, description="port role -> SysML port def")


class ModelicaSpec(_Entry):
    source: Literal["msl", "specalive", "generated"]
    class_: str | None = Field(None, alias="class")
    parameters: dict[str, str] = Field({}, description="IR parameter name -> Modelica parameter")
    connectors: dict[str, str] = Field({}, description="port role -> Modelica connector")


class Default(_Entry):
    value: float
    unit: str
    assumption: str = Field(description="recorded as an Assumption whenever the default is used")


class CatalogueEntry(_Entry):
    description: str
    ports: dict[str, PortSpec] = {}
    dynamic_ports: bool = Field(False, description="ports come from the IR part, not from here")
    measures: dict[str, str] = Field(
        {}, description="input port role -> the output port role of the part it measures")
    sysml: SysmlSpec
    modelica: ModelicaSpec
    required: list[str] = []
    defaults: dict[str, Default] = {}

    @model_validator(mode="after")
    def _consistent(self) -> CatalogueEntry:
        problems: list[str] = []
        m = self.modelica
        roles = set(self.ports)
        for label, mapped in (("modelica connector", m.connectors), ("sysml port", self.sysml.ports)):
            for role in sorted(set(mapped) - roles):
                problems.append(f"{label} for {role!r}, which is not in the port list")
            if not self.dynamic_ports:
                for role in sorted(roles - set(mapped)):
                    problems.append(f"port {role!r} has no {label}")
        for name in self.required:
            if name not in m.parameters:
                problems.append(f"required attribute {name!r} has no modelica parameter mapping")
        for name, default in self.defaults.items():
            if name not in m.parameters:
                problems.append(f"default {name!r} has no modelica parameter mapping")
            if not default.assumption.strip():
                problems.append(f"default {name!r} has no assumption text (R-CAT-2)")
            if default.unit not in SI_UNITS:
                problems.append(f"default {name!r} unit {default.unit!r} is not SI")
        for role in sorted(self.measures):
            if role not in self.ports or self.ports[role].direction != "in":
                problems.append(f"measures {role!r}, which is not an input port")
        for role, spec in self.ports.items():
            if spec.unit is not None and spec.unit not in SI_UNITS:
                problems.append(f"port {role!r} unit {spec.unit!r} is not SI")
        prefix = {"msl": "Modelica.", "specalive": "SpecAlive."}.get(m.source)
        if prefix and not (m.class_ or "").startswith(prefix):
            problems.append(f"modelica source {m.source!r} needs a class starting {prefix!r}")
        if m.source == "generated" and m.class_ is not None:
            problems.append("modelica source 'generated' must not name a class")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class Catalogue:
    def __init__(self, entries: dict[str, CatalogueEntry]) -> None:
        self._entries = dict(sorted(entries.items()))

    @property
    def kinds(self) -> list[str]:
        return list(self._entries)

    def __contains__(self, kind: object) -> bool:
        return kind in self._entries

    def entry(self, kind: str) -> CatalogueEntry:
        try:
            return self._entries[kind]
        except KeyError:
            raise UnknownKind(kind) from None

    def check_model(self, model: SystemModel) -> list[str]:
        """Problems between the IR's parts and the catalogue; empty when they agree."""
        problems: list[str] = []
        names = {(p.owner, p.name) for p in model.parameters if p.status == "effective"}
        for part in model.parts:
            if part.kind not in self._entries:
                problems.append(f"part {part.id!r}: kind {part.kind!r} is not in the catalogue")
                continue
            entry = self._entries[part.kind]
            if not entry.dynamic_ports:
                for port in part.ports:
                    spec = entry.ports.get(port.role)
                    if spec is None:
                        problems.append(f"part {part.id!r}: port role {port.role!r} is not "
                                        f"defined for kind {part.kind!r}")
                    elif (spec.direction, spec.domain) != (port.direction, port.domain):
                        problems.append(f"part {part.id!r}: port {port.id!r} is {port.direction} "
                                        f"{port.domain}, catalogue says {spec.direction} "
                                        f"{spec.domain}")
            for name in entry.required:
                if (part.id, name) not in names and name not in entry.defaults:
                    problems.append(f"part {part.id!r}: required attribute {name!r} has no "
                                    "effective parameter and no default")
        return problems


def load_catalogue(path: Path = DEFAULT_CATALOGUE_PATH) -> Catalogue:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogueError(f"cannot read catalogue {path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise CatalogueError(f"catalogue {path} is not valid YAML: {exc}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("kinds"), dict):
        raise CatalogueError(f"catalogue {path} must have a top-level 'kinds' mapping")
    entries: dict[str, CatalogueEntry] = {}
    problems: list[str] = []
    for kind, body in raw["kinds"].items():
        try:
            entries[kind] = CatalogueEntry.model_validate(body)
        except ValidationError as exc:
            details = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'entry'}: {e['msg']}"
                                for e in exc.errors())
            problems.append(f"kind {kind!r}: {details}")
    outputs = {role for e in entries.values() for role, spec in e.ports.items()
               if spec.direction == "out"}
    for kind, entry in sorted(entries.items()):
        for role, measured in sorted(entry.measures.items()):
            if measured not in outputs:
                problems.append(f"kind {kind!r}: measures {role!r} reads {measured!r}, which "
                                "is no kind's output port")
    if problems:
        raise CatalogueError(f"catalogue {path}:\n  " + "\n  ".join(problems))
    return Catalogue(entries)
