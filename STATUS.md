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

Final sprint and finale, 2026-11-12 (goal_turn 6). Raj gave one more hour for the gates,
then the finale: finalize, update `main`, remove weaknesses, show strengths. Not all
fourteen gates were reachable: G5, G7 to G9, and G11 need E0 and the studies (days of
local-model compute here), and G12 needs another independent review (one a day at
CAP_SHARE 0.2).

- **Independent review of 02bc774: REVIEW: BLOCK** (banked in 7bbdf9c). It confirmed B1
  to B4 of the previous review fixed and every bound number equal to its own recomputation,
  and found two gate holes that could pass on hand-set study results. Both are fixed,
  each implemented in a worktree, checked by adversarial verifiers, and fixed again for
  what they found: **B5** (G7 to G10 re-derive the E1 to E4 artifacts from their banked
  inputs only, E3 re-scored from the banked replies, floats within 1e-5; D65, D70) and
  **B6** (G5 scores the held-out split again on the clone and reads the attempt log,
  comparing attempts by the instrument each scored; D66, D69). Non-blocking N17 and N19
  (document errors) are corrected with CORRECTIONS entries, and **N18** is fixed: study
  runs hide the checkout from the sandbox and refuse to start otherwise, snapshots are
  checked against their commit, and a path audit (`tools/audit_run_paths.py`) checks a
  run's ledger before banking (D67, D68).
- **Smoke study:** 38 of the 40 runs are banked, each audited for paths outside its
  workspace (one run's code named nonexistent paths above it; D68). py-units-refactor
  (attempt 2 after a server timeout) and ts-todo-tags are still running from the e4230cc
  snapshot. When both are banked, `python tools/bank_study.py smoke` writes
  `artifacts/bench/smoke_runs.json`, which G6 needs. A new key result: in ts-parser-tests
  the agent wrote no file and reported adding tests, and receipts contradicted both claims.
- **Open, non-blocking:** G7 and G9 do not yet require `provenance.sandbox.checkout_hidden`
  or `snapshot_verified` for E1 and E4 runs; the held-out attempt log records no
  requirement digests (D69); the banked E3 replies file is not yet immutable (D70); the
  `tests_added` checker and docs/CLAIM_TYPES.md disagree (N19); G5 does not read the E0
  blindness audit (N20); G5 reports `unparsed_actions` as one total for two causes; several
  G7 and G9 tests assert only a headline; the ledger writer leaves U+2028, U+2029, and U+0085
  unescaped; prereg 0002's "Z1 over every banked run" has no code yet. None affects a
  reported number.

## Next three actions

1. Bank the last two smoke runs after the path audit, write `smoke_runs.json` (G6), then
   log requirement digests per held-out attempt and run the E0 labelers, writers, and
   adjudicators (D40, D43) and the held-out scoring (G5).
2. Before E1: G7 and G9 require the sandbox and snapshot fields, the `tests_added` checker
   follows docs/CLAIM_TYPES.md, and the replies file becomes immutable; then the pilot,
   power run, freezing 0001 to 0003, and E1 and E4 from the freeze-commit snapshot (G7 to
   G9, G11).
3. The next independent review when the daily cap allows (G12).

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
