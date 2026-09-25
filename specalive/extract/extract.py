# Purpose: the extract stage. Structure passes run per source in a fixed order (register first,
# then by role) over size-capped chunk batches; each LLM reply is a set of IR fragments, and a
# fragment whose verbatim quote is not in its cited chunk is discarded and counted, never repaired
# (R-EXT-4); a batch whose reply is cut off is halved and retried. A glossary of names already
# seen goes to later passes so names align. After entity resolution and precedence, a behaviour
# pass per controller returns a state machine over the now fixed ids, kept item by item only
# where guards, actions and ids check out.
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ValidationError

from specalive.core.catalogue import Catalogue, load_catalogue
from specalive.core.ids import make_id
from specalive.core.ir import (
    HISTORY,
    MAX_QUOTE,
    SYSTEM_OWNER,
    AcceptanceCriterion,
    Check,
    Event,
    ExpressionError,
    Part,
    SourceRole,
    State,
    StateMachine,
    SystemModel,
    Timer,
    TraceLink,
    Transition,
    expression_calls,
    expression_names,
    parse_action,
    parse_expression,
)
from specalive.extract.fragments import (
    AliasFragment,
    AssumptionHint,
    BehaviourReply,
    ConnectionFragment,
    CriterionFragment,
    Discarded,
    DocumentFragment,
    Draft,
    ExtractReport,
    Found,
    FragmentReply,
    ParameterFragment,
    PartFragment,
    RequirementFragment,
    name_key,
)
from specalive.extract.gaps import (
    apply_catalogue,
    apply_conventions,
    hint_assumptions,
    honesty_gate,
    missing_documents,
)
from specalive.extract.merge import ir_sources, resolve_connections, resolve_parts
from specalive.extract.precedence import (
    build_registry,
    rank_of,
    resolve_parameters,
    resolve_requirements,
    usable_tag,
)
from specalive.extract.text_input import text_bundle
from specalive.ingest.evidence import EvidenceBundle, EvidenceChunk, Source
from specalive.ingest.readers._common import CompletionClient
from specalive.llm.client import LLMIncomplete

IR_FILE = "ir.json"
REPORT_FILE = "extract_report.json"
BATCH_CHARS = 4_000  # larger batches made the model skim long tables
BEHAVIOUR_CHARS = 40_000
# A behaviour reply that lost items is asked once more with the problems listed (re-asked, never
# repaired); the attempt that keeps most is used.
BEHAVIOUR_ATTEMPTS = 2
# Registers first: they carry the tag / alias tables later passes lean on.
ROLE_ORDER: tuple[str, ...] = (
    "register", "requirement_spec", "design_note", "review_decision", "change_record",
    "datasheet", "verification_procedure", "reference_data", "legacy_model",
    "legacy_architecture", "correspondence", "informal_note", "other")

