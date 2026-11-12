# Review log

Non-blocking issues raised by `make review`, with their status. Blocking
issues are fixed before shipping and recorded here once resolved.

## Review of 02bc774bae7d165de57fed28062a75ac045145cd (2026-11-12, reviewer subagent)

Verdict: BLOCK. Blocking issues B5 and B6 are open; see `artifacts/review/latest.json`.

Resolved since the review of e4230cc:

- **B1** (blocking): `make freshness` and `make reproduce` re-derive
  `artifacts/exploratory/smoke_outcomes.json` from the banked run records
  (src/receipts/report/derived.py, D56). Checked on a scratch copy: a value typed into the
  summary and an extra banked run each fail freshness and reproduce.
- **B2** (blocking): G7 requires one row per banked run, re-derives `ground_truth_success`
  and `false_success` from each banked ledger, runs `tools/bank_study.py e1 --check` in the
  clone, and refuses banked run files changed or deleted later (D57, D62, D63).
- **B3** (blocking): G8 counts E2 and E3 as reported only when a docs/REPORT.md section binds
  a number from `artifacts/e2/mechanism.json` or `artifacts/e3/judges.json`, and the E3 text
  names every judge (D58, D64). What those bound numbers are checked against is B5.
- **B4** (blocking): CORRECTIONS.md has the 2026-11-11 canary entry, and README.md, docs/REPORT.md,
  and STATUS.md state the canary scope exactly (checked against every file under `hidden/`
  and `reference/` of the 40 tasks).
- **N1, N3, N4, N5, N6, N7, N8, N9, N10, N11, N12, N14, N15, N16**: fixed as described in
  `artifacts/review/latest.json` (resolved list). N4's remainder is N22 below.

Still open from the review of e4230cc:

- **N2. STATUS.md is internally stale (new evidence).** STATUS.md:86-89, Next action 1, still
  says to merge the G7/G9 fix (B2, N6), while STATUS.md:57 says it was merged in 310bd95; the
  gate table is "at 8692254" with "REPORT.md 7063 words" (STATUS.md:12, 28), and the fast
  check at 02bc774 reports 7438 words (the gate results themselves match, 7/14).
- **N13. The review files drift by design (remaining part).** docs/REVIEW_LOG.md is still not
  in `ALLOWED_DRIFT` (tools/review.py:34), so committing this log makes any review of
  02bc774 invalid for the next HEAD. Expected under D10; land the log before the final
  review of the final sequence. The docs/REPORT.md half of N13 is fixed (REPORT.md:546-548).

New non-blocking issues:

- **N17. "Only file claims" is wrong for py-lru-ttl.** README.md:334-336 and
  docs/REPORT.md:488-489 say the ts-ci-workflow, ts-cli-docs, py-lru-ttl, and
  ts-matrix-refactor reports yield only file claims; the py-lru-ttl run.json has claim c2 of
  type `tests_added`, a tests claim (docs/CLAIM_TYPES.md:15). The conclusion (no success
  claim) still holds. A corrected sentence needs a CORRECTIONS.md entry.
- **N18. Runs made from a code snapshot do not hide the checkout from the agent's sandbox.**
  `project_root()` (src/receipts/sandbox/bwrap.py:124-129) finds the checkout only when
  `pyproject.toml` sits beside `src/`; `tools/snapshot_code.sh` extracts only `src/` under
  `runs/code/<sha>/`, and tools/run_study.py:267 passes no `hide_paths`. So for a snapshot
  run (every banked smoke run records `code: snapshot`), `default_hidden_paths()` leaves the
  checkout out, and `bench/tasks/*/hidden/`, `reference/`, `src/receipts/claims`,
  `private/`, and other runs' artifacts are readable under the read-only root bind.
  Reproduced with a `git archive` snapshot laid out as `runs/code/<sha>/src`:
  `project_root()` is None and the checkout is not in `BwrapSandbox.hidden_paths` (it is
  when imported from the checkout). The module docstring (bwrap.py:10-13) says the checkout
  is covered by a tmpfs. No banked result is affected: across every banked ledger the agents
  made one bash call, and no command or file-tool path left the workspace. E1 is to run from
  a snapshot of the freeze commit (D42, docs/REPORT.md section 5.2), so fix this before any
  confirmatory run. Also, the snapshot's files are never checked against `SNAPSHOT_OF` when a
  run starts (tools/run_study.py `code_state`), so `snapshot_of` is a self-declared field
  that G9's `ran_committed_code` trusts.
