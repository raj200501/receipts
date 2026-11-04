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

Paused 2026-11-04 17:00 UTC at Raj's request (clean stop). Origin has every commit; the
working tree is clean.

- **G6 smoke study:** 20 of 40 runs banked and pushed (all `py-*` tasks done; `ts-*` next).
  Restart with `PYTHONPATH=$(bash tools/snapshot_code.sh 4ae76bb) uv run --no-sync python
  tools/run_study.py --plan artifacts/studies/smoke/plan.json --port 8090 --threads 3
  --parallel 4 --request-timeout 3600` (restart-safe; banked runs are skipped).
- **Scaffold and serving fixes this session** (all for every arm, before any pilot or E1
  run): slot pinning and 3 server threads (D44), lenient JSON actions with specific parse
  errors (D45), a JSON-action grammar with 1024 output tokens (D46). Three runs that had
  looped for hours then finished in 3 to 17 turns.
- **Pre-freeze work in progress, parked as a patch:** `docs/notes/prefreeze-wip-2026-11-04.patch`
  (`git apply` it; it applies cleanly to HEAD). It holds the D42 re-verification module
  (`src/receipts/study/rescore.py`), new E1/E4 rows, analysis, E3 sampling, gate changes,
  the run_study retry cap, the power-search fix, the three prereg drafts (0003 is new),
  and the hook demo. Reviewed by six lenses with 55 confirmed findings, partly fixed;
  the fix stage stopped mid-way, so the patch is unverified (tests may fail).

## Next three actions

1. Apply the patch, finish the fix stage (banking: instrument record binds claims,
   verify, ledger only; e3, e4-analysis, gates fixers), then run `make ci` and push.
2. Finish the smoke study, bank `smoke_runs.json`, run the E0 labelers, writers, and
   adjudicators (workflow drafts in the session notes, D40, D43), and the pilot.
3. Power run, E1/E4 plans, fill TO FIX fields, review, freeze 0001 to 0003, launch E1 with
   `runs/launch-study.sh` semantics (freeze-commit snapshot).

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

cash_usd = 0. cap_share 0.2 (D20). Claude children: 0 agent runs, 0 single calls, 0
review runs (billing guard, D4). Local-model calls are logged in
`artifacts/usage/ledger.jsonl` (`make budget` summarizes them). Pipeline work uses Claude
Code subagents in this session (plan usage; bulk roles on Sonnet).

## Needs Raj

1. **Claude subject runs are disabled here (billing guard).** This runtime sets
   `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_USE_CCR_V2`, which section 8 treats as possible
   per-token billing, so no `claude -p` child is launched (D4). E1 and E4 therefore use
   four local minimal-agent arms (D25), which meets G7's "3 configurations, 2 families",
   but the brief's Claude tiers and the Claude scaffold-crossing arm are missing; prereg
   0001 section 2 records this as a deviation. To add them: run the build on a machine
   where `claude` is logged in to your Max plan and
   `env | grep -E '^(ANTHROPIC_|CLAUDE_CODE_USE_)'` prints nothing; Claude arms then get
   their own preregistration before their data exists.

## Blocked

Nothing blocked right now.

## Backlog (suggestions for Raj, not ladder rungs)

- Publish the claim-type taxonomy and verifier as a small standalone spec so other agent
  CLIs can emit evidence-linked reports that receipts can check without a ledger adapter.