STRUCTURE_PROMPT = """\
You extract a structured system model from engineering evidence. You read one batch of evidence
chunks from one source document and return fragments. Never invent anything: every fragment must
be supported by a verbatim quote copied character for character from the chunk whose id you give
in chunk_id (at most 300 characters; quote the shortest span that supports the fragment). Quote
only chunk text, never the SOURCE or GLOSSARY lines. For a table row, quote the row as written,
including its "Header: value | Header: value" form. A fragment without such a quote is thrown
away. Go through every chunk: a table row that states a value yields a parameter.

Component kinds. A part's kind must be one of these catalogue kinds. If the evidence describes a
component none of them fits, use kind "unknown" and describe it. Never invent a kind.
<<KINDS>>

Return:
- parts: every physical component, instrument, operator control, controller or boundary the chunk
  describes. tag = its formal tag if the evidence gives one (as in an equipment schedule),
  otherwise the name used. aliases = every other name the same chunk gives that one component
  (split "a / b" into two names). One part per component: never list another component's tag as
  an alias, even when the chunk describes several similar components together. A chunk that
  decides or clarifies what a component or its command means (for example that a command is a
  controlled operation and not an emergency function) is a mention of that part: return it,
  with the clarification as an attribute. attributes = short descriptive facts (service, fail
  position, orientation), never numbers with units: those are parameters.
- connections: physical flow paths and signal paths between two parts, from the sending part to
  the receiving part, with the catalogue port roles when you can tell them. When one end is a
  controller, give signal_name: the name of that I/O signal as the evidence writes it.
- parameters: every numeric value with a unit that belongs to a part or to the system
  (setpoints, limits, areas, flows, delays, durations). owner_tag = the tag of the part the value
  belongs to: a level limit or setpoint of a tank belongs to that tank, a valve's flow to that
  valve, a delay or timer of the control sequence to the controller. Use the GLOSSARY tag when
  the chunk uses a short name or an alias. null only for a value of the run or test as a whole
  (simulation duration, logging interval, test tolerance). name = snake_case; use the catalogue
  parameter names above where they fit, and a GLOSSARY name when the quantity already has one.
  value = the number(s) exactly as written (a list as "20, 280"); unit exactly as written.
  cited_document = the identifier of the document the chunk names as the value's source (a
  "Source" column, "per <record>"), else null. stated_status = "effective" or "superseded" only
  when the evidence itself says so (status, effective or superseded columns or words), else null.
  configuration = "as_built" or "prototype" when the source says the value describes only that
  configuration, "verification" when it is only a test or verification setting (test schedules,
  tolerances, run lengths), else "nominal". provisional = true when the source says the value is
  subject to change, pending or to be confirmed. When a chunk records a change from an old value
  to a new one, return the new value; the old value is returned where its own source states it.
- requirements: each stated requirement ("shall"), with its identifier as tag.
- criteria: acceptance criteria and pass conditions, with their identifier as tag.
- documents: every document or record the chunk identifies by an identifier (change records,
  review minutes, specifications, data sheets, legacy models), with its role, whether the
  evidence says it is approved or released, its ISO date, revision and file name if given.
  Roles: <<ROLES>>.
- aliases: sets of names the evidence explicitly equates (a table with tag and alias columns, a
  naming cross-reference). Never names that merely look alike.
- assumptions: simplifications the source itself states (for example "treated as ideal").
- behaviour_chunk_ids: ids of chunks that describe controller states, modes, sequence steps,
  transitions, commands, command priority, timers or interlocks.
- system_name, system_description: only when the batch names or describes the system as a whole.
Return empty lists when the batch has nothing of a kind. The GLOSSARY lists names already
extracted from earlier sources: reuse them for the same component or quantity.
"""

BEHAVIOUR_PROMPT = """\
You turn a controller's described behaviour into a state machine over the ids listed in the
input. Never invent an id that is not listed, except the new state, event and timer ids you
declare; ids are lowercase snake_case and must not reuse a listed id. Every state and every
transition needs chunk_id and a verbatim quote (at most 300 characters) copied from that chunk.
Leave out anything that cannot be written with the listed ids; never approximate.
- states: one per distinct controller state, mode or sequence step. name = as the source names
  it; legacy_names = names an older or legacy source uses for the same state. outputs: for each
  listed output port, the value it holds in the state (true/false for a Boolean command).
  entry_actions is usually empty.
- events: one per command input that triggers transitions, on a listed input port.
- timers: one per delay; duration_parameter_id is one of the listed parameter ids.
- transitions: from_state, to_state (a state id, or "history" for the state saved by
  save_history), trigger_event (an event id) or null, and guard or null. A guard compares listed
  port ids, parameter ids and numbers with < <= > >= == != and combines them with and / or / not;
  it may use timer_expired(<timer id>) and in_state(<state id>). Use >= and <= for thresholds.
  actions: start_timer(<timer id>), save_history, clear_history. priority: 1 is evaluated first.
  Number the transitions of each from_state separately as 1, 2, 3 ... with no number repeated
  within that state: when a rule applies to many states ("from any state"), give it the same
  number in each, and number that state's other transitions around it. A command with higher
  precedence gets the lower number; guards on levels and timers come after the commands.
- checks: for each listed acceptance criterion that can be checked on a simulation result as a
  condition over listed port or parameter ids in a time window, give mode (at, always,
  eventually), condition, start_s and end_s (null for the run's bounds). Omit the others.
- initial_state: the state the controller starts in.
"""


class ExtractError(Exception):
    """The assembled IR failed its integrity check; `report` says what extraction found."""

    def __init__(self, message: str, report: ExtractReport) -> None:
        super().__init__(message)
        self.report = report