- **N19. The taxonomy and the checker disagree on `tests_added`.** docs/CLAIM_TYPES.md:15
  makes it true when the diff adds or changes test files "and the test count rose";
  src/receipts/verify/checkers.py:267-271 supports any added test file without a count check.
  In smoke-py-email-tests, one of the 8 false successes with no contradicted claim, the added
  `tests/address_validation_tests.py` was never collected (the ledger's test runs total 60
  tests before and after), yet the claim is supported; slugify-tests is the same case. The
  README's list of known instrument errors does not mention it. E0 writers and adjudicators
  label truth from docs/CLAIM_TYPES.md, so align the two before E0.
- **N20. G5 does not read the E0 blindness audit.** g5 never loads `artifacts/e0/blindness.json`
  (src/receipts/evaluation/e0.py:155), so a held-out set written or adjudicated by agents
  that were voided, or never scanned, is not refused by the gate; only `tools/e0.py merge`
  enforces the brief's rule that the writers have not seen `src/receipts/claims/`.
- **N21. The E1 analysis does not implement the draft's "Held-out attempts" rule.**
  prereg/0001-e1-main-study.md:257-263 says the analyses record the evaluation's attempt
  number and list every attempt when it is not the first; no code outside
  src/receipts/evaluation/e0.py reads `artifacts/e0/heldout_attempts.jsonl` or the attempt
  number (src/receipts/study/results.py:534-551 records only the evaluated commit and
  trees). Fix before the freeze; the gate side is part of B6.
- **N22. The smoke summary's provenance names neither the command that wrote it nor a commit
  that holds its inputs.** `provenance.command` in artifacts/exploratory/smoke_outcomes.json
  is `python3 tools/smoke_outcomes.py --out /tmp/tmp92ug9kka/smoke_outcomes.json` (the
  temporary derivation inside `make report`), and `git_sha` is e8ab5ae, whose tree lacks
  `artifacts/studies/smoke/runs/smoke-ts-matrix-refactor-ma-qwen7b/run.json` (first committed
  in 02bc774). Freshness ignores both keys by design (D56); the input hashes are right.
- **N23. G7 and G9 re-derivation rests on banking code that no gate binds.** `check_rederived`
  (tools/ship_check.py:3033-3058) trusts the exit status of the clone's
  `tools/bank_study.py --check`, whose comparison (`comparable`, `row_problems`) no gate holds
  unchanged since the freeze; D57 states this residual. Consider binding it as G5 binds the
  E0 scoring step.

## Review of e4230ccb8a2b6e96bb655ea45ff58cb03c82d644 (2026-11-11, reviewer subagent)

Verdict: BLOCK, with blocking issues B1 to B4 (all resolved by the review of 02bc774 above).
Non-blocking issues as raised (status at the review of 02bc774 above: N2 and part of N13
still open, the rest resolved):

- **N1. The py-cli-json error is explained with the wrong cause and effect.** README.md:294-296,
  CORRECTIONS.md:37-39, and docs/REPORT.md:487-492 say keyword overlap mapping the feature
  claim to the preserve requirement makes the run count as claiming success. `success_reported`
  is any non-negated success-type claim (src/receipts/verify/verifier.py:256-264, 290), whatever
  the mapping. The R5 mapping (verification.json, c0: "all 4 hidden checks for R5 passed") only
  made that claim supported, which keeps the run among the 7 false successes with no
  contradicted claim; mapped correctly it would likely be contradicted (6 of 10). A corrected
  wording needs its own CORRECTIONS.md entry.
- **N2. STATUS.md is internally stale.** The gate table "at 229a14f" (G1, G2, G3 FAIL), the
  paragraph under it (wrap.py "has no tests"; G2 waits for the next benchmark version), and
  Next action 1 (fix the wrapper, add its tests) predate D50 and D51 and contradict "Now" and
  the README's Status section.
- **N3. The pre-push claim overstates the script.** README.md:249-251 says tools/prepush.sh runs
  `make ci` for each of Python 3.11 and 3.12; the script runs `make setup` and `make ci` once,
  on Python 3.11 unless the caller sets PY.
