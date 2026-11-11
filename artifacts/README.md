# Banked artifacts

Every result number in this repository is derived by a committed script from a
file under `artifacts/`. What each kind of artifact records about how it was made:

- **Run records** (`studies/<study>/runs/<run>/run.json`): the full provenance of
  section 10.2 step 5: git SHA (and the code snapshot it ran), exact command, time,
  environment, model ID, file hash, and source revision, model-server command and
  its hash, agent-config hash, seed, task tree hash (except the early pipeline-check
  run, which predates it), sandbox backend, and the run's token usage and wall time.
- **Results derived from run records** (such as `exploratory/smoke_outcomes.json`):
  git SHA, exact command, time, environment, and the SHA-256 of every input record,
  with the models, agent-config hashes, seeds, and token usage of those runs (the
  derivation itself makes no model call). `make freshness` re-derives them (D56).
- **Environment and benchmark checks** (`env/`, `bench/reference_validation.json`):
  git SHA, command, time, and environment, plus the model and server for a
  throughput measurement.
- **Generated indexes** (`report/numbers.json`, `report/manifest.json`): each value
  or file with its source artifact and that artifact's SHA-256; they are rebuilt by
  `make report` and checked by `make freshness` and `make reproduce`.
- **Records kept by their own tools**: `citecheck.json` (each reference's retrieval
  date, final URL, page title, and content hash) and `review/latest.json` (the
  reviewed commit, the reviewer, and the time).
- **Study plans** (`studies/<study>/plan.json`) are inputs, not results; each run
  made from a plan records the plan's run spec.

Confirmatory artifacts also carry `"confirmatory": true`, the `"prereg"` path they
follow, and its `"prereg_sha256"`.

The layout that `tools/ship_check.py` verifies is documented in docs/PLAN.md
(section "Artifact contract").

`artifacts/usage/ledger.jsonl` logs every model call (tokens, wall time, cap
share, `cash_usd` which is always 0, and the API-price estimate as
`plan_equivalent_usd`). It never holds prompts, transcripts, or secrets.
