# Purpose: pins the LLM client contract with the network mocked — strict structured outputs at
# temperature 0, one network call for two identical requests (FR-01 acceptance 3), typed
# LLMError carrying the request id instead of partial objects, token/cost logging, and the
# API key never reaching the cache.
import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from specalive.config import load_settings
from specalive.llm.cache import ResponseCache
from specalive.llm.client import (
    LLMClient,
    LLMError,
    LLMIncomplete,
    OpenAITransport,
    RawResponse,
    strict_json_schema,
)


class Port(BaseModel):
    name: str
    role: str | None


class Part(BaseModel):
    tag: str
    ports: list[Port]
    volume_m3: float | None = None


GOOD = {"tag": "T1", "ports": [{"name": "in", "role": None}], "volume_m3": 1.5}


class FakeTransport:
    """Stands in for the network: records requests, replies with a canned RawResponse."""

    def __init__(self, reply=None, error=None):
        self.requests = []
        self.reply = reply or RawResponse(json.dumps(GOOD), 100, 20, "req_1", "stop")
        self.error = error

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.reply


def make_client(tmp_path, transport, key="sk-secret-key"):
    env = {"SPECALIVE_CACHE_DIR": str(tmp_path / "cache"),
           "SPECALIVE_PRICE_IN": "2.5", "SPECALIVE_PRICE_OUT": "10"}
    if key:
        env["OPENAI_API_KEY"] = key
    settings = load_settings(env)
    return LLMClient(settings, cache=ResponseCache(settings.cache_dir), transport=transport)


def test_returns_validated_instance(tmp_path):
    client = make_client(tmp_path, FakeTransport())
    out = client.complete(prompt="extract", input_text="tank T1", schema=Part)
    assert isinstance(out, Part) and out.tag == "T1" and out.ports[0].name == "in"


