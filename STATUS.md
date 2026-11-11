goal_turn: 4
STATE: ACTIVE

# Status

Updated 2026-11-11, goal_turn 4 (Raj's final push before the repository goes public).
History is in docs/LOG.md.

## Gates

`python tools/ship_check.py --fast` at d96b542 (fresh clone): **4/14** (FAST, does not count).

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
| G13 Documentation | PASS | README follows section 11; REPORT.md 6715 words; figures reproduce; every reference verified |
| G14 Hygiene | PASS | secrets clean; cash_usd = 0, caps respected; private/ untracked; files present; clean |

G1 fails on coverage only: `src/receipts/hook/wrap.py` (the `receipts wrap` command) has no
tests, which pulls the hook package to 78.6%; every test passes. G3 fails in fast mode only
because it requires G1 and G2; `make ci` itself passes on Python 3.11 and 3.12. G2 fails on
three `type: ignore[code]` comments without a reason inside benchmark task repositories;
adding reasons changes the task hashes that the reference validation and the banked smoke
runs cite, so that waits for the next benchmark version. G5 to G9, G11, and G12 wait on the
studies and on a review of the current code.

## Now

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

1. **Fast-forward `main` before the repository goes public.** The default branch `main`
   still holds only the brief (9e14f44). The session branch `claude/sweet-newton-r3x6t3`
   is a fast-forward of it. From a checkout: `git fetch origin && git push origin
   origin/claude/sweet-newton-r3x6t3:main`, or merge on GitHub. That push runs
   `.github/workflows/ci.yml` (`make ci` on Python 3.11 and 3.12); both pass on a fresh
   clone of the pushed head here (`tools/prepush.sh`, and `PY=3.12` for 3.12). CI has not
   run on GitHub since 2026-10-23, when it failed only because the demo was not built yet.
2. **Canary string before a dataset release (rule 9).** receipts-bench has no canary
   string yet. If a public repository counts as releasing the benchmark, a canary string
   belongs in every task file first; that changes the task hashes, so the smoke runs would
   be re-run for the new task version.
3. **Claude subject runs are disabled here (billing guard).** This runtime sets
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
- Report "false success without a contradicted claim" as a first-class outcome in E1: in
  the smoke runs many false successes contained no false sentence, so a claim-level
  checker alone would miss them.
