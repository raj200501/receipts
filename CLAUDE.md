# CLAUDE.md

After any compaction or restart, re-read CLAUDE.md, STATUS.md, and sections 6 to 10 of docs/BUILD_BRIEF.md before acting.

## Mission

receipts checks every atomic claim in an AI coding agent's final report against a
ground-truth event ledger of what actually happened in its sandbox (commands, exit
codes, test results, diffs, timing), labels each claim supported, contradicted, or
unverifiable with evidence attached, measures in a preregistered randomized study
across agents and model tiers how often and why reports go wrong (confusion versus
overclaiming), and ships receipts-hook, a Claude Code Stop hook and CLI wrapper that
flags unsupported claims live, with its effect measured. The build brief is
docs/BUILD_BRIEF.md (immutable; its SHA-256 is in docs/BUILD_BRIEF.sha256).

## Non-negotiables (docs/BUILD_BRIEF.md section 9, verbatim)

1. **No fabricated or hand-typed numbers.** Every result number (a measured rate, count of outcomes, estimate, interval, or test statistic) in README.md, docs/REPORT.md, other results documents, figures, and tables is produced by a committed script from a banked artifact under `artifacts/`. Design parameters, thresholds, caps, dates, versions, and the text of docs/BUILD_BRIEF.md are not result numbers. `make claimcheck` enforces this and `make freshness` re-derives every live number.
2. **Preregister before confirmatory runs.** Hypotheses, metrics, analysis plan, thresholds, sample sizes, exclusions, and stopping rules go in `prereg/NNNN-*.md`, committed and hashed before any confirmatory data exists. A needed change is a new, dated amendment file that cites the original, is committed before any data it affects, and is reported as a deviation; the original is never edited. Anything not preregistered is labeled exploratory.
3. **Publish failures beside successes.** Null and negative results get the same prominence as positive ones. Every changed or withdrawn claim gets a dated entry in CORRECTIONS.md.
4. **Label synthetic and mock data everywhere.** Synthetic, procedurally generated, or mock results are never presented as model results or real-world results.
5. **$0 cash, with caps enforced in code** (section 8).
6. **Secrets stay in the environment.** Never write keys or tokens to files, logs, artifacts, or command lines. `make secrets-scan` runs in CI and in ship-check.
7. **Defensive scope only.** Mock tools and disposable sandboxes. No real credentials, real systems, or harmful payloads. Build nothing that helps an agent evade graders, monitors, or safety measures beyond what the measurement strictly requires.
8. **No outbound actions.** Never send email, open issues or pull requests, post, publish packages, datasets, or sites, or contact anyone. Pushing is allowed only under section 10.1 step 11. Prepare drafts in `outbound/` for Raj to review and send.
9. **Respect licenses and terms.** Record the source, license, and retrieval date of all third-party data in docs/DATA.md. Do not redistribute what a license does not allow. Add a canary string to any dataset meant for release.
10. **The brief is immutable.** Never edit docs/BUILD_BRIEF.md. Record deviations, substitutions, and interpretations in DECISIONS.md, with a reason, before acting on them.
11. **Verified citations only.** Never cite from memory. Open and check every reference (title, authors, year, URL) once and bank what you saw in `artifacts/citecheck.json` (retrieval date, final URL, page title, content hash); `make citecheck` validates that file offline, so ship-check never needs the network. If a site blocks scripted access, use the arXiv, DOI, or another official copy, and never work around bot protection. If nothing opens, drop the reference and list it under "Needs Raj" for a manual check.
12. **Plain writing.** Precise, scoped claims. No hype words such as "revolutionary", "groundbreaking", or "state of the art". No em dashes anywhere (Raj's style rule).
13. **Honest progress.** Never pass a gate by weakening its check. If a gate cannot pass, say so in STATUS.md and keep working on what can.
14. **Measure, never induce.** Manipulations are realistic situations (an unattainable requirement, truncated output, time pressure, flaky tools). Never instruct, train, or reward an agent to misreport.
15. **Transcripts stay local.** Any real-world transcript, including Raj's own, is analyzed locally and never committed or uploaded. Only aggregates are committed.

## State files

- `STATUS.md`: line 1 `goal_turn: N`, line 2 `STATE: ACTIVE | BLOCKED ON RAJ | LADDER COMPLETE`;
  gate table, Now, next three actions, usage to date, Needs Raj, Blocked, backlog. Under 200 lines.
- `docs/LOG.md`: history moved out of STATUS.md.
- `DECISIONS.md`: interpretations, substitutions, deviations, each with a reason, written before acting.
- `CORRECTIONS.md`: dated entry for every changed or withdrawn claim.
- `docs/PLAN.md`: milestones mapped to gates, risks, fallbacks, usage estimates, artifact contract.
- `docs/REVIEW_LOG.md`: non-blocking review issues.
- `budget.toml`: caps (lower only, never raise). `artifacts/usage/ledger.jsonl`: every model call.
- `prereg/`: frozen preregistrations and `prereg/LOCK.json` hash chain.
- `artifacts/`: banked results with provenance. `artifacts/review/latest.json` is written only by
  the reviewer (headless run or `reviewer` subagent), never by the main session.
- `outbound/`: drafts for Raj. `private/` and `runs/` are git-ignored and never committed.
- `.claude/loop.md`: heartbeat prompt. `.claude/agents/`: `reviewer`, `citation-checker`.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | `uv sync --locked` (Python 3.11 by default, `PY=3.12` to switch) |
| `make doctor` | detect Docker, GPU, RAM, disk, claude CLI and login, Ollama, sandboxes, free tiers |
| `make test` | pytest with coverage |
| `make lint` | `ruff check` and `ruff format --check` |
| `make typecheck` | `mypy --strict` |
| `make ci` | lint, typecheck, test, offline demo (what CI runs on 3.11 and 3.12) |
| `make demo` | offline demo from recorded fixtures, compared with its golden output |
| `make prereg-verify` | preregistration chain and confirmatory-artifact ancestry |
| `make claimcheck` | every number in README.md and docs/REPORT.md is bound to an artifact |
| `make freshness` | re-derive every live number from artifacts |
| `make citecheck` | offline validation of `artifacts/citecheck.json` |
| `make secrets-scan` | scan tracked files for secrets |
| `make budget` | caps versus the brief, usage ledger versus caps, `cash_usd = 0` |
| `make review` | adversarial review; prints `REVIEW: SHIP` or `REVIEW: BLOCK` |
| `make report` | figures, tables, and the numbers registry from artifacts |
| `make reproduce` | rebuild every figure and number from banked artifacts |
| `make ship-check` | `python tools/ship_check.py`: G1 to G14 on a fresh clone of HEAD |
| `python tools/ship_check.py --fast` | quick check; last line `SHIP-CHECK-FAST (does not count)` |

## Working rules

- One Loop Protocol iteration per heartbeat (section 10.2). Failing gate on the critical path
  first; after 14/14, the next Stretch Ladder rung (section 7).
- Push only if `ALLOW_PUSH=1` is set, only to `origin`, never force, never tags.
- Never launch a Claude child while `python -m receipts.guard` reports a problem.
- At most one model-heavy background run at a time, with a PID file and log under `runs/<id>/`.