class EvidenceError(ValueError):
    """evidence.json is missing or not valid evidence."""


# --- chunks, order, batches, quotes --------------------------------------------------------

@dataclass(frozen=True)
class ChunkRef:
    chunk_id: str
    chunk: EvidenceChunk
    source: Source
    role: SourceRole


def index_chunks(bundle: EvidenceBundle) -> dict[str, ChunkRef]:
    """Every chunk under a stable id: its source id and its position within that source."""
    sources = {s.id: s for s in bundle.sources}
    counts: dict[str, int] = {}
    out: dict[str, ChunkRef] = {}
    for c in bundle.chunks:
        n = counts.get(c.source_id, 0)
        counts[c.source_id] = n + 1
        cid = f"{c.source_id}#{n}"
        src = sources[c.source_id]
        out[cid] = ChunkRef(cid, c, src, c.role or src.role)
    return out


def pass_order(bundle: EvidenceBundle) -> list[Source]:
    readable = [s for s in bundle.sources if s.status != "unread"]
    return sorted(readable, key=lambda s: (ROLE_ORDER.index(s.role)
                                           if s.role in ROLE_ORDER else len(ROLE_ORDER), s.id))


def batches(refs: list[ChunkRef], cap: int = BATCH_CHARS) -> list[list[ChunkRef]]:
    out: list[list[ChunkRef]] = []
    current: list[ChunkRef] = []
    size = 0
    for ref in refs:
        n = len(ref.chunk.text)
        if current and size + n > cap:
            out.append(current)
            current, size = [], 0
        current.append(ref)
        size += n
    if current:
        out.append(current)
    return out


def verify_quote(quote: str, text: str) -> str | None:
    """The chunk's own text for `quote` — exact, or equal with whitespace runs collapsed — or None
    when the quote is not there or is longer than a TraceLink allows."""
    words = quote.split()
    if not words or len(quote) > MAX_QUOTE:
        return None
    if quote in text:
        return quote
    match = re.search(r"\s+".join(map(re.escape, words)), text)
    if match is None or len(match.group(0)) > MAX_QUOTE:
        return None
    return match.group(0)


# --- structure passes ----------------------------------------------------------------------

def _catalogue_brief(catalogue: Catalogue) -> str:
    lines = []
    for kind in catalogue.kinds:
        entry = catalogue.entry(kind)
        if entry.dynamic_ports:
            ports = "ports come from its connections (its I/O signals)"
        else:
            ports = "ports: " + ", ".join(f"{role} ({s.direction} {s.domain})"
                                          for role, s in sorted(entry.ports.items()))
        params = ", ".join(entry.modelica.parameters) or "none"
        lines.append(f"- {kind}: {entry.description} {ports}; parameters: {params}.")
    return "\n".join(lines)


def structure_prompt(catalogue: Catalogue) -> str:
    return (STRUCTURE_PROMPT.replace("<<KINDS>>", _catalogue_brief(catalogue))
            .replace("<<ROLES>>", ", ".join(get_args(SourceRole))))


@dataclass
class _Glossary:
    parts: dict[str, tuple[str, str, list[str]]] = field(default_factory=dict)
    parameters: list[str] = field(default_factory=list)

    def add(self, parts: list[PartFragment], parameters: list[ParameterFragment]) -> None:
        for p in parts:
            key = name_key(p.tag)
            if not key:
                continue
            tag, kind, aliases = self.parts.setdefault(key, (p.tag, p.kind, []))
            for a in p.aliases:
                if a not in aliases and a != tag:
                    aliases.append(a)
        for q in parameters:
            entry = f"{q.owner_tag or SYSTEM_OWNER}.{q.name}"
            if entry not in self.parameters:
                self.parameters.append(entry)

    def text(self) -> str:
        parts = "; ".join(f"{tag} [{kind}]" + (f" aka {', '.join(aliases)}" if aliases else "")
                          for tag, kind, aliases in self.parts.values())
        return f"parts: {parts or '-'}\nparameters: {'; '.join(self.parameters) or '-'}"


