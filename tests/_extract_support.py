# Purpose: shared builders for the phase 4 tests — small evidence bundles, Found fragments made
# without an LLM, and FakeLLM, which serves canned structured replies by schema name (a list is
# served in order, a callable is given the input text) and records every call it receives.
from __future__ import annotations

from specalive.extract.fragments import Found
from specalive.ingest.evidence import EvidenceBundle, EvidenceChunk, Source


def chunk(source_id, locator, text, kind="prose", role=None, fields=None):
    return EvidenceChunk(source_id=source_id, locator=locator, text=text, kind=kind, role=role,
                         fields=fields or {})


def source(id, role, path=None, fmt="text", status="read", document=None, date=None,
           title=None, revision=None):
    return Source(id=id, path=path or f"{id}.txt", format=fmt, status=status,
                  reason=None if status == "read" else "not read", role=role, document=document,
                  date=date, title=title, revision=revision)


def bundle(sources, chunks):
    return EvidenceBundle(root="/bundle", sources=sources, chunks=chunks)


def found(fragment, source_id="src_a", role="design_note", date=None, locator="line 1",
          chunk_id=None):
    return Found(fragment=fragment, chunk_id=chunk_id or f"{source_id}#0", source_id=source_id,
                 locator=locator, quote=fragment.quote, role=role, date=date)


class FakeLLM:
    def __init__(self, replies):
        self.replies = {k: list(v) if isinstance(v, list) else v for k, v in replies.items()}
        self.calls = []

    def complete(self, *, prompt, input_text, schema, **kwargs):
        self.calls.append((prompt, input_text, schema.__name__))
        reply = self.replies[schema.__name__]
        if callable(reply):
            value = reply(input_text)
        else:
            value = reply.pop(0) if len(reply) > 1 else reply[0]
        return schema.model_validate(value)


def empty_reply(**overrides):
    reply = {"system_name": None, "system_description": None, "parts": [], "connections": [],
             "parameters": [], "requirements": [], "criteria": [], "documents": [], "aliases": [],
             "assumptions": [], "behaviour_chunk_ids": []}
    reply.update(overrides)
    return reply


def empty_behaviour(**overrides):
    reply = {"initial_state": "", "events": [], "timers": [], "states": [], "transitions": [],
             "checks": []}
    reply.update(overrides)
    return reply


def part(chunk_id, quote, tag, kind, aliases=(), name=None, attributes=None):
    return {"chunk_id": chunk_id, "quote": quote, "tag": tag, "aliases": list(aliases),
            "kind": kind, "name": name, "description": None,
            "attributes": [{"key": k, "value": v} for k, v in (attributes or {}).items()]}


def param(chunk_id, quote, owner, name, value, unit, cited=None, status=None,
          configuration="nominal", provisional=False):
    return {"chunk_id": chunk_id, "quote": quote, "owner_tag": owner, "name": name,
            "value": value, "unit": unit, "cited_document": cited, "stated_status": status,
            "configuration": configuration, "provisional": provisional}


def connection(chunk_id, quote, from_tag, to_tag, from_role=None, to_role=None, tag=None,
               medium="liquid", signal=None):
    return {"chunk_id": chunk_id, "quote": quote, "tag": tag, "from_tag": from_tag,
            "from_role": from_role, "to_tag": to_tag, "to_role": to_role,
            "medium_or_signal": medium, "signal_name": signal}
