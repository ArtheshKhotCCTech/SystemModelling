# Purpose: correspondence.md (FR-08 req 4) — proof that the IR, the SysML and the Modelica
# agree, one row per IR element. Both columns come from parsing the generated files, never from
# trusting the generator (R-REP-2): a brace-and-comment scanner gives each SysML `doc /* ir: <id>`
# its qualified name; the Modelica column reads `[IR <id>]` strings, `// IR <id>:` comments,
# enumeration literals, asserts, and ports through the verify layer's variable map. Declared
# rules mark by-design absences N/A; an absent model file makes its column NOT RUN.
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from specalive.core.catalogue import Catalogue
from specalive.core.ir import SystemModel
from specalive.report.artefacts import NOT_RUN, Run, table, write_report
from specalive.verify import simulate

REPORT_FILE = "correspondence.md"
OK, MISSING, NA = "OK", "MISSING", "N/A"

# What each generator is meant to emit, so an absence by design is not reported as MISSING.
RULES = [
    "Requirements are SysML elements only; Modelica carries no requirements. A superseded "
    "requirement is reported, not modelled, in either layer.",
    "Acceptance criteria are checked against the simulation (verification.json); Modelica holds "
    "one as an assert only when its controller can state it, and SysML does not model them.",
    "Superseded and as-built-only parameters are reported, not modelled, in either layer.",
    "Verification-only parameters (press times, tolerances, run length) are Modelica "
    "parameters; SysML models effective values only.",
    "Regions have no Modelica element; the controller refuses parallel "
    "regions.",
]

_DOC_IR = re.compile(r"^\s*ir:\s*(\w+)")  # the generator opens every element doc with it
_SYSML_HEAD = re.compile(
    r"^\s*(?:(?:in|out|inout|private|public|abstract)\s+)*"
    r"(?:exhibit\s+)?(package|part def|part|port def|port|attribute def|attribute|state def|"
    r"state|transition|requirement def|requirement|connection|action def|action|calc def)\b"
    r"\s*(?::>>\s*)?(\w+)?(?:\s*:\s*~?(\w+))?")
_MO_CLASS = re.compile(r"^\s*(?:partial\s+)?(package|model|block|connector|record|function)\s+"
                       r"(\w+)\b(.*)$")
_MO_END = re.compile(r"^\s*end\s+(\w+)\s*;")
_MO_IR = re.compile(r"\[IR (\w+)\]")
_MO_DECL = re.compile(r"^\s*(?:parameter\s+|discrete\s+|constant\s+)?[A-Za-z_][\w.]*"
                      r"(?:\[[^\]]*\])?\s+([A-Za-z_]\w*)")
_MO_CONNECT = re.compile(r"^\s*(connect\([^)]*\))")
_MO_COMMENT = re.compile(r"//\s*IR (\w+):\s*(.*)$")
_MO_ENUM = re.compile(r"type\s+(\w+)\s*=\s*enumeration\((.*?)\)\s*;", re.DOTALL)
_MO_LITERAL = re.compile(r"(\w+)\s*(?:\"(?:[^\"\\]|\\.)*\")?\s*(?:,|$)")
_MO_ASSERT = re.compile(r"assert\(.*,\s*\"(\w+):")


# --- SysML --------------------------------------------------------------------------------

@dataclass
class SysmlScan:
    elements: dict[str, str] = field(default_factory=dict)  # IR id -> qualified name
    usages: dict[str, tuple[str, str]] = field(default_factory=dict)  # usage -> (qname, def)
    def_ports: dict[str, set[str]] = field(default_factory=dict)  # part def -> port names


def _strip_comments(text: str) -> list[tuple[str, list[str]]]:
    """Each line without its comments, with the IR ids of the comments that open on it."""
    out, in_comment = [], False
    for rest in text.splitlines():
        code, found = [], []
        while rest:
            if in_comment:
                end = rest.find("*/")
                in_comment, rest = end < 0, "" if end < 0 else rest[end + 2:]
                continue
            start, line_comment = rest.find("/*"), rest.find("//")
            if line_comment >= 0 and (start < 0 or line_comment < start):
                code.append(rest[:line_comment])
                break
            if start < 0:
                code.append(rest)
                break
            code.append(rest[:start])
            in_comment, rest = True, rest[start + 2:]
            found += _DOC_IR.findall(rest)
        out.append(("".join(code), found))
    return out


