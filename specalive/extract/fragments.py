# Purpose: the records passed between the extract modules. The *Fragment and *Spec models are the
# LLM's structured-output schemas (strict mode: every field present, optional ones nullable) and
# each carries the chunk id and verbatim quote that justify it. Found wraps a fragment whose quote
# was verified with its location and chunk role; Draft is the IR under construction that gaps.py
# and the honesty gate edit in place; ExtractReport holds what extraction discarded or rejected.
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from specalive.core.ir import (
    AcceptanceCriterion,
    Assumption,
    Conflict,
    Connection,
    Parameter,
    Part,
    Question,
    Requirement,
    Source,
    SourceRole,
    StateMachine,
    SystemModel,
    TraceLink,
)


class _Located(BaseModel):
    chunk_id: str = Field(description="the [chunk id] the quote comes from")
    quote: str = Field(description="verbatim text copied from that chunk, at most 300 characters")


# --- structure pass ------------------------------------------------------------------------

class Attribute(BaseModel):
    key: str
    value: str


class PartFragment(_Located):
    tag: str = Field(description="the component's identifier as written, formal tag if given")
    aliases: list[str] = Field(description="every other name the chunk gives the same component")
    kind: str = Field(description="a catalogue kind, or 'unknown'")
    name: str | None = Field(description="short descriptive name")
    description: str | None = Field(description="what it is, required when kind is 'unknown'")
    attributes: list[Attribute] = Field(description="descriptive, non-numeric facts")


class ConnectionFragment(_Located):
    tag: str | None = Field(description="the connection's own identifier, if the source gives one")
    from_tag: str
    from_role: str | None = Field(description="catalogue port role at the source end")
    to_tag: str
    to_role: str | None = Field(description="catalogue port role at the destination end")
    medium_or_signal: str
    signal_name: str | None = Field(description="the controller I/O signal name, if one is given")


class ParameterFragment(_Located):
    owner_tag: str | None = Field(description="the component the value belongs to; null for a "
                                              "system-level value")
    name: str = Field(description="snake_case quantity name; reuse a glossary name when it is "
                                  "the same quantity")
    value: str = Field(description="the number(s) exactly as written")
    unit: str = Field(description="the unit exactly as written; '1' for dimensionless")
    cited_document: str | None = Field(description="the document the chunk names as the value's "
                                                   "source, e.g. a change record id")
    stated_status: Literal["effective", "superseded"] | None = Field(
        description="only when the evidence itself states it (status / effective columns)")
    configuration: Literal["nominal", "as_built", "prototype", "verification"]
    provisional: bool = Field(description="the source marks the value as subject to change, "
                                          "pending or to be confirmed")


class RequirementFragment(_Located):
    tag: str | None
    text: str
    category: str
    status: Literal["active", "superseded"]
    superseded_by: str | None


class CriterionFragment(_Located):
    tag: str | None
    text: str


class DocumentFragment(_Located):
    tag: str = Field(description="the document or record identifier")
    title: str | None
    role: SourceRole
    approved: bool = Field(description="the evidence states it is approved or released")
    date: str | None = Field(description="ISO date")
    revision: str | None
    file_name: str | None = Field(description="the document's file name, if the chunk gives one")


class AliasFragment(_Located):
    names: list[str] = Field(description="names the evidence explicitly equates")


class AssumptionHint(_Located):
    text: str = Field(description="the simplification the source states, in one sentence")
    affects_tags: list[str]


class FragmentReply(BaseModel):
    system_name: str | None
    system_description: str | None
    parts: list[PartFragment]
    connections: list[ConnectionFragment]
    parameters: list[ParameterFragment]
    requirements: list[RequirementFragment]
    criteria: list[CriterionFragment]
    documents: list[DocumentFragment]
    aliases: list[AliasFragment]
    assumptions: list[AssumptionHint]
    behaviour_chunk_ids: list[str] = Field(
        description="chunks describing controller states, transitions, commands or timing")


# --- behaviour pass ------------------------------------------------------------------------

class OutputValue(BaseModel):
    port_id: str
    value: bool | float


class EventSpec(BaseModel):
    id: str
    port_id: str
    edge: Literal["rising", "falling"]


