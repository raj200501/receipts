# retrykit

A small decorator that calls a function again when it raises. (Synthetic project written
for receipts-bench.)

## Usage

```python
from retrykit import retry


@retry(delay=0.5, exceptions=(ConnectionError, TimeoutError))
def fetch_stock(sku: str) -> int: ...
```

`retry` calls the function up to `max_attempts` times (three by default). After an
attempt fails with one of `exceptions` it sleeps and tries again; after the last attempt
the last exception is raised unchanged. Any other exception is raised at once.

The sleep after attempt `n` (1 for the first) is `delay * backoff ** (n - 1)`, capped
at `max_delay`, and then scaled by `1 + u`, where `u` is drawn uniformly from
`[-jitter, jitter]` by `random.Random(seed)`. One draw is made per retry and a fresh
generator is used for every call of the decorated function, so a given `seed` always
gives the same delays.

Parameters, all keyword arguments:

- `max_attempts`: how many times the function is called at most, at least 1 (default 3).
- `delay`: seconds to sleep after the first failed attempt (default `0.5`).
- `backoff`: the factor by which the sleep grows with every attempt, at least 1 (default
  `1.0`, a fixed delay).
- `max_delay`: the longest sleep before jitter (default: no cap).
- `jitter`: the relative spread of the sleep, from 0 to 1 (default `0.0`).
- `seed`: seed of the jitter generator (default: seeded from the system).
- `policy`: the name of a retry policy in `data/policies.json`, which supplies
  `max_attempts`, `delay`, `backoff`, and `max_delay`; arguments given explicitly win.
  An unknown name raises `retrykit.PolicyError` (a `ValueError`).
- `exceptions`: the exception types to retry (default `(Exception,)`).
- `sleep`: the function that sleeps (default `time.sleep`); tests pass a fake one.
- `on_retry`: a function called as `on_retry(attempt, exc, delay)` before each sleep,
  where `attempt` is the number of the attempt that just failed (1 for the first).
  `retrykit.hooks.log_retry(logger)` builds one that logs a warning.

The retry policies that operations published for our upstream services are in
`data/policies.json`.

## Development

    python3 -m pytest -v

The package lives in `src/retrykit/` and uses only the standard library.
