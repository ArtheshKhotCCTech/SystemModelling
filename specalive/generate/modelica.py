# Purpose: renders the IR as one Modelica package (FR-06 requirements 1-7), deterministically and
# without any LLM: the SpecAlive component classes the model uses, a controller class per state
# machine (controller.py), and a System model with one top-level parameter per usable IR value,
# one instance per part of the class the catalogue names, one connect() per connection, IR ids
# in description strings, ASSUMPTION comments, and an experiment annotation. Every value the
# generator supplies itself (catalogue or tool default) is a comment and a returned note.
# Each instance is placed and each connect drawn (layout.py), so a tool shows the diagram; the
# annotations are graphics only and change no equation.
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import jinja2

from specalive.core.catalogue import Catalogue
from specalive.core.ir import SYSTEM_OWNER, Parameter, Part, SystemModel
from specalive.generate import controller, layout
from specalive.generate.modelica_text import (
    ModelicaGenerationError,
    modelica_name,
    number,
    one_line,
    package_name,
    string,
)

__all__ = ["MODEL_FILE", "SYSTEM_CLASS", "GeneratedModelica", "ModelicaGenerationError",
           "render_modelica", "write_modelica"]

MODEL_FILE = "model.mo"
SYSTEM_CLASS = "System"
TEMPLATES = Path(__file__).resolve().parent / "templates" / "modelica"
COMPONENTS = TEMPLATES / "components"
COMPONENT_PREFIX = "SpecAlive.Components."
USABLE = ("effective", "verification_only")  # preference order; never superseded or as-built
# System parameter name (core RUN_PARAMETERS, the names extraction maps to) -> experiment field.
EXPERIMENT = {"start_time": "StartTime", "stop_time": "StopTime",
              "output_interval": "Interval"}
DEFAULT_STOP_TIME = 1.0  # the Modelica default
DEFAULT_INTERVALS = 500  # omc's default number of output intervals
_DEFAULT_NOTE = "// ASSUMPTION (generator default): "


@dataclass(frozen=True)
class GeneratedModelica:
    text: str
    package: str
    model_name: str  # what omc checks and builds: <package>.System
    notes: list[str]  # every value or omission the generator decided, for the reports


@dataclass(frozen=True)
class Decl:
    comments: list[str]
    text: str


@dataclass(frozen=True)
class SystemView:
    name: str
    description: str
    parameters: list[Decl]
    instances: list[Decl]
    connections: list[Decl]
    experiment_comments: list[str]
    experiment: str


@dataclass(frozen=True)
class PackageView:
    name: str
    description: str
    interfaces: str
    components: list[str]
    controllers: list[str]


def _coord(value: float) -> str:
    """A diagram coordinate: a whole number without a decimal point, else as written."""
    return str(int(value)) if float(value).is_integer() else number(value)


def _point(p: tuple[float, float]) -> str:
    return f"{{{_coord(p[0])}, {_coord(p[1])}}}"


def _library_text(name: str) -> str:
    """A SpecAlive library class without its leading Purpose comment."""
    path = COMPONENTS / f"{name}.mo"
    if not path.is_file():
        raise ModelicaGenerationError(
            f"the catalogue names SpecAlive class {name!r}, but the component package has none")
    lines = path.read_text(encoding="utf-8").splitlines()
    while lines and lines[0].startswith("//"):
        lines.pop(0)
    return "\n".join(lines)


