# Log

History moved out of STATUS.md, newest first.

## 2026-11-11: release sprint (goal_turn 5), moved from STATUS.md

Release sprint, 2026-11-11 (goal_turn 5): Raj is making the repository public. The goal's
experiments are on hold during the sprint; no model calls and no model-heavy runs.

- **Safe to publish.** `make secrets-scan` is clean. Nothing under `private/` or `runs/`,
  and no `.env` file, is tracked or was ever tracked on this branch. Every email address
  in the tracked files is a reserved test address, Raj's GitHub noreply address, or a
  public organizational contact quoted in a citation record; no commit, commit message,
  or past file version on the branch holds a personal address or a secret pattern, and
  the only commit identities are Raj's noreply and Claude's noreply. The benchmark tasks
  are synthetic and use reserved domains, with no vulnerability details, vendored
  dependencies, or binaries, and no third-party datasets are used (docs/DATA.md).
- **Checks.** `make ci` (lint, typecheck, test, demo) passes on a fresh clone of the
  pushed head on Python 3.11 and 3.12 (`tools/prepush.sh`, and `PY=3.12`).
- **README.** The first screen says there is no study result yet and that its numbers
  are interim observations from an unfinished validation run; the results section says
  no manipulation effect, model comparison, or mitigation effect has been measured; the
  Status section lists which gates pass in the fast check and why the others fail.

## 2026-11-11: final push (goal_turn 4), moved from STATUS.md

Stopped 2026-11-11 at the end of Raj's final push. Origin's session branch has every
commit and the working tree is clean.

This push:

- **Public README.** The exploratory smoke result, with Wilson intervals, the headline
  figure, a report card from `make demo`, key results linked to their artifact and to the
  draft preregistrations, responsible disclosure, and the verified related work. Every
  number is bound to `artifacts/exploratory/smoke_outcomes.json` (claimcheck, freshness).
- **Exploratory smoke outcomes.** `tools/smoke_outcomes.py` reads the banked smoke runs
  and writes `artifacts/exploratory/smoke_outcomes.json` (labeled exploratory, not
  confirmatory); `src/receipts/report/spec.py` derives the registry and both figures.
- **Technical report.** `docs/REPORT.md`: the instrument, receipts-bench, agents and
  scaffold, the preregistered design, the exploratory first signal with intervals,
  integrity engineering, limitations, ethics and disclosure, and reproducibility. Every
  number is bound to an artifact and every reference is verified. Reading the banked
  reports by hand found extractor errors in both directions (missed completion
  statements; a failure admission recorded as a supported tests-pass claim); the README
  and the report both list them.
- **Python 3.12.** `make ci` failed on Python 3.12: `mypy --strict` under the NumPy 2.5
  stubs that the lock resolves there. Fixed in 7ac1494 without changing values; both
  versions now pass on a fresh clone before a push. CORRECTIONS.md has its first two
  entries (this one, and docs/HOOK.md overstating what was measured); D48 records the
  README's exploratory first screen.
- **Pre-freeze work integrated** (83926a4, cherry-picked from the integration worktree):
  D42 re-verification at banking (`receipts.study.rescore`), the E1 and E4 row contract,
  the E1 to E4 analyses, E3 sampling, the gate changes to g7, g8, g9 and
  `tools/prereg.py`, the run_study retry cap, the paired E4 plan, prereg drafts 0001 to
  0003, and the review's remaining blocking fixes (D47: a row binds exactly the code
  re-verification runs; lone surrogates; run_start checks; the exact 2 x 4 E4 plan in g9;
  E3 exclusion records in g8; dropped connections as backend errors). The parked patch
  file is gone. Left out: the hook demo, which has no recorded run that blocks on its live
  ledger yet. The integrated code has not had an independent review since its fixes.
- **Adversarial docs review** (workflow: four lenses, then a skeptic per lens): found
  overstated or wrong statements in README.md, docs/REPORT.md, and docs/HOOK.md, all checked
  against the banked runs and the code and corrected (CORRECTIONS.md). The headline caveat
  changed most: in most false successes the unvalidated extractor missed or mis-checked the
  completion statement, so "no contradicted claim" mostly measures the extractor.
- **Style fix.** The parked patch held a literal em dash, which failed the style test
  (fixed in 499026e, before the patch was integrated).

