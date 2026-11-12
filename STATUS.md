goal_turn: 6
STATE: ACTIVE

# Status

Updated 2026-11-12, goal_turn 6 (crunch time: the repository is public; Raj is away and
authorized updating `main` at each RELEASE-READY point, D49).
History is in docs/LOG.md.

## Gates

`python tools/ship_check.py --fast` at 8692254 (fresh clone): **7/14** (FAST, does not count).

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 Build and tests | PASS | setup ok; tests pass; coverage 99.4%, every core module >= 85% |
| G2 Static quality | PASS | ruff check, ruff format --check, mypy --strict clean on every package file; every type: ignore in project code has a code and reason (D51) |
| G3 CI parity | PASS | workflow ok; fast: make ci not re-run, its parts pass in G1, G2, G4 |
| G4 Offline demo | PASS | make demo 0s offline (unshare -rn); matches golden; no model calls |
| G5 Instrument validity | FAIL | artifacts/bench/smoke_runs.json missing |
| G6 Benchmark | FAIL | artifacts/bench/smoke_runs.json missing |
| G7 Main study | FAIL | artifacts/e1/results.json missing |
| G8 Mechanisms, judges | FAIL | artifacts/e1/runs.jsonl missing |
| G9 Mitigation | FAIL | artifacts/e4/results.json missing |
| G10 Claim integrity | PASS | make claimcheck and make freshness pass on README.md and docs/REPORT.md |
| G11 Prereg integrity | FAIL | no confirmatory artifacts cite a preregistration |
| G12 Review | FAIL | latest review is not a valid SHIP for HEAD: REVIEW: BLOCK |
| G13 Documentation | PASS | README follows section 11; REPORT.md 7063 words; figures reproduce; every reference verified |
| G14 Hygiene | PASS | secrets clean; cash_usd = 0, caps respected; private/ untracked; files present; clean |

G1 to G4, G10, G13, and G14 pass. G5 and G6 wait on the smoke study, whose banked runs
give `smoke_runs.json`, and then on E0; G7 to G9 and G11 wait on the studies; G12 waits on
an independent review that approves the current code (the review of e4230cc blocked, B1 to
B4).

## Now

Crunch time, 2026-11-11 (goal_turn 6). `main` holds the release commits and the repository
is public. Raj's order: G1, G2, G3, the canary string, the smoke runs and
`smoke_runs.json` (G5, G6), E0, the E1 freeze and runs, E2 to E4, then an independent
review. CAP_SHARE stays 0.2.

- **Done:** G1 (real tests for `receipts wrap` and the CLI, D50), G2 (the type-ignore scan
  skips the synthetic task content under `bench/tasks/`, D51 and D55; the gate passed by
  that narrowing), G3 on Python 3.11 and 3.12, and the canary string (D52) in every task
  definition and every answer-key file with a comment syntax (JSON answer-key files carry
  none; no file the agent sees does). RELEASE-READY points since: 01f40e9, b3f48b2, and
  7d1d0f0, each with `main` updated (D49).
- **Review of e4230cc: REVIEW: BLOCK** (banked in 2cf2cef). Its documentation findings (B4,
  N1, N3, N7, N9 to N16) are fixed in e8ee5de, with CORRECTIONS entries. B1 and N4 are
  fixed next (D56): `make freshness` and `make reproduce` re-derive the smoke summary from
  the banked run records, and the summary carries the models, config hashes, seeds, and
  usage of its runs, with the environment that derived it. B3, N5, and N16 are fixed after that (D58): G8
  counts E2 and E3 as reported only when their REPORT.md sections bind numbers from their
  artifacts and name every judge; G5 re-derives every ledger-completeness row on the
  clone; G13 requires each README key result to link its artifact and preregistration.
  B2 and N6 are fixed in 6eddbef (D57, merged in 310bd95): G7 and G9 require one row per
  banked run, re-derive ground truth from each ledger, and run `tools/bank_study.py
  <study> --check` on the clone; G9 checks each E4 run's code. N8 (D59): new study runs
  carry the canary. Every review finding is now addressed; three adversarial workflows
  are checking these fixes before the next push.
- **Extractor (D60)**, merged in 6fde5bd: the pattern extractor reads the completion
  statements found in the smoke reports (for example "has been successfully added",
  "now uses"), with precision guards, before any E0 material exists. The smoke numbers
  keep the run-time verdicts; the demo report card now shows the bizdays completion
  sentence contradicted.
- **Fresh-clone `make ci` caught a regression** in 8094d0a: the analyze-to-G7 contract
  test banked ledgers without hidden-check results, which the new G7 requires. Fixed in
  f3430d9; nothing after 7d1d0f0 is pushed until `make ci` passes on both Pythons.
- **E0 verifier mode (D54)**, merged in 8692254: the held-out scoring verifies each seeded
  report with its task's requirement texts and records `verifier_mode`; `valid_types`,
  G5, and the G7/G9 instrument check refuse any other evaluation.
- **Smoke study (D53):** the remaining runs run from a snapshot of e4230cc, with the
  earlier arm and server settings, four at a time. Each commit that banks finished runs
  also re-derives the smoke summary and the README and REPORT numbers (freshness checks
  it, D56); the runs hand-read so far are noted in the README's Limitations.

- **Adversarial checks of 2026-11-12.** Fixed: banked runs are immutable (D62), `bank_study
  --check` keeps instrument fields apart and run records list untracked files (D63), the
  document errors (CORRECTIONS), and the D60 extractor change is reverted (D61). Still open:
  the E2 and E3 artifacts that G8 requires the report to bind are not re-derived (no E2 or
  E3 data exist yet); G5 reports `unparsed_actions` as one total for two different causes;
  several G7 and G9 tests assert only a headline that any failure produces; the D60
  phrasing families wait for a revision with precision guards.

## Next three actions

1. Merge the G7/G9 fix (B2, N6) after reading its diff adversarially, then run `make ci`
   on fresh clones for both Pythons and update `main` (D49).
2. Finish the smoke study, bank its runs and `smoke_runs.json` (G6), update the README
   numbers from the new `smoke_outcomes.json`, then run the E0 labelers, writers, and
   adjudicators (D40, D43) and score the held-out split (G5).
3. Pilot, power run, E1/E4 plans, fill the TO FIX fields, freeze 0001 to 0003, and launch
   E1 from the freeze-commit snapshot; the next independent review when the daily cap
   allows.

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
Code subagents in this session (plan usage; bulk roles on Sonnet). The smoke study's
local-model calls are in the usage ledger; no Claude model has been a study subject.

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