def _structure_input(src: Source, ir_id: str, batch: list[ChunkRef], glossary: _Glossary) -> str:
    head = (f"SOURCE {ir_id} role={src.role} title={src.title or src.path} "
            f"revision={src.revision or '-'} date={src.date or '-'} "
            f"document={src.document or '-'} status={src.doc_status or '-'}")
    chunks = "\n\n".join(f"[{r.chunk_id}] role={r.role} at {r.chunk.locator}\n{r.chunk.text}"
                         for r in batch)
    return f"{head}\nGLOSSARY\n{glossary.text()}\nCHUNKS\n{chunks}\n"


@dataclass
class Passes:
    parts: list[Found[PartFragment]] = field(default_factory=list)
    connections: list[Found[ConnectionFragment]] = field(default_factory=list)
    parameters: list[Found[ParameterFragment]] = field(default_factory=list)
    requirements: list[Found[RequirementFragment]] = field(default_factory=list)
    criteria: list[Found[CriterionFragment]] = field(default_factory=list)
    documents: list[Found[DocumentFragment]] = field(default_factory=list)
    aliases: list[Found[AliasFragment]] = field(default_factory=list)
    hints: list[Found[AssumptionHint]] = field(default_factory=list)
    behaviour_refs: list[ChunkRef] = field(default_factory=list)
    discarded: list[Discarded] = field(default_factory=list)
    system_name: str | None = None
    system_description: str | None = None


def _locate(frag: BaseModel, kind: str, allowed: dict[str, ChunkRef], source_map: dict[str, str],
            discarded: list[Discarded]) -> Found | None:
    chunk_id, quote = frag.chunk_id, frag.quote  # type: ignore[attr-defined]
    ref = allowed.get(chunk_id)
    if ref is None:
        discarded.append(Discarded(chunk_id=chunk_id, kind=kind, quote=quote,
                                   reason=f"cites chunk {chunk_id}, which is not in this pass"))
        return None
    text = verify_quote(quote, ref.chunk.text)
    if text is None:
        discarded.append(Discarded(chunk_id=chunk_id, kind=kind, quote=quote,
                                   reason=f"quote not found in chunk {chunk_id}"))
        return None
    return Found(fragment=frag, chunk_id=chunk_id, source_id=source_map[ref.source.id],
                 locator=ref.chunk.locator, quote=text, role=ref.role, date=ref.source.date)


def run_structure_passes(bundle: EvidenceBundle, llm: CompletionClient, catalogue: Catalogue,
                         source_map: dict[str, str]) -> Passes:
    refs = index_chunks(bundle)
    by_source: dict[str, list[ChunkRef]] = {}
    for ref in refs.values():
        by_source.setdefault(ref.source.id, []).append(ref)
    prompt = structure_prompt(catalogue)
    glossary = _Glossary()
    out = Passes()
    for src in pass_order(bundle):
        pending = batches(by_source.get(src.id, []))
        while pending:
            batch = pending.pop(0)
            try:
                reply: FragmentReply = llm.complete(
                    prompt=prompt, input_text=_structure_input(src, source_map[src.id], batch,
                                                               glossary),
                    schema=FragmentReply)
            except LLMIncomplete:
                if len(batch) == 1:
                    ref = batch[0]
                    out.discarded.append(Discarded(
                        chunk_id=ref.chunk_id, kind="chunk", quote=ref.chunk.text[:MAX_QUOTE],
                        reason="the reply for this chunk alone was too long for the model's "
                               "output limit; nothing was extracted from it"))
                else:
                    half = len(batch) // 2
                    pending[:0] = [batch[:half], batch[half:]]
                continue
            allowed = {r.chunk_id: r for r in batch}
            groups = (("part", reply.parts, out.parts),
                      ("connection", reply.connections, out.connections),
                      ("parameter", reply.parameters, out.parameters),
                      ("requirement", reply.requirements, out.requirements),
                      ("criterion", reply.criteria, out.criteria),
                      ("document", reply.documents, out.documents),
                      ("alias", reply.aliases, out.aliases),
                      ("assumption", reply.assumptions, out.hints))
            first_part, first_param = len(out.parts), len(out.parameters)
            for kind, items, target in groups:
                for frag in items:
                    found = _locate(frag, kind, allowed, source_map, out.discarded)
                    if found is not None:
                        target.append(found)
            glossary.add([f.fragment for f in out.parts[first_part:]],
                         [f.fragment for f in out.parameters[first_param:]])
            seen = {r.chunk_id for r in out.behaviour_refs}
            for cid in reply.behaviour_chunk_ids:
                if cid in allowed and cid not in seen:
                    out.behaviour_refs.append(allowed[cid])
                    seen.add(cid)
            if out.system_name is None and reply.system_name:
                out.system_name = reply.system_name
                out.system_description = reply.system_description
    return out


