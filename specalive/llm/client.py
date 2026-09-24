# Purpose: the one way SpecAlive calls an LLM. complete() takes a Pydantic model as the response
# schema, sends it as an OpenAI strict structured output at temperature 0, and returns a validated
# instance — or raises LLMError with the request id, never a partial object. An optional image
# goes beside the text as a data URL, and its hash joins the cache key. Every result is
# cached on disk (llm/cache.py), so a repeat call makes no network request; tokens and estimated
# cost are logged per call. `openai` is imported lazily so importing this module needs no key.
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from specalive.config import Settings
from specalive.llm.cache import ResponseCache

log = logging.getLogger("specalive.llm")

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    """A failed LLM call. `request_id` is the provider's id when one exists."""

    def __init__(self, message: str, request_id: str | None = None) -> None:
        super().__init__(message if request_id is None else f"{message} (request_id={request_id})")
        self.request_id = request_id


@dataclass(frozen=True)
class RawResponse:
    """What the transport hands back: the reply text plus accounting, before any validation."""

    content: str | None
    input_tokens: int
    output_tokens: int
    request_id: str | None
    finish_reason: str | None
    refusal: str | None = None


@dataclass(frozen=True)
class CallUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool


Transport = Callable[[dict[str, Any]], RawResponse]


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for `model` in the form OpenAI strict mode accepts: every object closed with
    additionalProperties=false, every property required (optional fields stay `X | None`),
    no defaults, and no keywords beside a $ref."""
    return _strictify(copy.deepcopy(model.model_json_schema()))


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node
    node.pop("default", None)
    if "$ref" in node:
        return {"$ref": node["$ref"]}
    for key, value in list(node.items()):
        node[key] = _strictify(value)
    if node.get("type") == "object" and "properties" in node:
        node["additionalProperties"] = False
        node["required"] = list(node["properties"])
    return node


def _user_content(text: str, image: bytes | None, media_type: str) -> str | list[dict[str, Any]]:
    if image is None:
        return text
    url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
    return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]


class OpenAITransport:
    """Sends a prepared request through the OpenAI SDK and maps the reply to a RawResponse."""

    def __init__(self, sdk_client: Any) -> None:
        self._sdk = sdk_client

    def __call__(self, request: dict[str, Any]) -> RawResponse:
        import openai

        try:
            completion = self._sdk.chat.completions.create(**request)
        except openai.OpenAIError as exc:
            raise LLMError(f"OpenAI API error: {exc}", getattr(exc, "request_id", None)) from exc
        choice = completion.choices[0]
        usage = completion.usage
        return RawResponse(
            content=choice.message.content,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            request_id=getattr(completion, "_request_id", None) or getattr(completion, "id", None),
            finish_reason=choice.finish_reason,
            refusal=getattr(choice.message, "refusal", None),
        )


class LLMClient:
    def __init__(self, settings: Settings, cache: ResponseCache | None = None,
                 transport: Transport | None = None) -> None:
        self._settings = settings
        self._cache = cache if cache is not None else ResponseCache(settings.cache_dir)
        self._transport = transport
        self.usage: list[CallUsage] = []

    def complete(self, *, prompt: str, input_text: str, schema: type[M],
                 image: bytes | None = None, image_media_type: str = "image/png") -> M:
        s = self._settings
        json_schema = strict_json_schema(schema)
        key_text = input_text if image is None else (
            f"{input_text}\n\x00image {image_media_type} {hashlib.sha256(image).hexdigest()}")
        key = ResponseCache.key(s.model, prompt, json_schema, key_text)

        cached = self._cache.get(key)
        if isinstance(cached, dict) and "response" in cached:
            try:
                result = schema.model_validate(cached["response"])
            except ValidationError:
                log.warning("cache entry %s no longer matches %s; calling the API", key[:12],
                            schema.__name__)
            else:
                self._record(CallUsage(s.model, 0, 0, 0.0, cached=True), request_id=None)
                return result

        request = {
            "model": s.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": _user_content(input_text, image, image_media_type)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": True},
            },
        }
        raw = self._get_transport()(request)
        cost = (raw.input_tokens * s.price_in_per_mtok
                + raw.output_tokens * s.price_out_per_mtok) / 1_000_000
        self._record(CallUsage(s.model, raw.input_tokens, raw.output_tokens, cost, cached=False),
                     request_id=raw.request_id)

        result = self._validate(raw, schema)
        self._cache.put(key, {"model": s.model, "schema": schema.__name__,
                              "response": result.model_dump(mode="json")})
        return result

    def _validate(self, raw: RawResponse, schema: type[M]) -> M:
        if raw.refusal:
            raise LLMError(f"model refused: {raw.refusal}", raw.request_id)
        if raw.finish_reason != "stop":
            raise LLMError(f"incomplete reply (finish_reason={raw.finish_reason})", raw.request_id)
        if raw.content is None:
            raise LLMError("empty reply", raw.request_id)
        try:
            return schema.model_validate(json.loads(raw.content))
        except (ValueError, ValidationError) as exc:
            raise LLMError(f"reply does not match {schema.__name__}: {exc}", raw.request_id) from exc

    def _get_transport(self) -> Transport:
        if not self._settings.has_api_key:
            raise LLMError("OPENAI_API_KEY is not set; only cached responses are available")
        if self._transport is None:
            import openai

            self._transport = OpenAITransport(openai.OpenAI(
                api_key=self._settings.openai_api_key, timeout=self._settings.llm_timeout_s))
        return self._transport

    def _record(self, usage: CallUsage, request_id: str | None) -> None:
        self.usage.append(usage)
        if usage.cached:
            log.info("llm cache hit model=%s", usage.model)
        else:
            log.info("llm call model=%s in=%d out=%d cost_usd~%.5f request_id=%s", usage.model,
                     usage.input_tokens, usage.output_tokens, usage.cost_usd, request_id)
