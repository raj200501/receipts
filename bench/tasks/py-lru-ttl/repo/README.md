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
cache.stats()  # {"hits": 1, "misses": 1, "evictions": 1}


@memoize(maxsize=64)
def square(n: int) -> int:
    return n * n
```

## API

- `LRUCache(capacity)`: `capacity` is at least 1.
- `get(key, default=None)`: returns the value and marks the key most recently used, or
  `default` (counted as a miss).
- `put(key, value)`: stores a value; when the cache is over capacity the least recently
  used entry is evicted (counted in `evictions`).
- `peek(key, default=None)`: like `get` but changes neither recency nor statistics.
- `delete(key)`: removes a key and returns whether it was there.
- `key in cache`, `len(cache)`, `cache.keys()` (least recently used first),
  `cache.clear()`, `cache.stats()`, `cache.reset_stats()`.
- `memoize(maxsize=128)`: caches results by positional and keyword arguments, which must
  be hashable. The wrapped function has `.cache` and `.cache_clear()`.

How long entries may live in a cache that expires them is fixed in
[docs/EXPIRY.md](docs/EXPIRY.md).

## Development

    python3 -m pytest -v

The package lives in `src/tinycache/` and uses only the standard library.