# --- behaviour pass ------------------------------------------------------------------------

@dataclass(frozen=True)
class BehaviourContext:
    owner: Part
    operands: set[str]    # port and parameter ids a guard or check may use
    parameters: set[str]  # parameter ids a timer duration may name
    refs: dict[str, ChunkRef]
    source_map: dict[str, str]
    taken_ids: set[str]


@dataclass
class BehaviourResult:
    machine: StateMachine | None
    checks: dict[str, Check] = field(default_factory=dict)
    discarded: list[Discarded] = field(default_factory=list)


def _legal_new_id(kind: str, value: str, taken: set[str]) -> bool:
    try:
        return make_id(kind, value) == value and value not in taken
    except ValueError:
        return False


def _expression_problem(text: str, operands: set[str], timers: set[str],
                        states: set[str]) -> str | None:
    try:
        expr = parse_expression(text)
    except ExpressionError as exc:
        return str(exc)
    unknown = sorted(expression_names(expr) - operands)
    if unknown:
        return f"{', '.join(unknown)} is not a listed port or parameter id"
    for call in expression_calls(expr):
        if call.arg not in (timers if call.func == "timer_expired" else states):
            return f"{call.func}({call.arg}) names an unknown id"
    return None


def _action_problem(text: str, timers: set[str]) -> str | None:
    try:
        action = parse_action(text)
    except ExpressionError as exc:
        return str(exc)
    if action.verb == "start_timer" and action.args[0] not in timers:
        return f"start_timer({action.args[0]}) names an unknown timer"
    return None


