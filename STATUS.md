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

Final sprint, 2026-11-12 (goal_turn 6). Raj gave one more hour for the gates, then the
finale: finalize and update `main`. Not all fourteen gates were reachable in that hour: G6
waits on the smoke runs not yet banked (each takes 30 to 60 minutes on this CPU-only
container), and G5, G7 to G9, and G11 wait on E0 and the studies, which take days of
local-model compute here.

- **On `main`: 02bc774** (RELEASE-READY), after `make ci` on fresh clones for Python 3.11
  and 3.12 and fresh-clone `make claimcheck`, `freshness`, `citecheck`, `secrets-scan`,
  and `budget`. It holds every fix below.
- **Independent review of 02bc774: REVIEW: BLOCK**, banked with this update. It confirms
  B1 to B4 of the previous review fixed and every bound number equal to its own
  recomputation from the 31 run records. Two new gate holes block, both latent because no
  E0 to E4 data exist yet: **B5**, G7 to G10 never re-derive the E1 to E4 result
  artifacts, so hand-set E2 classes, E3 counts, or E1 and E4 test results would pass;
  **B6**, G5 takes the recorded held-out predictions on trust instead of re-running the
  scoring, and reads neither the held-out attempt log nor the requirement digests.
  Non-blocking N2, N13, and N17 to N23 are in docs/REVIEW_LOG.md.
- **Review of e4230cc (BLOCK, B1 to B4, N1 to N16):** every finding is fixed (D56 to D59).
  Three adversarial workflows then checked the fixes; their confirmed findings led to the
  revert of the D60 extractor change before any E0 scoring (D61), immutable banked runs
  (D62), unforgeable `bank_study --check` and run-record inputs (D63), and G5, G8, and G13
  reading only committed directories and visible prose (D64).
- **Smoke study (D53):** 31 of the 40 runs are banked; the rest, nearly all TypeScript,
  keep running from the e4230cc snapshot, four at a time. Each banking commit re-derives
  the summary and the README and REPORT numbers (D56).
- **Open, non-blocking, from the adversarial checks:** G5 reports `unparsed_actions` as
  one total for two causes; several G7 and G9 tests assert only a
  headline that any failure produces; G9 lacks G7's accounting of planned runs that were
  never banked; the ledger writer leaves U+2028, U+2029, and U+0085 unescaped; prereg
  0002's "Z1 over every banked run" has no code yet. None affects a reported number.

## Next three actions

1. Bank the remaining smoke runs as they finish, then `smoke_runs.json` (G6); run the E0
   labelers, writers, and adjudicators (D40, D43) and score the held-out split (G5).
2. Pilot, power run, E1 and E4 plans, fill the TO FIX fields, freeze 0001 to 0003, and
   launch E1 and E4 from the freeze-commit snapshot (G7 to G9, G11).
3. Fix B5 (G7 to G10 re-derive the E1 to E4 result artifacts from their banked inputs)
   and B6 (G5 re-runs the held-out scoring in the clone, reads `heldout_attempts.jsonl`,
   and checks the requirement digests), with tests; then N18 and N19 before any E1 run;
   the next independent review when the daily cap allows (G12).

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
