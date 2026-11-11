from tinycache import LRUCache, Stats


def test_new_cache_has_zero_counters() -> None:
    assert LRUCache(2).stats() == {"hits": 0, "misses": 0, "evictions": 0, "expirations": 0}


def test_hits_misses_and_evictions_are_counted() -> None:
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.get("a")
    cache.get("b")
    cache.put("b", 2)
    assert cache.stats() == {"hits": 1, "misses": 1, "evictions": 1, "expirations": 0}


def test_reset_stats() -> None:
    cache = LRUCache(1)
    cache.get("a")
    cache.reset_stats()
    assert cache.stats()["misses"] == 0


def test_stats_snapshot_is_a_copy() -> None:
    cache = LRUCache(1)
    snapshot = cache.stats()
    cache.get("a")
    assert snapshot["misses"] == 0


def test_hit_rate() -> None:
    stats = Stats(hits=3, misses=1)
    assert stats.lookups == 4
    assert stats.hit_rate == 0.75
    assert Stats().hit_rate == 0.0