def build_state_machine(reply: BehaviourReply, ctx: BehaviourContext) -> BehaviourResult:
    """A StateMachine from a behaviour reply, keeping only the items that check out."""
    result = BehaviourResult(machine=None)
    taken = set(ctx.taken_ids)
    traces: list[TraceLink] = []

    def drop(kind: str, what: str, reason: str, chunk_id: str = "", quote: str = "") -> None:
        result.discarded.append(Discarded(chunk_id=chunk_id, kind=kind, quote=quote or what,
                                          reason=reason))

    def traced(kind: str, spec) -> TraceLink | None:
        ref = ctx.refs.get(spec.chunk_id)
        text = verify_quote(spec.quote, ref.chunk.text) if ref is not None else None
        if text is None:
            drop(kind, spec.quote, f"quote not found in chunk {spec.chunk_id}", spec.chunk_id,
                 spec.quote)
            return None
        return TraceLink(source_id=ctx.source_map[ref.source.id], locator=ref.chunk.locator,
                         quote=text)

    inputs = {p.id for p in ctx.owner.ports if p.direction != "out"}
    outputs = {p.id for p in ctx.owner.ports if p.direction != "in"}

    events: list[Event] = []
    for e in reply.events:
        if not _legal_new_id("event", e.id, taken):
            drop("event", e.id, f"{e.id!r} is not a new snake_case id")
        elif e.port_id not in inputs:
            drop("event", e.id, f"port {e.port_id!r} is not an input of {ctx.owner.id}")
        else:
            taken.add(e.id)
            events.append(Event(id=e.id, port=e.port_id, edge=e.edge))
    timers: list[Timer] = []
    for t in reply.timers:
        if not _legal_new_id("timer", t.id, taken):
            drop("timer", t.id, f"{t.id!r} is not a new snake_case id")
        elif t.duration_parameter_id not in ctx.parameters:
            drop("timer", t.id, f"duration {t.duration_parameter_id!r} is not a listed parameter")
        else:
            taken.add(t.id)
            timers.append(Timer(id=t.id, duration=t.duration_parameter_id))
    timer_ids = {t.id for t in timers}

    states: list[State] = []
    for s in reply.states:
        if not _legal_new_id("state", s.id, taken):
            drop("state", s.id, f"{s.id!r} is not a new snake_case id", s.chunk_id, s.quote)
            continue
        trace = traced("state", s)
        if trace is None:
            continue
        values: dict[str, bool | float] = {}
        for o in s.outputs:
            if o.port_id in outputs:
                values[o.port_id] = o.value
            else:
                drop("output", f"{s.id}.{o.port_id}",
                     f"{o.port_id!r} is not an output port of {ctx.owner.id}")
        actions = []
        for a in s.entry_actions:
            problem = _action_problem(a, timer_ids)
            if problem:
                drop("action", a, problem, s.chunk_id)
            else:
                actions.append(a)
        taken.add(s.id)
        traces.append(trace)
        states.append(State(id=s.id, name=s.name, tags=list(s.legacy_names),
                            entry_actions=actions, outputs=values))
    state_ids = {s.id for s in states}
    if reply.initial_state not in state_ids:
        drop("state machine", ctx.owner.id,
             f"initial state {reply.initial_state!r} is not among the kept states")
        return result

    kept: list[tuple[Transition, TraceLink, str]] = []
    priorities: set[tuple[str, int]] = set()
    for t in reply.transitions:
        where = f"{t.from_state} -> {t.to_state}"

        def reject(reason: str, t=t, where=where) -> None:
            drop("transition", where, reason, t.chunk_id, t.quote)

        trace = traced("transition", t)
        if trace is None:
            continue
        if t.from_state not in state_ids:
            reject(f"from {t.from_state!r} is not a kept state")
            continue
        if t.to_state not in state_ids and t.to_state != HISTORY:
            reject(f"to {t.to_state!r} is not a kept state")
            continue
        if t.trigger_event is not None and t.trigger_event not in {e.id for e in events}:
            reject(f"trigger {t.trigger_event!r} is not a kept event")
            continue
        problem = (_expression_problem(t.guard, ctx.operands, timer_ids, state_ids)
                   if t.guard else None)
        problem = problem or next((p for p in (_action_problem(a, timer_ids) for a in t.actions)
                                   if p), None)
        if problem:
            reject(problem)
            continue
        tid = f"tr_{t.from_state}_{t.priority}"
        if t.priority < 1 or (t.from_state, t.priority) in priorities or tid in taken:
            reject(f"priority {t.priority} is not unique from {t.from_state!r}")
            continue
        priorities.add((t.from_state, t.priority))
        taken.add(tid)
        kept.append((Transition(id=tid, from_=t.from_state, to=t.to_state,
                                trigger=t.trigger_event, guard=t.guard, actions=list(t.actions),
                                priority=t.priority), trace, t.chunk_id))

    saves = any("save_history" in tr.actions for tr, _, _ in kept) or any(
        "save_history" in s.entry_actions for s in states)
    transitions = []
    for tr, trace, chunk_id in kept:
        if tr.to == HISTORY and not saves:
            drop("transition", f"{tr.from_} -> {HISTORY}",
                 "targets history but no kept action does save_history", chunk_id)
            continue
        transitions.append(tr)
        traces.append(trace)

    sm_id = make_id("sm", f"{ctx.owner.id} sequence")
    if sm_id in taken:
        sm_id = make_id("sm", f"sm {ctx.owner.id} sequence")
    unique = {(t.source_id, t.locator, t.quote): t for t in traces}
    result.machine = StateMachine(
        id=sm_id, owner=ctx.owner.id, initial=reply.initial_state, events=events, timers=timers,
        states=states, transitions=transitions, trace=[unique[k] for k in sorted(unique)])

    for c in reply.checks:
        problem = _expression_problem(c.condition, ctx.operands, timer_ids, state_ids)
        if problem is None and c.mode == "at" and c.start_s is None:
            problem = "an 'at' check needs start_s"
        if problem is None and c.start_s is not None and c.end_s is not None \
                and c.start_s > c.end_s:
            problem = "start_s is after end_s"
        if problem:
            drop("check", c.criterion_tag, problem, quote=c.condition)
            continue
        result.checks[c.criterion_tag] = Check(mode=c.mode, condition=c.condition,
                                               start_s=c.start_s, end_s=c.end_s)
    return result