def scan_sysml(text: str) -> SysmlScan:
    scan = SysmlScan()
    stack: list[tuple[str | None, str | None, str | None]] = []  # (name, keyword, type)

    def qualified(name: str) -> str:
        return "::".join([n for n, _, _ in stack if n] + [name])

    for code, ids in _strip_comments(text):
        for ir_id in ids:
            names = [n for n, _, _ in stack if n]
            if names:
                scan.elements.setdefault(ir_id, "::".join(names))
        head = _SYSML_HEAD.match(code)
        keyword, name, type_ = (head[1], head[2], head[3]) if head else (None, None, None)
        if keyword == "port" and name:
            owner = stack[-1] if stack else None
            if owner and owner[1] == "part def":
                scan.def_ports.setdefault(owner[0], set()).add(name)
        if keyword == "part" and name and type_:
            scan.usages[name] = (qualified(name), type_)
        net = code.count("{") - code.count("}")
        if net > 0:
            stack.append((name, keyword, type_))
            stack.extend([(None, None, None)] * (net - 1))
        for _ in range(-net):
            if stack:
                stack.pop()
    return scan


# --- Modelica -----------------------------------------------------------------------------

@dataclass
class ModelicaScan:
    elements: dict[str, str] = field(default_factory=dict)  # IR id -> element
    controllers: dict[str, str] = field(default_factory=dict)  # machine id -> class
    states: dict[str, str] = field(default_factory=dict)  # "machine/state" -> element
    asserts: dict[str, str] = field(default_factory=dict)  # criterion id -> class
    edges: dict[str, set[str]] = field(default_factory=dict)  # class -> edge(x) connectors
    connectors: dict[str, dict[str, str]] = field(default_factory=dict)  # class -> id -> name


def scan_modelica(text: str) -> ModelicaScan:
    scan = ModelicaScan()
    stack: list[str] = []
    bodies: dict[str, list[str]] = {}
    for line in text.splitlines():
        cls = _MO_CLASS.match(line)
        if cls and not line.rstrip().endswith(";"):  # a short class `connector X = Y;` has no end
            stack.append(cls[2])
            bodies[cls[2]] = []
            tag = _MO_IR.search(cls[3])
            if tag:
                scan.controllers[tag[1]] = cls[2]
            continue
        end = _MO_END.match(line)
        if end and stack and stack[-1] == end[1]:
            stack.pop()
            continue
        if not stack:
            continue
        owner = stack[-1]
        bodies[owner].append(line)
        comment = _MO_COMMENT.search(line)
        if comment:
            scan.elements.setdefault(comment[1], f"{owner}: {comment[2].strip()}")
            continue
        found = _MO_ASSERT.search(line)
        if found:
            scan.asserts[found[1]] = f"{owner} assert"
        scan.edges.setdefault(owner, set()).update(re.findall(r"edge\((\w+)\)", line))
        tag = _MO_IR.search(line)
        if tag is None:
            continue
        connect = _MO_CONNECT.match(line)
        decl = _MO_DECL.match(line)
        if connect:
            scan.elements.setdefault(tag[1], connect[1])
        elif decl:
            # inside a controller the ids name its connectors, parameter copies and timers
            scan.connectors.setdefault(owner, {}).setdefault(tag[1], decl[1])
            if owner not in scan.controllers.values():
                scan.elements.setdefault(tag[1], f"{owner}.{decl[1]}")
    for machine, cls in scan.controllers.items():
        enum = _MO_ENUM.search("\n".join(bodies.get(cls, [])))
        if enum:
            for lit in _MO_LITERAL.finditer(enum[2].strip()):
                sid = lit[1][:-1] if lit[1].endswith("_") else lit[1]
                scan.states[f"{machine}/{sid}"] = f"{cls}.{enum[1]}.{lit[1]}"
    return scan


