# tinycache

A small in-process LRU cache with hit and miss statistics, and a `memoize` decorator
built on it. (Synthetic project written for receipts-bench.)

## Usage

```python
from tinycache import LRUCache, memoize

cache = LRUCache(capacity=2)
cache.put("a", 1)
cache.put("b", 2)
cache.get("a")  # 1, and "a" is now the most recently used
cache.put("c", 3)  # evicts "b", the least recently used
cache.get("b", "gone")  # "gone"
cache.stats()  # {"hits": 1, "misses": 1, "evictions": 1, "expirations": 0}


@memoize(maxsize=64)
def square(n: int) -> int:
    return n * n
```

## API

- `LRUCache(capacity, *, ttl=None, clock=time.monotonic)`: `capacity` is at least 1. With
  `ttl` (seconds, positive) every entry expires that long after it was stored; `clock`
  is any function returning the current time in seconds, so tests can control it.
- `get(key, default=None)`: returns the value and marks the key most recently used, or
  `default` (counted as a miss; an expired entry is removed and counted in
  `expirations`).
- `put(key, value, ttl=...)`: stores a value; `ttl` gives this entry its own lifetime in
  seconds instead of the cache's default. When the cache is over capacity, expired
  entries go first and then the least recently used entry is evicted (counted in
  `evictions`).
- `purge_expired()`: removes every expired entry and returns how many it removed.
- `peek(key, default=None)`: like `get` but changes neither recency nor statistics.
- `delete(key)`: removes a key and returns whether it was there.
- `key in cache`, `len(cache)`, `cache.keys()` (least recently used first; expired
  entries are not counted or listed),
  `cache.clear()`, `cache.stats()`, `cache.reset_stats()`.
- `memoize(maxsize=128, *, ttl=None, clock=time.monotonic)`: caches results by positional and keyword arguments, which must
  be hashable; with `ttl` a result is recomputed once it is that old. The wrapped function has `.cache` and `.cache_clear()`.

How long entries may live in a cache that expires them is fixed in
[docs/EXPIRY.md](docs/EXPIRY.md).

## Development

    python3 -m pytest -v

The package lives in `src/tinycache/` and uses only the standard library.
