# Review log

Non-blocking issues raised by `make review`, with their status. Blocking
issues are fixed before shipping and recorded here once resolved.

## Review of e4230ccb8a2b6e96bb655ea45ff58cb03c82d644 (2026-11-11, reviewer subagent)

Verdict: BLOCK. Blocking issues B1 to B4 are open; see `artifacts/review/latest.json`.
Non-blocking issues, all open:

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
