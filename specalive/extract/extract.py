# Purpose: the extract stage. Structure passes run per source in a fixed order (register first,
# then by role) over size-capped chunk batches; each LLM reply is a set of IR fragments, and a
# fragment whose verbatim quote is not in its cited chunk is discarded and counted, never repaired
# (R-EXT-4); a batch whose reply is cut off is halved and retried. A glossary of names already
# seen goes to later passes so names align. After entity resolution and precedence, a behaviour
# pass per controller returns a state machine over the now fixed ids, kept item by item only
# where guards, actions and ids check out. An optional progress callback is told which source (n
# of m) and which controller is being worked on, so a long LLM stage is never silent (FR-09).
# Phase 9: a guard that reads another part's output wired to exactly one controller input reads
# that input instead, since a controller can read only its own ports. A check whose time window
# the criterion does not state is discarded, and a priority clash left after every attempt is a
# Question rather than a silent choice between the two transitions. A traced command precedence
# numbers each state's transitions (commands in that order, then guards), and a controller output
# or event the reply puts on another part's unwired port, where a kept quote names that part,
# becomes a new controller port with a traced connection. A rule "from any state" (from_state
# "*") is expanded by code to every kept state but its exceptions and its own target. A table
# row that names its quantity in a label column gives the parameter that name, not the LLM's
# choice, so two rows are never merged as one quantity and later passes see stable names.
# Registers are read first and the other sources against the glossary they built, each wave in
# parallel (fresh-run finding: 21 calls in a row took five minutes).
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ValidationError

from specalive.core.catalogue import Catalogue, load_catalogue
from specalive.core.ids import make_id
from specalive.core.units import to_si
from specalive.core.ir import (
    HISTORY,
    MAX_QUOTE,
    SYSTEM_OWNER,
    AcceptanceCriterion,
    Check,
    Connection,
    Event,
    ExpressionError,
    Part,
    Port,
    Question,
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
    apply_run_names,
    hint_assumptions,
    honesty_gate,
    missing_documents,
    unconnected_inputs,
    unique_ids,
)
from specalive.extract.merge import (
    _FORMAL,
    _names_any,
    ir_sources,
    measurement_links,
    single_drivers,
    resolve_connections,
    resolve_parts,
)
from specalive.extract.precedence import (
    adopt_system_values,
    build_registry,
    rank_of,
    resolve_parameters,
    resolve_requirements,
    usable_tag,
)
from specalive.extract.schedule import press_schedules
from specalive.extract.text_input import text_bundle
from specalive.ingest.evidence import EvidenceBundle, EvidenceChunk, Source
from specalive.ingest.readers._common import CompletionClient
from specalive.llm.client import LLMIncomplete

IR_FILE = "ir.json"
REPORT_FILE = "extract_report.json"
BATCH_CHARS = 4_000  # larger batches made the model skim long tables
BEHAVIOUR_CHARS = 40_000
# A behaviour reply that lost items is asked again with the problems listed (re-asked, never
# repaired); the attempt that keeps most is used. Three: on L1 a priority clash survived two.
BEHAVIOUR_ATTEMPTS = 3
ANY_STATE = "*"  # a transition's from_state for a rule that leaves every state
EVENT_DOMAINS = ("signal_bool", "event")  # port domains an edge-triggered event can sit on
# Register columns that name the quantity a row's value belongs to, most specific first; only
# rows that also have a value column are named this way (an equipment row is not).
# Sources read in the first wave: their tag, alias and parameter names are the glossary every
# other source is read against in the second.
GLOSSARY_ROLES = frozenset({"register"})
# A register's rows that state requirements are statements like any specification's: they are
# read in the second wave, against the glossary, so they reuse its names.
STATEMENT_ROLES = frozenset({"requirement_spec"})
# Structure passes running at once for the CLI; tests pass 1 so scripted fakes answer in order.
STRUCTURE_WORKERS = 4
LABEL_HEADERS = ("parameter", "keyparameter", "quantity", "description", "name", "input")

