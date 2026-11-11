goal_turn: 6
STATE: ACTIVE

# Status

Updated 2026-11-11, goal_turn 6 (crunch time: the repository is public; Raj is away and
authorized updating `main` at each RELEASE-READY point, D49).
History is in docs/LOG.md.

## Gates

`python tools/ship_check.py --fast` at 229a14f (fresh clone): **4/14** (FAST, does not count).

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 Build and tests | FAIL | core coverage below 85%: hook 78.6% |
| G2 Static quality | FAIL | type: ignore without code and reason at bench/tasks/py-ci-workflow/repo/tests/test_commits.py:65, bench/tasks/py-email-tests/repo/src/addrcheck/validator.py:88, bench/tasks/py-email-tests/repo/tests/test_validator.py:56 |
| G3 CI parity | FAIL | fast: make ci parts (lint, typecheck, test, demo) do not all pass |
| G4 Offline demo | PASS | make demo 0s offline (unshare -rn); matches golden; no model calls |
| G5 Instrument validity | FAIL | artifacts/bench/smoke_runs.json missing |
| G6 Benchmark | FAIL | artifacts/bench/smoke_runs.json missing |
| G7 Main study | FAIL | artifacts/e1/results.json missing |
| G8 Mechanisms, judges | FAIL | artifacts/e1/runs.jsonl missing |
| G9 Mitigation | FAIL | artifacts/e4/results.json missing |
| G10 Claim integrity | PASS | make claimcheck and make freshness pass on README.md and docs/REPORT.md |
| G11 Prereg integrity | FAIL | no confirmatory artifacts cite a preregistration |
| G12 Review | FAIL | latest review is not a valid SHIP for HEAD: REVIEW: BLOCK |
| G13 Documentation | PASS | README follows section 11; REPORT.md 6992 words; figures reproduce; every reference verified |
| G14 Hygiene | PASS | secrets clean; cash_usd = 0, caps respected; private/ untracked; files present; clean |

G1 fails on coverage only: `src/receipts/hook/wrap.py` (the `receipts wrap` command) has no
tests, which keeps the hook package below the floor; every test passes. G3 fails in fast
mode only because it requires G1 and G2; `make ci` itself passes on Python 3.11 and 3.12.
G2 stops at `type: ignore[code]` comments without a reason inside benchmark task
repositories; adding reasons changes the task hashes that the reference validation and the
banked smoke runs cite, so that waits for the next benchmark version. G5 to G9, G11, and
G12 wait on the studies and on a review of the current code.

## Now

Crunch time, 2026-11-11 (goal_turn 6). `main` holds the release commit through Raj's
merge commit and the repository is public. Raj's order: G1, G2, G3, the canary string
(before any more smoke runs), the smoke runs and `smoke_runs.json` (G5, G6), E0, the E1
freeze and runs, E2 to E4, then an independent review. CAP_SHARE stays 0.2.

- **G1, receipts-hook coverage.** `receipts wrap` and the `receipts` CLI now have real
  tests (a real git workspace, a real pytest rerun through the test sandbox, real
  extraction and verification), and the bugs the docs review found are fixed (D50):
  command claims in a wrapped report are unverifiable, not contradicted, and files
  untracked before the run are no longer reported as added. Hook coverage measured on
  the hook and CLI tests alone: 98%.
- **G2, type-ignore scope.** The brief scopes G2 to the package and calls task
  repositories third-party code (section 8), so the type-ignore scan now skips
  `bench/tasks/` and nothing else (D51; a test pins the scope from both sides). The
  narrower scan then found two bare ignores in project code (`tests/evaluation/test_e3.py`),
  hidden before because the gate prints only its first findings; both now carry reasons.
- **RELEASE-READY 01f40e9**: G1, G2, G3, G4, G10, G13, G14 pass in the fast check; `main`
  and the branch both point at it (D49).
- **Canary (rule 9, D52).** Every task's `task.toml` and every answer-key file carries the
  canary string; no file the agent sees does, so the banked smoke runs stay valid runs of
  the same task. The reference validation, banked again from the canary commit 85f9b92 with
  a clean `bench/` tree, finds every task valid.
- **Smoke study restart (D53).** The remaining runs (the TypeScript catalog tasks) run from
  a snapshot of the commit that banks the validation, with the earlier arm and server
  settings; nothing in the agent scaffold changed since the earlier runs.

## Next three actions

1. Fix what the docs review found in code: `receipts wrap` labels claims about commands
   contradicted although it records none (they should be unverifiable), and its start
   state leaves out untracked files; add tests for the wrapper and the `receipts` CLI
   (this also lifts G1's hook coverage); flag action claims in a Stop-hook session that
   made no tool call. Then review the integrated pre-freeze work and close its open items:
   the E0 verifier mode (`e0.predict` passes requirement texts; `seeded_eval.json` records
   the mode; analyses and g7/g9 check it); DECISIONS entries for the prereg and E1
   fixers' interpretations; g9 re-deriving Z1 and checking E4 runs against the freeze
   commit; g7 re-deriving verdicts and checking identical E1 cells; g8 checking K;
   repeated plan run ids; the trailing word boundary in g7/g9's plan patterns;
   `prereg.py freeze` refusing unparsable machine-readable lines; E4 banking-code list;
   the E3 failure log, shared-text stratum, and condition 8; the none and hook arms
   sharing a response cache key; snapshot contents checked against their commit.
2. Finish the smoke study (the 20 `ts-*` runs left), bank `smoke_runs.json` (G6), run the
   E0 labelers, writers, and adjudicators (D40, D43), and score the held-out split (G5).
3. Pilot, power run, E1/E4 plans, fill the TO FIX fields, review, freeze 0001 to 0003, and
   launch E1 from the freeze-commit snapshot (`runs/launch-study.sh` semantics).

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

## Usage to date

cash_usd = 0. cap_share 0.2 (D20). Claude children: 0 agent runs, 0 single calls, 0
review runs (billing guard, D4). Local-model calls are logged in
`artifacts/usage/ledger.jsonl` (`make budget` summarizes them). Pipeline work uses Claude
Code subagents in this session (plan usage; bulk roles on Sonnet). No model calls were
made in this push.

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
- Measure the extractor's recall on completion statements ("the feature is done") in E0
  and report it beside Y1: in the smoke runs, most false successes had no contradicted
  claim because the extractor missed or mis-checked the completion statement, so a
  claim-level checker is only as good as its extraction.
