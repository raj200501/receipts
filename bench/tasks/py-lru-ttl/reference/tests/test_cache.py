import pytest
from tinycache import LRUCache


def test_put_then_get() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1


def test_get_missing_returns_default() -> None:
    cache = LRUCache(2)
    assert cache.get("a") is None
    assert cache.get("a", "x") == "x"


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        LRUCache(0)


def test_least_recently_used_entry_is_evicted() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.keys() == ["b", "c"]


def test_get_refreshes_recency() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.keys() == ["a", "c"]


def test_put_of_an_existing_key_replaces_and_refreshes() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    assert cache.keys() == ["a", "c"]
    assert cache.get("a") == 10


def test_peek_does_not_refresh_or_count() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.peek("a") == 1
    cache.put("c", 3)
    assert cache.keys() == ["b", "c"]
    assert cache.stats() == {"hits": 0, "misses": 0, "evictions": 1, "expirations": 0}


def test_delete_reports_presence() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.delete("a") is True
    assert cache.delete("a") is False
    assert len(cache) == 0


def test_contains_and_len() -> None:
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    assert "z" not in cache
    assert len(cache) == 2


def test_contains_does_not_refresh() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    cache.put("c", 3)
    assert "a" not in cache


def test_clear_keeps_statistics() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.get("a")
    cache.clear()
    assert len(cache) == 0
    assert cache.stats()["hits"] == 1


def test_none_is_a_storable_value() -> None:
    cache = LRUCache(2)
    cache.put("a", None)
    assert "a" in cache
    assert cache.get("a", "default") is None


def test_capacity_property() -> None:
    assert LRUCache(5).capacity == 5


@pytest.mark.parametrize("key", [1, "text", (1, 2), None, 2.5])
def test_any_hashable_key_works(key: object) -> None:
    cache = LRUCache(2)
    cache.put(key, "v")
    assert cache.get(key) == "v"
