# Verifier test fixtures (synthetic)

Everything in this directory is synthetic test data, hand-built for the
`receipts.verify` tests. None of it comes from a real agent run or a real model.

- `synthetic_run.jsonl`: a hash-chained ledger written by
  `tests.verify.ledgers.build_fixture_ledger` through `LedgerWriter` with a fake
  clock. Its invented story: the agent edits `src/dates/parse.py`, its own test
  run passes 4 of 4, the post-run snapshot rerun finds a fifth test failing, and
  the hidden check for requirement R2 fails. `run_start` carries a `note` field
  saying the ledger is synthetic. `tests/verify/test_verifier.py` regenerates the
  file and fails if the committed copy differs.