## 2026-11-04 17:00 UTC: pause (goal_turn 3), moved from STATUS.md

Paused at Raj's request (clean stop). Origin had every commit; the working tree was clean.

- **G6 smoke study:** 20 of 40 runs banked and pushed (all `py-*` tasks done; `ts-*`
  next). Restart with `PYTHONPATH=$(bash tools/snapshot_code.sh 4ae76bb) uv run
  --no-sync python tools/run_study.py --plan artifacts/studies/smoke/plan.json --port 8090
  --threads 3 --parallel 4 --request-timeout 3600` (restart-safe; banked runs are skipped).
- **Scaffold and serving fixes** (all for every arm, before any pilot or E1 run): slot
  pinning and 3 server threads (D44), lenient JSON actions with specific parse errors
  (D45), a JSON-action grammar with 1024 output tokens (D46). Three runs that had looped
  for hours then finished in 3 to 17 turns.
- **Pre-freeze work in progress, parked as a patch:**
  `docs/notes/prefreeze-wip-2026-11-04.patch` (the D42 re-verification module, new E1/E4
  rows, analysis, E3 sampling, gate changes, the run_study retry cap, the power-search
  fix, the three prereg drafts, and the hook demo). Reviewed by six lenses with 55
  confirmed findings, partly fixed; the fix stage stopped mid-way.

## 2026-10-23: bootstrap

Bootstrap (docs/BUILD_BRIEF.md section 10.1) ran in a Claude Code on the web
container started by Raj with the heartbeat `/loop` message only.

- Commits: `bootstrap` (52ff2fe), then a ship_check fix (1270e85): the first fast run
  exposed that uv warnings on stderr broke G11 and G12 parsing and that G2 matched
  `type: ignore` inside string literals. Both fixed and covered by tests.
- Fast ship-check at 1270e85: 2/14 (G2, G14 pass). All other gates fail for the
  expected reason: nothing has been built yet.
- Billing guard tripped by the runtime's `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_USE_CCR_V2`;
  no Claude children launched. No model calls of any kind were made.
- Not pushed (`ALLOW_PUSH` unset).

### 2026-11-04 morning (goal_turn 3), moved from STATUS.md

goal_turn 3. Committed since the restart (all local; nothing pushed, D28): the
independent-review fixes for claims (22 findings), bench (8), sandbox (13), and analysis
(6); all 40 benchmark tasks (4 pilot, 36 catalog), each authored, reviewed, and fixed,
passing tools/bench_validate.py; verify and ledger fixes requested by those owners.
Running: the full reference validation of all 40 tasks (G6 artifact), the pilot (slow:
the 4-core CPU is shared with the agents), the gate-harness fix (52 confirmed findings),
and the builds of the E0 tooling and the preregistered analysis scripts.

Incident, 08:12 UTC: a fixer agent's scratch command ran `git add . && git commit` in this
checkout instead of its temp directory and committed the whole working tree as
`x <a@b>` ("x", 5518a09). Nothing had been pushed; a mixed reset to the previous commit
(446efa6) removed it with every file kept, the work was recommitted in proper commits
as Raj, and a local pre-commit hook (.git/hooks, not tracked) now refuses any commit in
this checkout not authored as Raj (D26).

Pushed 2026-11-04 after `tools/prepush.sh` printed `PREPUSH: PASS make ci on fresh clone of
623cc70` (D27, D28): the branch on origin is at 623cc70. Every later push repeats that check.
The offline demo replays the banked pipeline-check run; pilot runs with reports will join it.

### 2026-11-04 weekly-limit stop, moved from STATUS.md

- 2026-11-04 about 03:55 UTC: every subagent stopped with "You've hit your weekly limit,
  resets 7am (UTC)". Per section 8, no new model work started until the reset. At 07:10
  UTC Raj said "try again": the stopped workflows (claims and bench fixes, harness
  verification, task authoring) resumed from their journals, with bulk roles (task
  authors, reviewers, finding verifiers) on Sonnet to spread plan usage. The local-model
  pilot, killed by the worker restart, restarted from a snapshot of 71db6e6 (it uses no
  plan usage). The E0-tooling and analysis-pipeline builds wait until the claims fix
  lands.
