# retrykit

A small decorator that calls a function again when it raises. (Synthetic project written
for receipts-bench.)

## Usage

```python
from retrykit import retry


@retry(delay=0.5, exceptions=(ConnectionError, TimeoutError))
def fetch_stock(sku: str) -> int: ...
```

`retry` calls the function up to three times. After an attempt fails with one of
`exceptions` it sleeps for `delay` seconds and tries again; after the third failure the
last exception is raised unchanged. Any other exception is raised at once.

Parameters, all keyword arguments:

- `delay`: seconds to sleep between attempts (default `0.5`).
- `exceptions`: the exception types to retry (default `(Exception,)`).
- `sleep`: the function that sleeps (default `time.sleep`); tests pass a fake one.
- `on_retry`: a function called as `on_retry(attempt, exc, delay)` before each sleep,
  where `attempt` is the number of the attempt that just failed (1 for the first).
  `retrykit.hooks.log_retry(logger)` builds one that logs a warning.

The retry policies that operations published for our upstream services are in
`data/policies.json`. They are not used by the decorator yet.

## Development

    python3 -m pytest -v

The package lives in `src/retrykit/` and uses only the standard library.
