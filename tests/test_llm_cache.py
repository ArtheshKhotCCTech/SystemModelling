# Purpose: pins the on-disk LLM response cache — the key changes with model, prompt, schema
# and input (R-FND-5: a model change never returns a stale answer), stored values round-trip
# exactly, a corrupt entry reads as a miss rather than a crash, and clear() empties it.
import pytest

from specalive.llm.cache import ResponseCache

BASE = dict(model="m1", prompt="p", schema={"type": "object"}, input_text="in")


def test_key_is_stable():
    assert ResponseCache.key(**BASE) == ResponseCache.key(**BASE)


@pytest.mark.parametrize(
    "field,value",
    [("model", "m2"), ("prompt", "p2"), ("schema", {"type": "string"}), ("input_text", "in2")],
)
def test_key_changes_with_each_component(field, value):
    assert ResponseCache.key(**{**BASE, field: value}) != ResponseCache.key(**BASE)


def test_key_ignores_schema_key_order():
    a = ResponseCache.key(**{**BASE, "schema": {"a": 1, "b": 2}})
    b = ResponseCache.key(**{**BASE, "schema": {"b": 2, "a": 1}})
    assert a == b


def test_miss_then_hit_round_trips(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    k = ResponseCache.key(**BASE)
    assert cache.get(k) is None
    value = {"name": "tank", "items": [1, 2.5, "ü"], "nested": {"ok": True}}
    cache.put(k, value)
    assert cache.get(k) == value
    assert ResponseCache(tmp_path / "cache").get(k) == value  # survives a new instance


def test_corrupt_entry_is_a_miss(tmp_path):
    cache = ResponseCache(tmp_path)
    k = ResponseCache.key(**BASE)
    cache.put(k, {"x": 1})
    next(tmp_path.glob("*.json")).write_text("{not json", encoding="utf-8")
    assert cache.get(k) is None


def test_clear_removes_entries_and_reports_count(tmp_path):
    cache = ResponseCache(tmp_path / "c")
    for i in range(3):
        cache.put(ResponseCache.key(**{**BASE, "input_text": str(i)}), {"i": i})
    assert cache.clear() == 3
    assert cache.get(ResponseCache.key(**{**BASE, "input_text": "0"})) is None
    assert cache.clear() == 0


def test_clear_on_missing_directory_is_zero(tmp_path):
    assert ResponseCache(tmp_path / "never-created").clear() == 0