Progress = Callable[[str], None]


def _quiet(message: str) -> None:
    pass
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
  For a rule that applies from every state ("from any state", "from any non-X state"), give one
  transition with from_state "*" and except_states listing the states it does not apply from
  (null otherwise); it is added to every other state except its own to_state.
  A state's output or an event may name another part's listed port when the controller drives or
  reads that part and nothing connects it yet; quote the text naming the part.
  Number the transitions of each from_state separately as 1, 2, 3 ... with no number repeated
  within that state: when a rule applies to many states ("from any state"), give it the same
  number in each, and number that state's other transitions around it. A command with higher
  precedence gets the lower number; guards on levels and timers come after the commands.
- command_precedence: when a source states which command wins when several arrive together, the
  event ids in that order, the winning one first, with chunk_id and the quote stating it; null if
  no source states it. The transition numbers of commands then follow this order.
- checks: for each listed acceptance criterion that can be checked on a simulation result as a
  condition over listed port or parameter ids in a time window, give mode (at, always,
  eventually), condition, start_s and end_s (null for the run's bounds). An exception the
  criterion states ("permitted only in X") belongs in the condition, e.g. or in_state(x).
  start_s and end_s are only times in seconds that the criterion itself states. start_basis and end_basis say where
  each bound comes from: stated_time (a time in seconds the criterion states, given as the
  bound, also when it names what happens then: the START at 280 s), event (the criterion gives
  no time for it, only an event: before X begins, after Y completes) or
  run_bound (the bound is null because the criterion holds to the start or end of the run). If
  either basis is event, omit the criterion: never stand in the run's start or end for it.
  always with both bounds null is only for a criterion that holds for the whole run (never, at
  all times). Omit the others.
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


def _row_label(chunk: EvidenceChunk) -> str | None:
    """The quantity a register row names in its label column, when it also has a value column."""
    if chunk.kind != "table_row":
        return None
    keys = {name_key(k): v for k, v in chunk.fields.items()}
    if not any(k.startswith("value") or k == "inputvalue" for k in keys):
        return None
    label = next((keys[h] for h in LABEL_HEADERS if h in keys and name_key(keys[h])), None)
    return label.strip() if label else None


def _catalogue_names(catalogue: Catalogue) -> set[str]:
    names: set[str] = set()
    for kind in catalogue.kinds:
        e = catalogue.entry(kind)
        names.update(e.required, e.defaults, e.modelica.parameters)
    return names


def _named_by_row(found: Found[ParameterFragment], ref: ChunkRef,
                  catalogue_names: set[str]) -> Found[ParameterFragment]:
    """The fragment named after its row's label, unless the LLM chose a catalogue name."""
    label = _row_label(ref.chunk)
    if label is None or found.fragment.name in catalogue_names:
        return found
    try:
        name = make_id("param", label)
    except ValueError:
        return found
    return dataclasses.replace(found, fragment=found.fragment.model_copy(update={"name": name}))


def _structure_input(src: Source, ir_id: str, batch: list[ChunkRef], glossary: str) -> str:
    head = (f"SOURCE {ir_id} role={src.role} title={src.title or src.path} "
            f"revision={src.revision or '-'} date={src.date or '-'} "
            f"document={src.document or '-'} status={src.doc_status or '-'}")
    chunks = "\n\n".join(f"[{r.chunk_id}] role={r.role} at {r.chunk.locator}\n{r.chunk.text}"
                         for r in batch)
    return f"{head}\nGLOSSARY\n{glossary}\nCHUNKS\n{chunks}\n"


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


def _ask(llm: CompletionClient, prompt: str, src: Source, ir_id: str, batch: list[ChunkRef],
         glossary: str) -> list[tuple[list[ChunkRef], FragmentReply | None]]:
    """Replies for one batch, halving it while the reply is cut off; None for a single chunk whose
    reply is still too long."""
    pending, out = [batch], []
    while pending:
        part = pending.pop(0)
        try:
            out.append((part, llm.complete(
                prompt=prompt, input_text=_structure_input(src, ir_id, part, glossary),
                schema=FragmentReply)))
        except LLMIncomplete:
            if len(part) == 1:
                out.append((part, None))
            else:
                half = len(part) // 2
                pending[:0] = [part[:half], part[half:]]
    return out


def run_structure_passes(bundle: EvidenceBundle, llm: CompletionClient, catalogue: Catalogue,
                         source_map: dict[str, str], progress: Progress = _quiet,
                         workers: int = 1) -> Passes:
    """Two waves, `workers` calls at a time: the registers' batches (tables that state their own
    tags), whose names become the glossary; then every other source's batches against that fixed
    glossary. Replies are taken in the fixed source and batch order, so neither the result nor
    the cache keys depend on which call finishes first."""
    refs = index_chunks(bundle)
    by_source: dict[str, list[ChunkRef]] = {}
    for ref in refs.values():
        by_source.setdefault(ref.source.id, []).append(ref)
    prompt = structure_prompt(catalogue)
    catalogue_names = _catalogue_names(catalogue)
    glossary = _Glossary()
    out = Passes()
    order = pass_order(bundle)
    number = {src.id: n for n, src in enumerate(order, start=1)}

    def wave(groups: list[tuple[Source, list[ChunkRef]]]) -> None:
        tasks = []
        for src, refs in groups:
            pending = batches(refs)
            progress(f"source {number[src.id]} of {len(order)}: {src.path or src.id} "
                     f"({len(pending)} batch(es))")
            tasks.extend((src, batch) for batch in pending)
        text = glossary.text()

        def ask(task: tuple[Source, list[ChunkRef]]):
            return _ask(llm, prompt, task[0], source_map[task[0].id], task[1], text)

        if workers > 1 and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                replies = list(pool.map(ask, tasks))
        else:
            replies = [ask(t) for t in tasks]
        for results in replies:
            absorb(results)

    def absorb(results: list[tuple[list[ChunkRef], FragmentReply | None]]) -> None:
        for batch, reply in results:
            if reply is None:
                ref = batch[0]
                out.discarded.append(Discarded(
                    chunk_id=ref.chunk_id, kind="chunk", quote=ref.chunk.text[:MAX_QUOTE],
                    reason="the reply for this chunk alone was too long for the model's "
                           "output limit; nothing was extracted from it"))
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
            out.parameters[first_param:] = [
                _named_by_row(f, allowed[f.chunk_id], catalogue_names)
                for f in out.parameters[first_param:]]
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

    def first(ref: ChunkRef) -> bool:
        return ref.source.role in GLOSSARY_ROLES and ref.role not in STATEMENT_ROLES

    early = [(src, [r for r in by_source.get(src.id, []) if first(r)]) for src in order]
    early = [(src, refs) for src, refs in early if refs]
    late = [(src, [r for r in by_source.get(src.id, []) if not first(r)]) for src in order]
    read_early = {src.id for src, _ in early}
    late = [(src, refs) for src, refs in late if refs or src.id not in read_early]
    wave(early)
    wave(late)
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
    via: dict[str, str] = field(default_factory=dict)  # other part's output -> owner input
    criteria: dict[str, str] = field(default_factory=dict)  # name_key(criterion tag) -> its text
    others: dict[str, tuple[Part, Port]] = field(default_factory=dict)  # other parts' ports by id
    connected: set[str] = field(default_factory=set)  # port ids some connection already joins
    parameter_units: dict[str, str] = field(default_factory=dict)  # parameter id -> its unit


def controller_inputs_by_source(owner: Part, connections: list[Connection]) -> dict[str, str]:
    """Each other part's output port wired to exactly one input of `owner` -> that input."""
    inputs = {p.id for p in owner.ports if p.direction == "in"}
    targets: dict[str, set[str]] = {}
    for c in connections:
        if c.to_port in inputs:
            targets.setdefault(c.from_port, set()).add(c.to_port)
    return {src: next(iter(t)) for src, t in sorted(targets.items()) if len(t) == 1}


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def through_wiring(expression: str, via: dict[str, str]) -> str:
    """`expression` with each whole id in `via` replaced by the controller input it is wired to."""
    return _IDENTIFIER.sub(lambda m: via.get(m.group(0), m.group(0)), expression)


@dataclass
class BehaviourResult:
    machine: StateMachine | None
    checks: dict[str, Check] = field(default_factory=dict)
    discarded: list[Discarded] = field(default_factory=list)
    # (from_state, priority, kept transition, dropped transition), each as "trigger -> to"
    collisions: list[tuple[str, int, str, str]] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)  # new controller ports, for the owner
    # checks rightly left out (a window the criterion does not time): reported, never re-asked,
    # since asking again only invites a made-up bound
    omitted: list[Discarded] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)  # joining them to other parts


_NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?")


def _unstated_bound(bounds: tuple[float | None, ...], text: str) -> float | None:
    """The first time bound that no number in the criterion `text` states (T1's 1 is no time)."""
    stated = {float(n) for n in _NUMBER.findall(text)}
    return next((b for b in bounds if b is not None and float(b) not in stated), None)


def _is_time(unit: str | None) -> bool:
    """Whether a timer may run for a value in `unit`; an unknown unit is not judged here."""
    if unit is None:
        return True
    try:
        return to_si(1.0, unit)[1] == "s"
    except ValueError:
        return False


def _describe(trigger: str | None, guard: str | None, to: str) -> str:
    return f"{trigger or guard or 'always'} -> {to}"


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


def _foreign_links(reply: BehaviourReply, ctx: BehaviourContext, taken: set[str],
                   result: BehaviourResult) -> dict[str, str]:
    """Other parts' unwired ports the reply drives (a state output on an input) or reads (an
    event on an output), where a verified quote of the reply names the part: each gets a new
    controller port and a connection traced to those quotes. Returns other port -> new port."""
    quotes = []
    for spec in [*reply.states, *reply.transitions]:
        ref = ctx.refs.get(spec.chunk_id)
        text = verify_quote(spec.quote, ref.chunk.text) if ref is not None else None
        if text is not None:
            quotes.append(TraceLink(source_id=ctx.source_map[ref.source.id],
                                    locator=ref.chunk.locator, quote=text))
    own = {p.id for p in ctx.owner.ports}
    wanted = {o.port_id: "in" for st in reply.states for o in st.outputs if o.port_id not in own}
    wanted.update({e.port_id: "out" for e in reply.events if e.port_id not in own})
    mapping: dict[str, str] = {}
    for pid in sorted(wanted):
        if pid not in ctx.others or pid in ctx.connected:
            continue
        part, port = ctx.others[pid]
        if port.direction != wanted[pid] or port.domain == "fluid":
            continue
        named = list({(t.source_id, t.locator, t.quote): t for t in quotes
                      if _names_any(t.quote, part.tags)}.values())
        if not named:
            continue
        alias = next((t for t in part.tags if not _FORMAL.match(t) and name_key(t)), part.id)
        role = make_id("port", alias)
        if f"{ctx.owner.id}_{role}" in taken:
            role = make_id("port", f"{alias} {port.role}")
        mine = Port(id=f"{ctx.owner.id}_{role}", role=role,
                    direction="out" if port.direction == "in" else "in", domain=port.domain,
                    unit=port.unit, trace=named)
        ends = (mine.id, pid) if mine.direction == "out" else (pid, mine.id)
        cid = make_id("conn", f"{ends[0]} to {ends[1]}")
        if mine.id in taken or cid in taken:
            continue
        taken.update((mine.id, cid))
        result.ports.append(mine)
        result.connections.append(Connection(
            id=cid, from_port=ends[0], to_port=ends[1], trace=named,
            medium_or_signal=port.role.removesuffix("_in").removesuffix("_out")))
        mapping[pid] = mine.id
    result.ports.sort(key=lambda q: q.id)
    return mapping


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
            # never moved by code (R-EXT-4); the re-ask says where the quote really is
            homes = [cid for cid, r in sorted(ctx.refs.items())
                     if verify_quote(spec.quote, r.chunk.text) is not None]
            where = f"; it is in chunk {homes[0]}" if len(homes) == 1 else ""
            drop(kind, spec.quote, f"quote not found in chunk {spec.chunk_id}{where}",
                 spec.chunk_id, spec.quote)
            return None
        return TraceLink(source_id=ctx.source_map[ref.source.id], locator=ref.chunk.locator,
                         quote=text)

    linked = _foreign_links(reply, ctx, taken, result)
    ports = [*ctx.owner.ports, *result.ports]
    inputs = {p.id for p in ports if p.direction != "out"}
    outputs = {p.id for p in ports if p.direction != "in"}
    domains = {p.id: p.domain for p in ports}

    events: list[Event] = []
    for e in reply.events:
        port_id = linked.get(e.port_id, e.port_id)
        if not _legal_new_id("event", e.id, taken):
            drop("event", e.id, f"{e.id!r} is not a new snake_case id")
        elif port_id not in inputs:
            drop("event", e.id, f"port {e.port_id!r} is not an input of {ctx.owner.id}")
        elif domains[port_id] not in EVENT_DOMAINS:
            drop("event", e.id, f"port {port_id!r} is {domains[port_id]}; an event needs a "
                 "Boolean command input, and a threshold on a value is a guard")
        else:
            taken.add(e.id)
            events.append(Event(id=e.id, port=port_id, edge=e.edge))
    timers: list[Timer] = []
    for t in reply.timers:
        if not _legal_new_id("timer", t.id, taken):
            drop("timer", t.id, f"{t.id!r} is not a new snake_case id")
        elif t.duration_parameter_id not in ctx.parameters:
            drop("timer", t.id, f"duration {t.duration_parameter_id!r} is not a listed parameter")
        elif not _is_time(ctx.parameter_units.get(t.duration_parameter_id)):
            drop("timer", t.id, f"duration {t.duration_parameter_id!r} is in "
                 f"{ctx.parameter_units[t.duration_parameter_id]!r}, not a time")
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
            if linked.get(o.port_id, o.port_id) in outputs:
                values[linked.get(o.port_id, o.port_id)] = o.value
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

    rank: dict[str, int] = {}  # event id -> its place in the stated command precedence
    cp = reply.command_precedence
    cp_trace = traced("command precedence", cp) if cp is not None else None
    if cp_trace is not None:
        event_ids = {e.id for e in events}
        for eid in cp.events:
            if eid not in event_ids:
                drop("command precedence", eid, f"{eid!r} is not a kept event", cp.chunk_id)
            elif eid not in rank:
                rank[eid] = len(rank)
        if rank:
            traces.append(cp_trace)

    def order(t) -> tuple[int, ...]:
        """Stated precedence first, then the reply's numbers: commands, then guards."""
        if not rank:
            return (t.priority,)
        if t.trigger_event in rank:
            return (0, rank[t.trigger_event])
        return (1 if t.trigger_event else 2, t.priority)

    expanded = []
    for t in reply.transitions:
        if t.from_state != ANY_STATE:
            expanded.append(t)
            continue
        excluded = set(t.except_states or [])
        for x in sorted(excluded - state_ids):
            drop("transition", x, f"except state {x!r} is not a kept state", t.chunk_id)
        expanded.extend(t.model_copy(update={"from_state": s.id, "except_states": None})
                        for s in states if s.id not in excluded and s.id != t.to_state)

    kept: list[tuple[Transition, TraceLink, str, tuple[int, ...]]] = []
    priorities: dict[tuple[str, tuple[int, ...]], str] = {}
    for t in expanded:
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
        actions = list(t.actions)
        if t.to_state == HISTORY:
            # clearing on the way back would resume nothing, and is redundant: the next
            # save_history replaces the saved state. The action goes; the resume stays.
            clears = [a for a in actions if _action_problem(a, set()) is None
                      and parse_action(a).verb == "clear_history"]
            for a in clears:
                drop("action", a, f"{where}: clear_history on a return to history would resume "
                     "nothing; the transition is kept without it", t.chunk_id, t.quote)
            actions = [a for a in actions if a not in clears]
        guard = through_wiring(t.guard, ctx.via) if t.guard else t.guard
        problem = (_expression_problem(guard, ctx.operands, timer_ids, state_ids)
                   if guard else None)
        problem = problem or next((p for p in (_action_problem(a, timer_ids) for a in actions)
                                   if p), None)
        if problem:
            reject(problem)
            continue
        tid = f"tr_{t.from_state}_{t.priority}"
        other = priorities.get((t.from_state, order(t)))
        if other is not None:
            mine = _describe(t.trigger_event, guard, t.to_state)
            result.collisions.append((t.from_state, t.priority, other, mine))
            reject(f"priority {t.priority} from {t.from_state!r} is also given to {other}; each "
                   "transition of a state needs its own number, the lower one for the command "
                   "with higher precedence in the sources")
            continue
        if t.priority < 1 or (not rank and tid in taken):
            reject(f"priority {t.priority} is not unique from {t.from_state!r}")
            continue
        priorities[(t.from_state, order(t))] = _describe(t.trigger_event, guard, t.to_state)
        if not rank:
            taken.add(tid)
        kept.append((Transition(id=tid, from_=t.from_state, to=t.to_state,
                                trigger=t.trigger_event, guard=guard, actions=actions,
                                priority=t.priority), trace, t.chunk_id, order(t)))
    if rank:  # renumber 1..n per state in precedence order
        for state in {tr.from_ for tr, _, _, _ in kept}:
            mine = sorted((k for k in kept if k[0].from_ == state), key=lambda k: k[3])
            for n, (tr, _, _, _) in enumerate(mine, start=1):
                tr.priority, tr.id = n, f"tr_{state}_{n}"
        clash = [k for k in kept if k[0].id in taken]
        for tr, _, chunk_id, _ in clash:
            drop("transition", f"{tr.from_} -> {tr.to}", f"id {tr.id} is already taken", chunk_id)
        kept = [k for k in kept if k not in clash]
        taken.update(tr.id for tr, _, _, _ in kept)

    saves = any("save_history" in tr.actions for tr, _, _, _ in kept) or any(
        "save_history" in s.entry_actions for s in states)
    transitions = []
    for tr, trace, chunk_id, _ in kept:
        if tr.to == HISTORY and not saves:
            drop("transition", f"{tr.from_} -> {HISTORY}",
                 "targets history but no kept action does save_history", chunk_id)
            continue
        transitions.append(tr)
        traces.append(trace)

    # a timer a guard waits on but no kept action starts never expires: say so, so the reply is
    # asked again (the transition stays; nothing is added by code)
    started = {parse_action(a).args[0] for a in
               [a for tr in transitions for a in tr.actions]
               + [a for st in states for a in st.entry_actions]
               if parse_action(a).verb == "start_timer"}
    for tr in transitions:
        if not tr.guard:
            continue
        for call in expression_calls(parse_expression(tr.guard)):
            if call.func == "timer_expired" and call.arg not in started:
                drop("timer", call.arg, f"{call.arg} is tested leaving {tr.from_!r} but never "
                     "started: no transition into that state and no entry action starts it")
    sm_id = make_id("sm", f"{ctx.owner.id} sequence")
    if sm_id in taken:
        sm_id = make_id("sm", f"sm {ctx.owner.id} sequence")
    unique = {(t.source_id, t.locator, t.quote): t for t in traces}
    result.machine = StateMachine(
        id=sm_id, owner=ctx.owner.id, initial=reply.initial_state, events=events, timers=timers,
        states=states, transitions=transitions, trace=[unique[k] for k in sorted(unique)])

    for c in reply.checks:
        problem = _expression_problem(c.condition, ctx.operands, timer_ids, state_ids)
        if problem is None and c.mode == "at" and c.start_s is None and c.start_basis != "event":
            problem = "an 'at' check needs start_s"
        if problem is None and c.start_s is not None and c.end_s is not None \
                and c.start_s > c.end_s:
            problem = "start_s is after end_s"
        omission = None
        # an 'at' check is a single instant: its end bound is not used, so not judged
        bases = (c.start_basis,) if c.mode == "at" else (c.start_basis, c.end_basis)
        if problem is None and "event" in bases:
            omission = "a window bound timed from an event is not checkable over the run's clock"
        for name, bound, basis in (("start_s", c.start_s, c.start_basis),
                                   ("end_s", c.end_s, c.end_basis))[:len(bases)]:
            if problem is None and omission is None and basis == "stated_time" and bound is None:
                problem = f"{name} is given as a stated time but has no value"
            if problem is None and omission is None and basis == "run_bound"                     and bound is not None:
                problem = f"{name} is given as the run's bound but has a value"
        text = ctx.criteria.get(name_key(c.criterion_tag))
        unstated = (_unstated_bound((c.start_s, c.end_s), text)
                    if text and not problem and not omission else None)
        if unstated is not None:
            omission = (f"{unstated:g} s is not a time the criterion states; a window timed from "
                        "an event is not checkable over the run's clock")
        if omission:
            result.omitted.append(Discarded(chunk_id="", kind="check", quote=c.condition,
                                            reason=f"{c.criterion_tag}: {omission}"))
            continue
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
                         report: ExtractReport, progress: Progress = _quiet) -> dict[str, Check]:
    checks: dict[str, Check] = {}
    controllers = [p for p in draft.parts if p.kind == "sequence_controller"]
    behaviour = sorted(passes.behaviour_refs, key=lambda r: (rank_of(r.role), r.chunk_id))
    for owner in sorted(controllers, key=lambda p: p.id):
        if not behaviour:
            report.missing_information.append(
                f"{owner.id}: no source describes the controller's states or transitions")
            continue
        effective = {p.id for p in draft.parameters if p.status == "effective"}
        criteria = {name_key(tag): ac.text for ac in draft.acceptance_criteria
                    for tag in [*ac.tags, ac.id]}
        ctx = BehaviourContext(owner=owner, parameters=effective,
                               operands={q.id for p in draft.parts for q in p.ports} | effective,
                               refs=refs, source_map=source_map, taken_ids=draft.ids(),
                               via=controller_inputs_by_source(owner, draft.connections),
                               criteria=criteria,
                               others={q.id: (p, q) for p in draft.parts if p.id != owner.id
                                       for q in p.ports},
                               connected={e for c in draft.connections
                                          for e in (c.from_port, c.to_port)},
                               parameter_units={p.id: p.unit for p in draft.parameters
                                                if p.status == "effective"})
        base = _behaviour_input(owner, draft, behaviour, draft.acceptance_criteria)
        attempts: list[BehaviourResult] = []
        text = base
        for n in range(1, BEHAVIOUR_ATTEMPTS + 1):
            progress(f"behaviour of {owner.id}: attempt {n}")
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
        report.discarded_fragments.extend(result.omitted)
        if result.machine is not None:
            owner.ports = sorted([*owner.ports, *result.ports], key=lambda q: q.id)
            draft.connections = sorted([*draft.connections, *result.connections],
                                       key=lambda c: c.id)
            draft.state_machines.append(result.machine)
            draft.questions.extend(_collision_questions(owner, result.collisions, draft.ids()))
        checks.update(result.checks)
    return checks