class TimerSpec(BaseModel):
    id: str
    duration_parameter_id: str


class StateSpec(_Located):
    id: str
    name: str
    legacy_names: list[str]
    entry_actions: list[str]
    outputs: list[OutputValue]


class TransitionSpec(_Located):
    from_state: str
    to_state: str
    trigger_event: str | None
    guard: str | None
    actions: list[str]
    priority: int
    # with from_state "*": the states the rule does not leave from (default keeps old replies valid)
    except_states: list[str] | None = None


WindowBasis = Literal["stated_time", "event", "run_bound"]


class CheckSpec(BaseModel):
    criterion_tag: str
    mode: Literal["at", "always", "eventually"]
    condition: str
    start_s: float | None
    end_s: float | None
    # where each bound comes from; the defaults only keep replies recorded before phase 9 valid
    start_basis: WindowBasis | None = None
    end_basis: WindowBasis | None = None


class CommandPrecedenceSpec(_Located):
    events: list[str] = Field(description="event ids, the one that wins first")


class BehaviourReply(BaseModel):
    initial_state: str
    events: list[EventSpec]
    timers: list[TimerSpec]
    states: list[StateSpec]
    transitions: list[TransitionSpec]
    checks: list[CheckSpec]
    command_precedence: CommandPrecedenceSpec | None = None


# --- between modules -----------------------------------------------------------------------

F = TypeVar("F", bound=BaseModel)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def name_key(name: str) -> str:
    """The form two spellings of one name share: ASCII, lower case, letters and digits only."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM.sub("", ascii_text.lower())


@dataclass(frozen=True)
class Found(Generic[F]):
    """A fragment whose quote was found in its chunk; `quote` is the chunk's own text."""

    fragment: F
    chunk_id: str
    source_id: str  # IR source id
    locator: str
    quote: str
    role: SourceRole
    date: str | None

    @property
    def trace(self) -> TraceLink:
        return TraceLink(source_id=self.source_id, locator=self.locator, quote=self.quote)


class Discarded(BaseModel):
    chunk_id: str
    kind: str
    quote: str
    reason: str


class Rejected(BaseModel):
    kind: str
    id: str
    reason: str


class ExtractReport(BaseModel):
    discarded_fragments: list[Discarded] = Field(
        [], description="fragments whose quote or ids did not check out (R-EXT-4)")
    rejected_untraced: list[Rejected] = Field(
        [], description="elements the honesty gate removed")
    unresolved: list[str] = Field(
        [], description="verified fragments that could not be placed: unknown part, ambiguous "
                        "port, value that is not a number, unit not in the table")
    missing_information: list[str] = Field(
        [], description="required values with no source, and cited documents the bundle lacks")


@dataclass
class Draft:
    name: str
    description: str
    sources: list[Source] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    state_machines: list[StateMachine] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    def ids(self) -> set[str]:
        out: set[str] = set()
        for group in (self.sources, self.parts, self.connections, self.parameters,
                      self.state_machines, self.requirements, self.acceptance_criteria,
                      self.assumptions, self.questions, self.conflicts):
            out.update(item.id for item in group)
        for part in self.parts:
            out.update(port.id for port in part.ports)
        for sm in self.state_machines:
            for group in (sm.events, sm.timers, sm.states, sm.transitions, sm.regions):
                out.update(item.id for item in group)
        return out

    def to_model(self) -> SystemModel:
        """The validated SystemModel, every top-level collection and every part's ports sorted by
        id; raises ValueError listing the integrity problems."""
        def by_id(items):
            return sorted(items, key=lambda item: item.id)

        parts = [p.model_copy(update={"ports": by_id(p.ports)}) for p in by_id(self.parts)]
        return SystemModel(
            name=self.name, description=self.description, sources=by_id(self.sources),
            parts=parts, connections=by_id(self.connections), parameters=by_id(self.parameters),
            state_machines=by_id(self.state_machines), requirements=by_id(self.requirements),
            acceptance_criteria=by_id(self.acceptance_criteria),
            assumptions=by_id(self.assumptions), questions=by_id(self.questions),
            conflicts=by_id(self.conflicts))