class _Builder:
    def __init__(self, model: SystemModel, catalogue: Catalogue) -> None:
        self.m, self.cat = model, catalogue
        self.notes: list[str] = []
        problems = catalogue.check_model(model)
        if problems:
            raise ModelicaGenerationError("the IR does not match the catalogue:\n  "
                                          + "\n  ".join(problems))
        self.ports = {port.id: (part, port) for part in model.parts for port in part.ports}
        self.value: dict[tuple[str, str], Parameter] = {}
        for status in reversed(USABLE):
            for p in model.parameters:
                if p.status == status:
                    self.value[(p.owner, p.name)] = p
        self.machines: dict[str, list] = defaultdict(list)
        kinds = {p.id: p.kind for p in model.parts}
        for sm in model.state_machines:
            if catalogue.entry(kinds[sm.owner]).modelica.source != "generated":
                raise ModelicaGenerationError(
                    f"state machine {sm.id!r} is owned by {sm.owner!r}, whose kind "
                    f"{kinds[sm.owner]!r} is not generated from a state machine")
            self.machines[sm.owner].append(sm)
        self.controllers = {sm.id: controller.render_controller(sm, model)
                            for sm in sorted(model.state_machines, key=lambda s: s.id)}
        self.layout = layout.layout(model, catalogue)

    def comments(self, element_id: str, own: list[str]) -> list[str]:
        return controller.assumption_comments(self.m, element_id, own)

    # --- the System model ---

    def parameters(self) -> list[Decl]:
        decls = []
        for p in sorted(self.m.parameters, key=lambda p: p.id):
            if p.status not in USABLE:
                continue
            label = f"{p.owner} {p.name}" + (", verification only"
                                              if p.status == "verification_only" else "")
            desc = string(f"{label} [IR {p.id}]")
            name = modelica_name(p.id)
            if isinstance(p.value, list):
                values = ", ".join(number(v) for v in p.value)
                binding = f"{{{values}}}" if p.value else "fill(0.0, 0)"
                text = (f'parameter Real {name}[{len(p.value)}](each unit = "{p.unit}") = '
                        f"{binding} {desc};")
            else:
                text = f'parameter Real {name}(unit = "{p.unit}") = {number(p.value)} {desc};'
            decls.append(Decl(self.comments(p.id, p.assumption_ids), text))
        return decls

    def _machine_of(self, part: Part):
        machines = self.machines.get(part.id, [])
        if len(machines) != 1:
            raise ModelicaGenerationError(
                f"part {part.id!r} of kind {part.kind!r} is generated from the state machine it "
                f"owns, but it owns {len(machines)}")
        return machines[0]

    def instance(self, part: Part) -> Decl:
        entry = self.cat.entry(part.kind)
        comments = self.comments(part.id, part.assumption_ids)
        if entry.modelica.source == "generated":
            rendered = self.controllers[self._machine_of(part).id]
            cls, mods = rendered.class_name, [f"{p} = {p}" for p in rendered.parameters]
        else:
            cls, mods = entry.modelica.class_, []
            for ir_name, mo_name in sorted(entry.modelica.parameters.items()):
                p = self.value.get((part.id, ir_name))
                if p is not None:
                    mods.append(f"{mo_name} = {modelica_name(p.id)}")
                elif ir_name in entry.defaults:
                    default = entry.defaults[ir_name]
                    mods.append(f"{mo_name} = {number(default.value)}")
                    comments.append(f"// ASSUMPTION (catalogue default {part.kind}.{ir_name}): "
                                    f"{one_line(default.assumption)}")
                    self.notes.append(f"part {part.id}: {part.kind}.{ir_name} has no IR value; "
                                      f"catalogue default {number(default.value)} "
                                      f"{default.unit} used")
        modifier = f"({', '.join(mods)})" if mods else ""
        x, y = self.layout.origins[part.id]
        placement = (f"annotation(Placement(transformation(origin = {_point((x, y))}, "
                     f"extent = {{{{-{layout.HALF}, -{layout.HALF}}}, "
                     f"{{{layout.HALF}, {layout.HALF}}}}})))")
        return Decl(comments, f"{cls} {modelica_name(part.id)}{modifier} "
                              f"{string(f'{part.name} [IR {part.id}]')} {placement};")

    def _endpoint(self, port_id: str) -> str:
        part, port = self.ports[port_id]
        entry = self.cat.entry(part.kind)
        if entry.modelica.source == "generated":
            connector = modelica_name(port.role)
        else:
            connector = entry.modelica.connectors.get(port.role)
            if connector is None:
                raise ModelicaGenerationError(
                    f"part {part.id!r}: port role {port.role!r} has no Modelica connector in "
                    f"the catalogue entry for {part.kind!r}")
        return f"{modelica_name(part.id)}.{connector}"

    def connections(self) -> list[Decl]:
        decls = []
        for c in sorted(self.m.connections, key=lambda c: c.id):
            points = ", ".join(_point(p) for p in self.layout.lines[c.id])
            colour = ", ".join(str(v) for v in self.layout.colours[c.id])
            decls.append(Decl(
                self.comments(c.id, c.assumption_ids),
                f"connect({self._endpoint(c.from_port)}, {self._endpoint(c.to_port)}) "
                f"{string(f'{c.medium_or_signal} [IR {c.id}]')} "
                f"annotation(Line(points = {{{points}}}, color = {{{colour}}}));"))
        return decls

    def experiment(self) -> tuple[list[str], str]:
        found: dict[str, float] = {}
        for name in EXPERIMENT:
            p = self.value.get((SYSTEM_OWNER, name))
            if p is not None:
                if isinstance(p.value, list):
                    raise ModelicaGenerationError(f"parameter {p.id!r} is a list, not a time")
                found[name] = float(p.value)
        comments = []
        if "stop_time" not in found:
            found["stop_time"] = DEFAULT_STOP_TIME
            comments.append(f"no stop time in the IR; StopTime = {number(DEFAULT_STOP_TIME)} s, "
                            "the Modelica default")
        if "output_interval" not in found:
            span = found["stop_time"] - found.get("start_time", 0.0)
            found["output_interval"] = span / DEFAULT_INTERVALS
            comments.append(f"no output interval in the IR; Interval = (StopTime - StartTime) / "
                            f"{DEFAULT_INTERVALS} = {number(found['output_interval'])} s, omc's "
                            f"default of {DEFAULT_INTERVALS} output intervals")
        self.notes.extend(comments)
        fields = ", ".join(f"{EXPERIMENT[name]} = {number(found[name])}"
                           for name in EXPERIMENT if name in found)
        (x1, y1), (x2, y2) = self.layout.extent
        diagram = (f"Diagram(coordinateSystem(extent = {{{_point((x1, y1))}, "
                   f"{_point((x2, y2))}}}))")
        return ([_DEFAULT_NOTE + c for c in comments],
                f"annotation({diagram}, experiment({fields}));")

    def _unasserted_notes(self) -> None:
        asserted = {cid for r in self.controllers.values() for cid in r.asserted}
        for ac in controller.invariants(self.m):
            if ac.id in asserted:
                continue
            reasons = "; ".join(r.not_asserted[ac.id] for r in self.controllers.values()
                                if ac.id in r.not_asserted) or "no controller in the model"
            self.notes.append(f"criterion {ac.id} holds for the whole run but is not asserted in "
                              f"the model ({reasons}); it is left to verification")

    # --- the package ---

    def _check_unique_names(self) -> None:
        names = [modelica_name(p.id) for p in self.m.parameters if p.status in USABLE]
        names += [modelica_name(p.id) for p in self.m.parts]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ModelicaGenerationError(f"names used twice in the System model: {dupes}")

    def build(self) -> tuple[PackageView, SystemView]:
        self._check_unique_names()
        parts = sorted(self.m.parts, key=lambda p: p.id)
        instances = [self.instance(p) for p in parts]
        classes = sorted({self.cat.entry(p.kind).modelica.class_ for p in parts
                          if self.cat.entry(p.kind).modelica.source == "specalive"})
        for cls in classes:
            if not cls.startswith(COMPONENT_PREFIX) or "." in cls[len(COMPONENT_PREFIX):]:
                raise ModelicaGenerationError(
                    f"SpecAlive class {cls!r} must be {COMPONENT_PREFIX}<Name>")
        components = [_library_text(cls[len(COMPONENT_PREFIX):]) for cls in classes]
        connections = self.connections()
        experiment_comments, experiment = self.experiment()
        self._unasserted_notes()
        system = SystemView(
            SYSTEM_CLASS,
            string(f"{self.m.name}: one instance per IR part and one connect per IR connection"),
            self.parameters(), instances, connections, experiment_comments, experiment)
        pkg = PackageView(package_name(self.m.name), string(self.m.description),
                          _library_text("Interfaces"), components,
                          [r.text.rstrip("\n") for r in self.controllers.values()])
        return pkg, system


def _environment() -> jinja2.Environment:
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)),
                              undefined=jinja2.StrictUndefined, autoescape=False,
                              trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)


def render_modelica(model: SystemModel, catalogue: Catalogue) -> GeneratedModelica:
    """The Modelica package for `model`; the same IR always gives the same bytes (R-MO-2)."""
    builder = _Builder(model, catalogue)
    pkg, system = builder.build()
    text = _environment().get_template("package.mo.j2").render(pkg=pkg, sys=system)
    return GeneratedModelica(text, pkg.name, f"{pkg.name}.{SYSTEM_CLASS}", builder.notes)


def write_modelica(model: SystemModel, catalogue: Catalogue,
                   out_dir: Path) -> tuple[Path, GeneratedModelica]:
    result = render_modelica(model, catalogue)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / MODEL_FILE
    target.write_text(result.text, encoding="utf-8", newline="\n")
    return target, result