def _collision_questions(owner: Part, collisions: list[tuple[str, int, str, str]],
                         taken: set[str]) -> list[Question]:
    """One Question per pair of transitions left sharing a priority, naming every state where
    they clash. The dropped one is not in the model until the question is answered."""
    states: dict[tuple[str, str], list[str]] = {}
    for from_state, _, kept, dropped in collisions:
        states.setdefault((kept, dropped), []).append(from_state)
    out = []
    for (kept, dropped), where in sorted(states.items()):
        qid = make_id("q", f"q priority {owner.id} {kept} {dropped}")
        n = 2
        while qid in taken:
            qid, n = make_id("q", f"q priority {owner.id} {kept} {dropped} {n}"), n + 1
        taken.add(qid)
        out.append(Question(
            id=qid, affects=[owner.id], options=[kept, dropped],
            text=f"In {', '.join(sorted(set(where)))} of {owner.id}, '{kept}' and '{dropped}' "
                 "were given the same priority and the sources as read did not order them. Which "
                 f"is evaluated first? Only '{kept}' is in the model until this is answered."))
    return out


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
                catalogue: Catalogue | None = None, progress: Progress = _quiet,
                workers: int = 1) -> ExtractResult:
    """Evidence to a validated SystemModel and the report of what was discarded or is missing."""
    catalogue = catalogue or load_catalogue()
    report = ExtractReport()
    sources, source_map = ir_sources(bundle)
    passes = run_structure_passes(bundle, llm, catalogue, source_map, progress, workers)
    report.discarded_fragments.extend(passes.discarded)

    docs, cited = build_registry(sources, passes.documents)
    partset = resolve_parts(passes.parts, passes.aliases, catalogue)
    connections = resolve_connections(passes.connections, partset, catalogue)
    report.unresolved.extend(connections.problems)
    measured = measurement_links(partset, connections.connections, catalogue)
    connections.connections = sorted(connections.connections + measured.connections,
                                     key=lambda c: c.id)
    report.missing_information.extend(measured.missing)
    drivers = single_drivers(connections.connections, sources)
    connections.connections = drivers.connections

    candidates = []
    for f in passes.parameters:
        tag = usable_tag(f.fragment.owner_tag)
        owner = SYSTEM_OWNER if tag is None else partset.lookup(tag)
        if owner is None:
            report.unresolved.append(f"parameter {f.fragment.name} ({f.chunk_id}): owner '{tag}' "
                                     "is not a known part")
            continue
        candidates.append((owner, f))
    params = resolve_parameters(adopt_system_values(candidates), docs)
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
        questions=partset.questions + params.questions + measured.questions + drivers.questions,
        conflicts=params.conflicts + drivers.conflicts)

    checks = run_behaviour_passes(passes, draft, llm, index_chunks(bundle), source_map, report,
                                  progress)
    # after the behaviour pass, whose input lists every id: new ids would change what it is asked
    schedules = press_schedules(bundle, draft.parts, draft.parameters, source_map)
    gone = {p.id for p in schedules.replaced}
    draft.parameters = [p for p in draft.parameters if p.id not in gone]
    draft.conflicts = [c for c in draft.conflicts if c.subject.element_id not in gone]
    report.discarded_fragments.extend(
        Discarded(chunk_id="", kind="parameter", quote=p.trace[0].quote if p.trace else p.id,
                  reason=f"{p.id}: the quote does not name {p.owner}; replaced by the schedule "
                         "that names it")
        for p in schedules.replaced)
    draft.parameters.extend(schedules.parameters)
    draft.questions.extend(schedules.questions)
    for ac in draft.acceptance_criteria:
        check = next((c for tag, c in checks.items()
                      if name_key(tag) in {name_key(t) for t in ac.tags}), None)
        if check is not None:
            ac.check, ac.reason = check, None

    apply_conventions(draft)
    report.missing_information.extend(apply_run_names(draft))
    report.missing_information.extend(apply_catalogue(draft, catalogue))
    report.missing_information.extend(missing_documents(draft.sources,
                                                        params.unresolved_citations))
    report.missing_information.extend(unique_ids(draft))
    report.rejected_untraced = honesty_gate(draft)
    # after the gate, which can remove a connection and so leave an input open
    draft.questions.extend(unconnected_inputs(draft))
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