def _behaviour_input(owner: Part, draft: Draft, refs: list[ChunkRef], criteria) -> str:
    connected: dict[str, str] = {}
    parts = {p.id: p for p in draft.parts}
    ports = {q.id: p for p in draft.parts for q in p.ports}
    for c in draft.connections:
        for mine, other in ((c.from_port, c.to_port), (c.to_port, c.from_port)):
            if mine in ports and ports[mine].id == owner.id and other in ports:
                o = ports[other]
                connected[mine] = f"{o.id} ({o.kind}; {', '.join(o.tags)})"
    lines = [f"CONTROLLER {owner.id} ({owner.name}; {', '.join(owner.tags)})", "PORTS"]
    for p in owner.ports:
        lines.append(f"- {p.id}: {p.direction} {p.domain}, connected to "
                     f"{connected.get(p.id, 'nothing')}")
    lines.append("OTHER PORT IDS")
    for part in sorted(parts.values(), key=lambda p: p.id):
        if part.id != owner.id:
            lines.extend(f"- {q.id}: {q.direction} {q.domain} of {part.id}" for q in part.ports)
    lines.append("PARAMETER IDS")
    lines.extend(f"- {p.id}: {p.owner}.{p.name} = {p.original.value} {p.original.unit}"
                 for p in sorted(draft.parameters, key=lambda p: p.id) if p.status == "effective")
    lines.append("ACCEPTANCE CRITERIA")
    lines.extend(f"- {ac.tags[0] if ac.tags else ac.id}: {ac.text}" for ac in criteria)
    lines.append("TAKEN IDS")
    lines.append(", ".join(sorted(draft.ids())))
    lines.append("CHUNKS")
    size = 0
    for r in refs:
        block = f"[{r.chunk_id}] role={r.role} at {r.chunk.locator}\n{r.chunk.text}"
        if size + len(block) > BEHAVIOUR_CHARS:
            break
        lines.append(block)
        size += len(block)
    return "\n".join(lines) + "\n"


def run_behaviour_passes(passes: Passes, draft: Draft, llm: CompletionClient,
                         refs: dict[str, ChunkRef], source_map: dict[str, str],
                         report: ExtractReport) -> dict[str, Check]:
    checks: dict[str, Check] = {}
    controllers = [p for p in draft.parts if p.kind == "sequence_controller"]
    behaviour = sorted(passes.behaviour_refs, key=lambda r: (rank_of(r.role), r.chunk_id))
    for owner in sorted(controllers, key=lambda p: p.id):
        if not behaviour:
            report.missing_information.append(
                f"{owner.id}: no source describes the controller's states or transitions")
            continue
        effective = {p.id for p in draft.parameters if p.status == "effective"}
        ctx = BehaviourContext(owner=owner, parameters=effective,
                               operands={q.id for p in draft.parts for q in p.ports} | effective,
                               refs=refs, source_map=source_map, taken_ids=draft.ids())
        base = _behaviour_input(owner, draft, behaviour, draft.acceptance_criteria)
        attempts: list[BehaviourResult] = []
        text = base
        for _ in range(BEHAVIOUR_ATTEMPTS):
            reply = llm.complete(prompt=BEHAVIOUR_PROMPT, input_text=text, schema=BehaviourReply)
            attempts.append(build_state_machine(reply, ctx))
            if not attempts[-1].discarded:
                break
            problems = "\n".join(f"- {d.kind} {d.quote[:120]!r}: {d.reason}"
                                 for d in attempts[-1].discarded)
            text = (f"{base}PROBLEMS\nYour previous answer lost these items; answer again with "
                    f"them corrected, changing nothing else:\n{problems}\n")
        result = min(attempts, key=lambda r: (r.machine is None, len(r.discarded)))
        for n, attempt in enumerate(attempts, start=1):
            report.discarded_fragments.extend(
                d.model_copy(update={"reason": f"{d.reason} (attempt {n})"})
                for d in attempt.discarded)
        if result.machine is not None:
            draft.state_machines.append(result.machine)
        checks.update(result.checks)
    return checks


# --- the stage -----------------------------------------------------------------------------

@dataclass
class ExtractResult:
    model: SystemModel
    report: ExtractReport