# --- the table ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    ir_id: str
    type: str
    sysml: str
    modelica: str
    status: str


@dataclass
class Correspondence:
    rows: list[Row]
    sysml_reason: str | None  # why the SysML column was not checked
    modelica_reason: str | None
    modelica_file: str | None
    notes: list[str]

    def counts(self) -> Counter:
        return Counter(r.status.split(" (")[0] for r in self.rows)


def _na(reason: str) -> str:
    return f"{NA} — {reason}"


def _status(sysml: str, modelica: str) -> str:
    missing = [layer for layer, v in (("SysML", sysml), ("Modelica", modelica)) if v == MISSING]
    if missing:
        return f"{MISSING} ({', '.join(missing)})"
    not_run = [layer for layer, v in (("SysML", sysml), ("Modelica", modelica)) if v == NOT_RUN]
    return f"{NOT_RUN} ({', '.join(not_run)})" if not_run else OK


class _Builder:
    def __init__(self, model: SystemModel, sysml: SysmlScan | None, mo: ModelicaScan | None,
                 vm: simulate.VariableMap | None) -> None:
        self.model, self.sysml, self.mo, self.vm = model, sysml, mo, vm
        self.rows: list[Row] = []

    def add(self, ir_id: str, type_: str, sysml: str | None, modelica: str | None) -> None:
        """None means 'look it up': NOT RUN without the file, MISSING when it is not there."""
        if sysml is None:
            sysml = NOT_RUN if self.sysml is None else self.sysml.elements.get(ir_id, MISSING)
        if modelica is None:
            modelica = NOT_RUN if self.mo is None else self.mo.elements.get(ir_id, MISSING)
        self.rows.append(Row(ir_id, type_, sysml, modelica, _status(sysml, modelica)))

    def sysml_port(self, part_id: str, port) -> str:
        if self.sysml is None:
            return NOT_RUN
        own = self.sysml.elements.get(port.id)
        if own is not None:
            return own
        usage = self.sysml.usages.get(part_id)
        if usage and port.role in self.sysml.def_ports.get(usage[1], set()):
            return f"{usage[0]}::{port.role}"
        return MISSING

    def modelica_port(self, port_id: str) -> str:
        if self.mo is None or self.vm is None:
            return NOT_RUN
        variable = self.vm.ports.get(port_id)
        return f"System.{variable}" if variable else MISSING

    def modelica_state(self, machine: str, state: str) -> str:
        if self.mo is None:
            return NOT_RUN
        return self.mo.states.get(f"{machine}/{state}", MISSING)

    def modelica_timer(self, sm, timer) -> str:
        if self.mo is None:
            return NOT_RUN
        cls = self.mo.controllers.get(sm.id)
        variable = self.mo.connectors.get(cls or "", {}).get(timer.id)
        return f"{cls}.{variable}" if variable else MISSING

    def modelica_event(self, sm, event) -> str:
        if self.mo is None:
            return NOT_RUN
        cls = self.mo.controllers.get(sm.id)
        connector = self.mo.connectors.get(cls or "", {}).get(event.port)
        if cls and connector and connector in self.mo.edges.get(cls, set()):
            return f"{cls}: edge({connector})"
        return MISSING

    def build(self) -> list[Row]:
        m = self.model
        for part in m.parts:
            self.add(part.id, "part", None, None)
            for port in part.ports:
                self.add(port.id, "port", self.sysml_port(part.id, port),
                         self.modelica_port(port.id))
        for c in m.connections:
            self.add(c.id, "connection", None, None)
        for p in m.parameters:
            if p.status in ("superseded", "as_built_only"):
                self.add(p.id, "parameter", _na(f"{p.status}, not modelled"),
                         _na(f"{p.status}, not modelled"))
            elif p.status == "verification_only":
                self.add(p.id, "parameter", _na("verification-only, not in SysML"), None)
            else:
                self.add(p.id, "parameter", None, None)
        for sm in m.state_machines:
            ctl = None if self.mo is None else self.mo.controllers.get(sm.id, MISSING)
            self.add(sm.id, "state machine", None, ctl)
            for s in sm.states:
                self.add(s.id, "state", None, self.modelica_state(sm.id, s.id))
            for t in sm.transitions:
                self.add(t.id, "transition", None, None)
            for e in sm.events:
                self.add(e.id, "event", None, self.modelica_event(sm, e))
            for t in sm.timers:
                self.add(t.id, "timer", None, self.modelica_timer(sm, t))
            for g in sm.regions:
                self.add(g.id, "region", None, _na("parallel regions are not generated"))
        for r in m.requirements:
            no_modelica = _na("requirements are not modelled in Modelica")
            if r.status == "superseded":
                by = f" by {r.superseded_by}" if r.superseded_by else ""
                self.add(r.id, "requirement", _na(f"superseded{by}, not modelled"), no_modelica)
            else:
                self.add(r.id, "requirement", None, no_modelica)
        for ac in m.acceptance_criteria:
            found = None if self.mo is None else self.mo.asserts.get(ac.id)
            modelica = found or (NOT_RUN if self.mo is None
                                 else _na("checked against the simulation"))
            self.add(ac.id, "acceptance criterion", _na("not modelled in SysML"), modelica)
        order = list(dict.fromkeys(r.type for r in self.rows))
        return sorted(self.rows, key=lambda r: (order.index(r.type), r.ir_id))