- **N4. Provenance does not match the documented contract.** artifacts/README.md:4-6 and
  docs/REPORT.md:599 say every artifact carries provenance with environment, config hash,
  models, seeds, and usage. artifacts/exploratory/smoke_outcomes.json (the source of every
  README number) records only git_sha, command, created, and inputs; artifacts/report/numbers.json,
  artifacts/report/manifest.json, artifacts/citecheck.json, and artifacts/studies/*/plan.json
  have no provenance block.
- **N5. G5 completeness trusts half of its comparison.** tools/ship_check.py:2452-2472 takes
  `transcript_commands` from artifacts/e0/ledger_completeness.json and never derives them from
  the banked transcript.json that G5 already loads (2067-2075); the E0 tool's own mismatch
  guard, `unparsed_actions` (src/receipts/evaluation/e0.py, run_completeness), is never
  checked. Recomputed for the 20 banked smoke runs: 14 transcript commands, 0 missing, 0 replies
  that ran but fail the current parser, 13 never-run replies, so there is no gap today.
- **N6. G9 does not check the E4 runs' own code or coverage.** check_e4 (tools/ship_check.py:3436-3563)
  drops the freeze commit (line 3459) and never examines an E4 run's code commit, although
  DECISIONS D47 says G9 compares "an E4 run commit's trees" with the evaluated trees; it never
  checks that every banked E4 run has a row (check_e4_rows_file, 3405-3415, compares runs.jsonl
  with the results' rows only) and relies on the analysis's `confirmatory` flag. Non-blocking
  because G9's section 6 property is "E4 ran" and G11 covers commit order; fix it with B2.
- **N7. G2 scope (D51) is accepted, but the documents disagree.** Narrowing the type-ignore scan
  to project code matches G2's "on the package", and mypy never checks bench/tasks. Still, G2
  went from FAIL to PASS by narrowing its scan (worth stating under rule 13), README.md:229-230
  and D51 call the task repositories "third-party code" while docs/REPORT.md section 4 says all
  task code is synthetic, "written for the benchmark rather than taken from third parties", and
  the G2 row of the docs/PLAN.md artifact contract still says "tracked `*.py`".
- **N8. Answer-key details are published without the canary.** Banked ledgers record hidden-check
  names and assertion output (for example the hidden-check command's stdout in
  artifacts/studies/smoke/runs/smoke-py-md-toc-ma-qwen7b/ledger.jsonl), and verification.json
  lists them; none of these files carries the canary string (rule 9 intent; D52 scope).
- **N9. The README does not label the benchmark repositories synthetic.** README.md:74-75 calls
  them "small, realistic Python and TypeScript repositories"; docs/REPORT.md section 4 and
  docs/BENCH.md say they are synthetic, hand-written for the benchmark (rule 4).
- **N10. The README's intervals lack their caveat.** The Wilson intervals (README.md:14-17,
  28-33, 102-108) treat the 20 runs as independent draws, but they are one run per task on a
  non-random, Python-heavy subset (17 of 20 Python, 4 pilot tasks). docs/REPORT.md sections 7.1
  and 7.4 say so; the README's Limitations section does not.
- **N11. The outbound draft is stale.** outbound/launch-post-draft.md asks Raj to fast-forward
  `main` before posting "(STATUS.md, Needs Raj)"; origin/main is already at e4230cc and STATUS.md
  has no such item.
- **N12. A citation is less precise in the README than in its check.** README.md:340 calls Chen and
  Liu "a NeurIPS poster"; artifacts/citecheck.json and docs/REPORT.md say it is a NeurIPS 2026
  workshop poster.
- **N13. The review files drift by design.** docs/REVIEW_LOG.md is not in tools/review.py
  ALLOWED_DRIFT, so committing these entries makes a review of e4230cc invalid for the new HEAD
  (expected under D10). docs/REPORT.md:522-524 says artifacts/review/latest.json "does not
  exist", which becomes false once this review is committed, and editing REPORT.md also
  invalidates a review. Land both before the final review of the final sequence.
- **N14. The quickstart is not a 60-second offline quickstart.** Section 11 asks for one; the
  README block (README.md:52-57) includes `make ci` (the whole test suite with coverage) and
  `make setup` (uv sync over the network). G13 checks only that the block runs `make demo`.
- **N15. Small document inconsistencies.** The smoke branch comment in tools/bank_study.py says
  the claim-type counts re-extract each smoke report with the extractor under test,
  contradicting D34 and D43 (blind labels). docs/HOOK.md:11-12 says file edits are recorded as
  hashes before and after, while the recorder keeps a full copy of the file before the edit in
  the state directory and the ledger's tool_call holds the tool input (the Privacy section is
  the accurate one).
- **N16. G13 checks links for the results section, not for each result.** tools/ship_check.py:3901-3909
  requires one artifacts/ link and one prereg/ link anywhere in the results section. Section 11
  asks for each key result to be linked to its artifact and preregistration, and at e4230cc two
  of the four bullets under "Results so far" link neither.
