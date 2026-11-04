# relay-config

Typed environment configuration for the webhook relay. The relay reads its settings from
environment variables. This package describes them as a schema, reads the raw strings as
typed values, and ships `envcheck`, the command the deploy pipeline runs to check an
environment before the relay starts with it.

## envcheck

    node --experimental-strip-types bin/envcheck.ts
    node --experimental-strip-types bin/envcheck.ts --env-file examples/relay.env
    node --experimental-strip-types bin/envcheck.ts --env-file examples/relay.env --json
    npm run envcheck -- --env-file examples/relay.env

Without `--env-file`, envcheck checks its own environment. With it, it checks only the
variables in that file. When every setting can be read, it prints one `NAME=value` line
per setting in schema order (lists joined with commas, durations in their largest whole
unit, secrets as `****`) and exits with status 0; `--json` prints
`{"NAME": {"kind": ..., "value": ...}}` instead. When a setting is missing or cannot be
read, it prints `envcheck: NAME: message` on stderr, for example
`envcheck: RELAY_PORT: expected an integer, got "80a"`, and exits with status 2. An env
file that cannot be read also gives status 2.

## Settings

| Variable | Kind | Meaning |
| --- | --- | --- |
| `RELAY_PORT` | integer, 1 to 65535 | port the relay listens on |
| `RELAY_UPSTREAM_URL` | URL, https only | where verified webhooks are forwarded |
| `RELAY_SIGNING_SECRET` | string, secret, at least 32 characters | key that verifies webhook signatures |
| `RELAY_LOG_LEVEL` | `debug`, `info`, `warn`, or `error` | log verbosity |
| `RELAY_TIMEOUT` | duration | time limit for one upstream request |
| `RELAY_RETRY_LIMIT` | integer, 0 to 10 | retries before a webhook goes to the dead-letter queue |
| `RELAY_ALLOWED_EVENTS` | list | event types the relay forwards; others are dropped |
| `RELAY_QUEUE_URL` | URL | the dead-letter queue |
| `RELAY_VERIFY_TLS` | boolean | verify the upstream's TLS certificate |

Every setting is required.

## Value formats

Values are trimmed before they are read, and an empty value counts as not set.

- integer: a whole decimal number such as `8080` or `-3`
- boolean: `true`, `false`, `1`, `0`, `yes`, `no`, `on`, or `off`, in any case
- duration: a whole number and a unit, `250ms`, `30s`, `5m`, or `1h`, read as milliseconds
- list: comma-separated items; spaces around items and empty items are dropped
- URL: an absolute URL, read in its normalized form (`HTTPS://Hooks.Example.invalid:443/in`
  becomes `https://hooks.example.invalid/in`)

## Env files

An env file has one `NAME=value` per line. Blank lines and lines that start with `#` are
skipped, a line may start with `export `, and a value may be wrapped in single or double
quotes (double quotes understand `\n`, `\"`, and `\\`). In an unquoted value, ` #` starts a
comment. A line without `=`, a name that is not a valid variable name, and a variable set
twice are errors that name the line.

## Library

    import { duration, integer, string, url } from "./src/fields.ts";
    import { loadConfig } from "./src/load.ts";

    const schema = {
      PORT: integer({ min: 1, max: 65535 }),
      API_URL: url({ protocols: ["https"] }),
      API_TOKEN: string({ secret: true, minLength: 16 }),
      TIMEOUT: duration(),
    };
    const config = loadConfig(schema, process.env);
    // { PORT: number, API_URL: string, API_TOKEN: string, TIMEOUT: number }

The field builders are `string`, `integer`, `boolean`, `duration`, `list`, `url`, and
`oneOf`; each takes `secret` and `description` options. `loadConfig` reads the variables
in schema order and throws a `ConfigError` for the first one that is not set or cannot be
read; `error.variable` names it, and `error.message` is the text envcheck prints after
`envcheck: `. `loadRelayConfig` in `src/relay.ts` loads the relay's own schema,
`RELAY_SCHEMA`.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