def correspond(run: Run, catalogue: Catalogue | None) -> Correspondence:
    model = run.model
    if model is None:
        return Correspondence([], run.ir.not_run, run.ir.not_run, None, [])
    sysml = scan_sysml(run.sysml.data) if run.sysml.ok else None
    mo = scan_modelica(run.modelica.data) if run.modelica.ok else None
    vm, notes = None, []
    if mo is not None:
        if catalogue is None:
            notes.append("ports not checked in Modelica: the catalogue did not load")
        else:
            name = run.repair_log.data.get("model") if run.repair_log.ok else None
            system = f"{model.name}.System" if not name else name
            vm = simulate.variable_map(model, catalogue, run.modelica.data, system)
    rows = _Builder(model, sysml, mo, vm).build()
    return Correspondence(rows, None if sysml else run.sysml.not_run,
                          None if mo else run.modelica.not_run,
                          run.modelica.name if mo else None, notes)


def render_correspondence(run: Run, catalogue: Catalogue | None) -> str:
    c = correspond(run, catalogue)
    name = run.model.name if run.model else "no IR"
    lines = [f"# IR ↔ SysML ↔ Modelica correspondence — {name}", "",
             "One row per IR element, found in each generated file by its IR id comment "
             "(SysML `doc /* ir: <id>`, Modelica `\"[IR <id>]\"` and `// IR <id>:`), not taken "
             "from the generator. `MISSING` means a layer lacks an element it should hold; "
             "`N/A` means the layer does not hold that element by design:", ""]
    lines += [f"- {rule}" for rule in RULES]
    if run.model is None:
        return "\n".join(lines + ["", run.ir.not_run]) + "\n"
    counts = c.counts()
    lines += ["", f"- SysML: {run.sysml.name}" if c.sysml_reason is None
              else f"- SysML: {c.sysml_reason}",
              f"- Modelica: {c.modelica_file}" if c.modelica_reason is None
              else f"- Modelica: {c.modelica_reason}"]
    lines += [f"- Note: {n}" for n in c.notes]
    lines += ["", f"{len(c.rows)} elements: {counts.get(OK, 0)} OK, {counts.get(MISSING, 0)} "
                  f"MISSING, {counts.get(NOT_RUN, 0)} {NOT_RUN}.", ""]
    lines += table(["IR id", "Type", "SysML element", "Modelica element", "Status"],
                   [[f"`{r.ir_id}`", r.type, r.sysml, r.modelica, r.status] for r in c.rows])
    return "\n".join(lines) + "\n"


def write_correspondence(run: Run, catalogue: Catalogue | None, out_dir: Path) -> Path:
    return write_report(out_dir, REPORT_FILE, render_correspondence(run, catalogue))
