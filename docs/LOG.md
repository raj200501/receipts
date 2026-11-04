# Log

History moved out of STATUS.md, newest first.

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
