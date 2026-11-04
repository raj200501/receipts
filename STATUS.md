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

goal_turn 3, 2026-11-04 11:40 UTC. Pushed through e9fc3bc (prepush PASS, D28); later
commits are local until the next prepush.

- **G6 smoke study** (one unmanipulated `ma-qwen7b` run per task, seed 0) is running from a
  code snapshot of e9fc3bc with the D39 scaffold (16 turns, then one final-report
  request): 8 of 40 banked and committed, 4 in flight, about 12 runs an hour.
  `runs/chain-pilot.sh` starts the pilot (32 runs, `pilot-*` tasks only) the moment the
  smoke study exits with all 40 banked.
- **E1 sample size:** `tools/power_e1.py` (committed) implements the prereg 0001 section 8
  rule; it runs on the banked pilot and writes `artifacts/power/e1_power.json`.
- **Preregistrations:** an agent is folding the two code owners' gap lists into prereg
  0001 (E1, E2) and 0002 (E4) and drafting 0003 (E3 judges). I review the text before the
  freeze; the freeze waits for the pilot and the power run.
- **E0:** the blind-label claim-type counting (D34) is being built and reviewed; the writer,
  adjudicator, and labeler runs start once every smoke run is banked. Smoke reports are
  short (zero to four claims each), so the writer volume needs a decision (next actions).
- **G9:** an agent is writing the scripted hook demo (`tools/hook_demo.py`); hook latency is
  measured on the smoke runs once all are banked.

## Next three actions

1. When the smoke study is complete: bank `smoke_runs.json` (G6), build the E0 writer
   packets, run the blind labelers for the claim-type counts and the writer and
   adjudicator subagents (D40 sets the volume), then split and commit the held-out
   manifest.
2. When the pilot is banked: run `tools/power_e1.py`, write the E1 and E4 plans, fill the
   TO FIX fields, review, and freeze prereg 0001, 0002, and 0003 together before any E1 run.
3. Integrate the blind-label tooling and the hook demo, run `tools/prepush.sh`, push.

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
