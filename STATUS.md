goal_turn: 3
STATE: ACTIVE

# Status

Updated 2026-11-04, goal_turn 3 (Raj cleared /goal and said continue). History is in docs/LOG.md.

## Gates

`python tools/ship_check.py --fast` at 1270e85 (fresh clone): **2/14** (FAST, does not count).

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 Build and tests | FAIL | core modules missing: ledger, claims, verify, analysis, hook |
| G2 Static quality | PASS | ruff check, ruff format --check, mypy --strict clean |
| G3 CI parity | FAIL | make ci parts do not all pass (demo not built) |
| G4 Offline demo | FAIL | make demo not built yet |
| G5 Instrument validity | FAIL | artifacts/e0/claim_type_counts.json missing |
| G6 Benchmark | FAIL | 0 tasks of 30 |
| G7 Main study | FAIL | artifacts/e1/results.json missing |
| G8 Mechanisms, judges | FAIL | artifacts/e1/runs.jsonl missing |
| G9 Mitigation | FAIL | artifacts/e4/results.json missing |
| G10 Claim integrity | FAIL | docs/REPORT.md missing |
| G11 Prereg integrity | FAIL | no confirmatory artifacts yet |
| G12 Review | FAIL | no review yet |
| G13 Documentation | FAIL | README.md is still the build brief |
| G14 Hygiene | PASS | secrets clean; cash_usd = 0; private/ untracked; files present; clean tree |

## Now

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

## Next three actions

1. Integrate claims, analysis, sandbox, and bench; fix every confirmed gate-harness finding.
2. Launch the task-authoring workflows over docs/BENCH_CATALOG.md (G6) and run the pilot on
   the `pilot-*` tasks; record two pilot runs as demo fixtures, write the golden output,
   get `make ci` green, push.
3. Smoke runs on every task (G6), claim-type counts, then E0 seeded reports (G5) and the
   frozen preregistrations (G11) before any E1 run.

## Environment (`make doctor`, 2026-10-23)

- Linux x86_64 cloud container (Claude Code on the web); RAM 15.7 GB; 4 CPUs; no GPU;
  about 21 GB free disk after model downloads (floor 8 GB)
- Python 3.11 and 3.12 (venv on 3.11); uv 0.11.32; git 2.43; node 22, npm 10
- Sandbox: bubblewrap 0.9.0 works (installed from apt); Docker daemon starts with
  `dockerd --iptables=false` and `docker run --network none` works; `unshare -rn` works (D22)
- Local models: llama-cpp-python 0.3.36 server in /opt/receipts-llm; pinned GGUF files
  Qwen2.5-Coder-7B-Instruct q4_k_m and Granite 3.3 8B Instruct Q4_K_M, hash-verified (D23);
  throughput banked in `artifacts/env/local_throughput_qwen2.5-coder-7b-instruct-q4km.json`
- claude 2.1.309 installed but unusable: billing guard tripped by `ANTHROPIC_BASE_URL`,
  `CLAUDE_CODE_USE_CCR_V2` (D4)
- Usable backends: local=yes (llama-cpp-python), claude=no, free_tier=no
- `tools/provision.sh` recreates this environment in a fresh container
- 2026-11-04: the container survived the pause (models, venvs, bubblewrap intact); the
  Docker daemon was restarted and `docker run --network none` works again

## Usage to date

cash_usd = 0. cap_share 0.2 (D20). Claude agent runs 0, single calls 0, review runs 0.
Local model runs 0.
Subagent use: none yet.

## Needs Raj

1. **Claude subject runs are disabled here (billing guard).** This runtime sets
   `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_USE_CCR_V2`, which section 8 treats as possible
   per-token billing. E1 needs at least two Claude tiers as subjects, so G7 to G9 cannot
   finish here. Action: run the build on a machine where `claude` is logged in to your Max
   plan and `env | grep -E '^(ANTHROPIC_|CLAUDE_CODE_USE_)'` prints nothing (section 0 step 4).
   Work that needs no Claude children (M1 to M4 with local models) continues meanwhile.

## Blocked

- 2026-11-04 about 03:55 UTC: every subagent stopped with "You've hit your weekly limit,
  resets 7am (UTC)". Per section 8, no new model work started until the reset. At 07:10
  UTC Raj said "try again": the stopped workflows (claims and bench fixes, harness
  verification, task authoring) resumed from their journals, with bulk roles (task
  authors, reviewers, finding verifiers) on Sonnet to spread plan usage. The local-model
  pilot, killed by the worker restart, restarted from a snapshot of 71db6e6 (it uses no
  plan usage). The E0-tooling and analysis-pipeline builds wait until the claims fix
  lands.

## Backlog (suggestions for Raj, not ladder rungs)

- Publish the claim-type taxonomy and verifier as a small standalone spec so other agent
  CLIs can emit evidence-linked reports that receipts can check without a ledger adapter.
