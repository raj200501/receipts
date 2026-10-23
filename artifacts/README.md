# Banked artifacts

Every result number in this repository is derived by a committed script from a
file under `artifacts/`. Each artifact carries provenance: git SHA, config hash,
model IDs and revisions, seeds, timestamps, environment, exact command lines,
and usage. Confirmatory artifacts also carry `"confirmatory": true`, the
`"prereg"` path they follow, and its `"prereg_sha256"`.

The layout that `tools/ship_check.py` verifies is documented in docs/PLAN.md
(section "Artifact contract").

`artifacts/usage/ledger.jsonl` logs every model call (tokens, wall time, cap
share, `cash_usd` which is always 0, and the API-price estimate as
`plan_equivalent_usd`). It never holds prompts, transcripts, or secrets.