def test_request_is_strict_structured_output_at_temperature_zero(tmp_path):
    t = FakeTransport()
    make_client(tmp_path, t).complete(prompt="extract", input_text="tank T1", schema=Part)
    req = t.requests[0]
    assert req["temperature"] == 0
    assert req["model"] == "gpt-4o"
    fmt = req["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert req["messages"][0] == {"role": "system", "content": "extract"}
    assert req["messages"][1] == {"role": "user", "content": "tank T1"}


def test_second_identical_call_is_served_from_cache(tmp_path):
    t = FakeTransport()
    client = make_client(tmp_path, t)
    first = client.complete(prompt="extract", input_text="tank T1", schema=Part)
    second = client.complete(prompt="extract", input_text="tank T1", schema=Part)
    assert len(t.requests) == 1
    assert first == second


def test_cache_survives_a_new_client_and_needs_no_key(tmp_path):
    make_client(tmp_path, FakeTransport()).complete(prompt="p", input_text="i", schema=Part)
    t2 = FakeTransport()
    out = make_client(tmp_path, t2, key=None).complete(prompt="p", input_text="i", schema=Part)
    assert out.tag == "T1" and t2.requests == []


def test_changed_input_misses_the_cache(tmp_path):
    t = FakeTransport()
    client = make_client(tmp_path, t)
    client.complete(prompt="p", input_text="a", schema=Part)
    client.complete(prompt="p", input_text="b", schema=Part)
    assert len(t.requests) == 2


def test_image_is_sent_as_a_data_url_beside_the_text(tmp_path):
    t = FakeTransport()
    make_client(tmp_path, t).complete(prompt="read", input_text="diagram", schema=Part,
                                      image=b"\x89PNG-bytes", image_media_type="image/png")
    user = t.requests[0]["messages"][1]
    assert user["role"] == "user"
    text_part, image_part = user["content"]
    assert text_part == {"type": "text", "text": "diagram"}
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_image_is_part_of_the_cache_key(tmp_path):
    t = FakeTransport()
    client = make_client(tmp_path, t)
    client.complete(prompt="p", input_text="i", schema=Part, image=b"one")
    client.complete(prompt="p", input_text="i", schema=Part, image=b"one")
    client.complete(prompt="p", input_text="i", schema=Part, image=b"two")
    client.complete(prompt="p", input_text="i", schema=Part)
    assert len(t.requests) == 3


def test_missing_key_on_cache_miss_raises_llm_error(tmp_path):
    t = FakeTransport()
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        make_client(tmp_path, t, key=None).complete(prompt="p", input_text="i", schema=Part)
    assert t.requests == []


def test_transport_error_propagates_with_request_id_and_nothing_is_cached(tmp_path):
    t = FakeTransport(error=LLMError("boom", request_id="req_42"))
    client = make_client(tmp_path, t)
    with pytest.raises(LLMError) as exc:
        client.complete(prompt="p", input_text="i", schema=Part)
    assert exc.value.request_id == "req_42"
    assert not list((tmp_path / "cache").glob("*.json"))


@pytest.mark.parametrize(
    "reply",
    [
        RawResponse('{"tag": "T1"', 5, 5, "req_t", "length"),        # truncated
        RawResponse("not json", 5, 5, "req_j", "stop"),              # unparseable
        RawResponse('{"tag": 3}', 5, 5, "req_v", "stop"),            # fails validation
        RawResponse(None, 5, 5, "req_r", "stop", refusal="no"),      # refusal
    ],
)
def test_bad_reply_raises_instead_of_returning_partial_object(tmp_path, reply):
    client = make_client(tmp_path, FakeTransport(reply=reply))
    with pytest.raises(LLMError) as exc:
        client.complete(prompt="p", input_text="i", schema=Part)
    assert exc.value.request_id == reply.request_id
    assert not list((tmp_path / "cache").glob("*.json"))


def test_reply_cut_off_at_the_length_limit_is_its_own_error(tmp_path):
    reply = RawResponse('{"tag": "T1"', 5, 5, "req_t", "length")
    with pytest.raises(LLMIncomplete) as exc:
        make_client(tmp_path, FakeTransport(reply=reply)).complete(prompt="p", input_text="i",
                                                                    schema=Part)
    assert isinstance(exc.value, LLMError) and exc.value.request_id == "req_t"


def test_logs_tokens_and_estimated_cost(tmp_path, caplog):
    client = make_client(tmp_path, FakeTransport())
    with caplog.at_level(logging.INFO, logger="specalive.llm"):
        client.complete(prompt="p", input_text="i", schema=Part)
    text = caplog.text
    assert "in=100" in text and "out=20" in text
    # 100 * 2.5/1e6 + 20 * 10/1e6 = 0.00045
    assert "0.00045" in text
    assert client.usage[-1].cost_usd == pytest.approx(0.00045)


def test_api_key_never_logged_or_cached(tmp_path, caplog):
    client = make_client(tmp_path, FakeTransport(), key="sk-never-show-me")
    with caplog.at_level(logging.DEBUG):
        client.complete(prompt="p", input_text="i", schema=Part)
    assert "sk-never-show-me" not in caplog.text
    for f in (tmp_path / "cache").glob("*.json"):
        assert "sk-never-show-me" not in f.read_text(encoding="utf-8")


def test_strict_schema_closes_objects_and_requires_every_property():
    schema = strict_json_schema(Part)
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["ports", "tag", "volume_m3"]
    port = schema["$defs"]["Port"]
    assert port["additionalProperties"] is False
    assert sorted(port["required"]) == ["name", "role"]
    assert "default" not in json.dumps(schema)


# --- the real OpenAI transport, against a fake SDK object (no network) ---------------------

def fake_sdk(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_openai_transport_maps_sdk_response():
    completion = SimpleNamespace(
        id="chatcmpl-1", _request_id="req_sdk",
        choices=[SimpleNamespace(finish_reason="stop",
                                 message=SimpleNamespace(content='{"a": 1}', refusal=None))],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
    )
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return completion

    raw = OpenAITransport(fake_sdk(create))({"model": "m", "temperature": 0, "messages": []})
    assert raw == RawResponse('{"a": 1}', 7, 3, "req_sdk", "stop", refusal=None)
    assert seen["temperature"] == 0


def test_openai_transport_wraps_sdk_errors_as_llm_error():
    import openai

    class FakeAPIError(openai.APIError):
        def __init__(self):
            Exception.__init__(self, "rate limited")
            self.request_id = "req_err"

    def create(**kwargs):
        raise FakeAPIError()

    with pytest.raises(LLMError) as exc:
        OpenAITransport(fake_sdk(create))({"model": "m", "messages": []})
    assert exc.value.request_id == "req_err"
