# throttle

The per-client rate limiter of the API gateway, as a library, plus a command-line tool
that replays a gateway request log through it. Replays answer questions such as "how
many of this client's requests would the new limits have rejected yesterday?"

## How the limiter works

Every client has a token bucket. The bucket holds at most `burst` tokens and refills
continuously at `per_minute` tokens per minute; a new client starts with a full
bucket. Each request takes one token, and a request that finds less than one whole
token is rejected with a Retry-After: the number of seconds until the bucket has a
token again. Clients that have sent no request for 60 seconds are forgotten, so the
gateway does not keep a bucket for every client it has ever seen.

## Limits

The limits are in `config/limits.toml`:

    [policy]
    include = ["data/internal-limits.toml"]

    [default]
    burst = 20
    per_minute = 60

    [clients.reports-web]
    burst = 40
    per_minute = 120

A client without its own `[clients.NAME]` table gets the `[default]` limit. Files
named in `[policy] include` (paths relative to the repository root, the parent of
`config/`) add more `[clients.NAME]` tables; other teams keep their clients' limits in
such files. A client may be listed only once across all of them.

## Usage

    python3 -m throttle limits
    python3 -m throttle replay examples/gateway-2026-10-28.csv
    python3 -m throttle replay examples/gateway-2026-10-28.csv --rejected
    python3 -m throttle --config other/limits.toml replay requests.csv

`limits` prints the default limit and the limit of every listed client. `replay`
reads a request log, a CSV file with the header `time,client,method,path` whose times
are ISO 8601 times with `Z` or an offset, in time order:

    time,client,method,path
    2026-10-28T14:00:00.000Z,billing-export,GET,/v1/invoices?page=1

and prints how many requests of each client were allowed and rejected, for example:

    client          allowed  rejected
    mobile-app           42         3
    partner-portal        9         0
    reports-web         118         0
    total               169         3

With `--rejected` it also lists every rejected request and its Retry-After. A limits
file or log that cannot be read stops the command with a message (naming the line for
a log), and the command exits with status 2.

## Library

    from throttle.clock import ManualClock
    from throttle.limiter import Limiter
    from throttle.policy import load_policy

    clock = ManualClock()
    limiter = Limiter(load_policy(), clock)
    decision = limiter.check("reports-web")   # Decision(allowed=True, retry_after_s=0)
    clock.advance(1.5)
    limiter.tracked_clients()                 # ["reports-web"]

## Development

    python3 -m pytest -v

The package lives in `src/throttle/` and uses only the standard library.