def _criteria(found: list[Found[CriterionFragment]]) -> list[AcceptanceCriterion]:
    groups: dict[str, list[Found[CriterionFragment]]] = {}
    for f in found:
        tag = usable_tag(f.fragment.tag)
        cid = make_id("ac", tag) if tag else make_id("ac", f"ac {f.source_id} {f.locator}")
        groups.setdefault(cid, []).append(f)
    out = []
    for cid in sorted(groups):
        items = sorted(groups[cid], key=lambda f: (rank_of(f.role), f.source_id, f.chunk_id))
        best = items[0].fragment
        unique = {(f.trace.source_id, f.trace.locator, f.trace.quote): f.trace for f in items}
        out.append(AcceptanceCriterion(
            id=cid, tags=[usable_tag(best.tag)] if usable_tag(best.tag) else [], text=best.text,
            reason="No executable check could be written over the extracted ids.",
            trace=[unique[k] for k in sorted(unique)]))
    return out


def run_extract(bundle: EvidenceBundle, llm: CompletionClient,
                catalogue: Catalogue | None = None) -> ExtractResult:
    """Evidence to a validated SystemModel and the report of what was discarded or is missing."""
    catalogue = catalogue or load_catalogue()
    report = ExtractReport()
    sources, source_map = ir_sources(bundle)
    passes = run_structure_passes(bundle, llm, catalogue, source_map)
    report.discarded_fragments.extend(passes.discarded)

    docs, cited = build_registry(sources, passes.documents)
    partset = resolve_parts(passes.parts, passes.aliases, catalogue)
    connections = resolve_connections(passes.connections, partset, catalogue)
    report.unresolved.extend(connections.problems)

    candidates = []
    for f in passes.parameters:
        tag = usable_tag(f.fragment.owner_tag)
        owner = SYSTEM_OWNER if tag is None else partset.lookup(tag)
        if owner is None:
            report.unresolved.append(f"parameter {f.fragment.name} ({f.chunk_id}): owner '{tag}' "
                                     "is not a known part")
            continue
        candidates.append((owner, f))
    params = resolve_parameters(candidates, docs)
    report.unresolved.extend(params.problems)

    name = passes.system_name or "system model"
    draft = Draft(
        name=make_id("system", name),
        description=passes.system_description
        or f"Extracted from {len(bundle.sources)} source(s).",
        sources=sources + cited, parts=partset.parts, connections=connections.connections,
        parameters=params.parameters, requirements=resolve_requirements(passes.requirements),
        acceptance_criteria=_criteria(passes.criteria),
        assumptions=partset.assumptions + hint_assumptions(passes.hints, partset.lookup),
        questions=partset.questions + params.questions, conflicts=params.conflicts)

    checks = run_behaviour_passes(passes, draft, llm, index_chunks(bundle), source_map, report)
    for ac in draft.acceptance_criteria:
        check = next((c for tag, c in checks.items()
                      if name_key(tag) in {name_key(t) for t in ac.tags}), None)
        if check is not None:
            ac.check, ac.reason = check, None

    apply_conventions(draft)
    report.missing_information.extend(apply_catalogue(draft, catalogue))
    report.missing_information.extend(missing_documents(draft.sources,
                                                        params.unresolved_citations))
    report.rejected_untraced = honesty_gate(draft)
    try:
        model = draft.to_model()
    except ValueError as exc:
        raise ExtractError(str(exc), report) from None
    return ExtractResult(model=model, report=report)


def extract_text(text: str, llm: CompletionClient, name: str = "text",
                 catalogue: Catalogue | None = None) -> ExtractResult:
    """Plain text runs through the same run_extract as a bundle (R-EXT-8)."""
    return run_extract(text_bundle(text, name), llm, catalogue)


def load_evidence(path: Path) -> EvidenceBundle:
    try:
        return EvidenceBundle.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvidenceError(f"cannot read {path}: {exc.strerror or exc}") from None
    except ValidationError as exc:
        raise EvidenceError(f"{path} is not valid evidence: {exc.error_count()} problem(s), "
                            f"first: {exc.errors()[0]['msg']}") from None


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.write("\n")


def write_ir(result: ExtractResult, out_dir: Path) -> Path:
    """ir.json and extract_report.json, with no clock or random value in either."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / IR_FILE
    _write(target, result.model.model_dump_json(indent=2, by_alias=True))
    write_report(result.report, out_dir)
    return target


def write_report(report: ExtractReport, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / REPORT_FILE
    _write(target, report.model_dump_json(indent=2))
    return target
