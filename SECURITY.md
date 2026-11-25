# Security policy

## Reporting a vulnerability

Please report security problems privately to the maintainer through GitHub's
private vulnerability reporting on this repository. Do not open a public issue
for a vulnerability. Expect an acknowledgement within a week.

## Scope and design

receipts runs untrusted agent tool calls and third-party task code. By design:

- Subject agents, task graders, and benchmark scripts never run directly on the
  host. Study runs use bubblewrap with no network, the host root read-only, this
  repository's checkout hidden, and an allowlisted environment that keeps
  credentials out (DECISIONS D22, D33, D67); a Docker backend with
  `--network none` is also available.
- No real credentials, real systems, or harmful payloads are used. Tools given
  to agents are mocks inside disposable workspaces.
- Secrets live only in environment variables. `make secrets-scan` runs in CI
  and in `make ship-check`.
- Real transcripts (including the maintainer's) are analyzed locally and never
  committed. Only aggregates are committed.

If you find a way for a subject agent to escape its sandbox, reach the network
when it should not, or read a credential, please report it privately.
