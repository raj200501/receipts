# Decisions

Interpretations, substitutions, and deviations, each with a reason, recorded before
acting on them (rule 10). Newest last.

## 2026-10-23 (bootstrap)

**D1. goal_turn starts at 0.** Raj started this session with the message-1 heartbeat
only; no `/goal` turn has run. Bootstrap is recorded as goal_turn 0 so the first `/goal`
turn becomes 1.

**D2. Heartbeat schedule.** The heartbeat is a session-only recurring task (CronCreate,
delivered back into this same session) at minutes 7 and 37 of every hour: the same
30-minute cadence, off the :00 and :30 marks as the scheduler recommends. No scheduler
that starts a separate session per firing is used (section 0.1).

**D3. No push.** `ALLOW_PUSH` is not set, so commits stay local (section 10.1 step 11,
rule 8), even though the cloud harness names a session branch to push to. This
container is ephemeral, so the risk that unpushed work is lost is listed under Needs Raj.

**D4. Claude backend disabled by the billing guard.** The Claude Code on the web runtime
sets `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_USE_CCR_V2`. Section 8 says the wrapper refuses
to launch Claude children while either is present, so `make doctor` marks Claude unusable
and does not run `claude auth status` (its answer could not change the verdict). No
Claude child (subject, judge, extractor, or headless review) is launched here. Small
pipeline jobs use Claude Code subagents, which section 8 allows; `make review` uses the
`reviewer` subagent.

**D5. Sandbox fallback.** No Docker daemon and no bubblewrap. The local sandbox is
`unshare -rn` (user and network namespaces, verified working) plus a scrubbed environment
(`GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`, cloud credentials, and every API key or
token removed; `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`), rlimits, and a
temporary workspace. It does not confine filesystem writes, so until bubblewrap or Docker
works, only this project's own generated tasks run in it (section 8). M1 will try to
install bubblewrap and record the result here.

**D6. G1 core modules.** "Core modules" means the section 4 components `ledger`,
`claims`, `verify`, `analysis`, and `hook` (as subpackages or modules of `receipts`).
Each must exist and reach 85% line coverage on its own, and the whole package must reach
85%. Coverage omissions are allowed only for files with a recorded-fixture contract test
at `tests/contract/test_<stem>.py`. This is at least as strict as the gate text.

**D7. G5 metric.** Per claim type, end to end (extractor plus verifier): precision =
claims whose predicted verdict equals the gold verdict / claims the pipeline produced a
verdict for; recall = the same correct count / gold claims. Missed extractions count
against recall and spurious ones against precision. Thresholds apply to point estimates;
Wilson 95% intervals are printed. The five most common claim types are counted on the
real G6 smoke-run reports. The held-out half is frozen by a committed hash manifest whose
first commit must strictly precede the evaluation's first commit.

**D8. G11 is never vacuous.** `make prereg-verify` passes trivially when no confirmatory
artifact exists, so ship_check also requires at least one confirmatory artifact citing a
frozen preregistration. The confirmatory artifact's first commit must be a strict
descendant of the freeze commit (git ancestry, not timestamps).

**D9. G4 offline enforcement.** ship_check runs `make demo` inside `unshare -rn` (falling
back to a dead proxy when namespaces are unavailable) with `RECEIPTS_OFFLINE=1`, compares
`tools/demo.py` stdout with `tests/golden/demo_output.txt` itself rather than trusting
`--check`, and requires the usage ledger to be unchanged.

**D10. G12 review drift and the review log.** The reviewed commit may differ from HEAD
only in `artifacts/review/`, STATUS.md, and docs/LOG.md (section 10.1 step 8). Because
docs/REVIEW_LOG.md is not in that list, every non-blocking issue in the latest review must
already be listed there. The reviewer reuses existing issue IDs, so a review of unchanged
code converges. When a final-sequence review raises a new non-blocking issue, the next
turn logs it and the final sequence runs again.

**D11. claimcheck syntax.** Result numbers are written as `<!--n:key-->value<!--/n-->`
and bound to `artifacts/report/numbers.json`, which records each value's source artifact
and hash. Other numbers must be identifiers, dates, versions, section or list numbers, or
phrases in `docs/claimcheck_allow.txt` with a written reason. A document byte-identical
to docs/BUILD_BRIEF.md is exempt (rule 1: the brief's text is not result numbers).

**D12. citecheck scope.** Every external URL in README.md and docs/REPORT.md is treated
as a reference and needs a verified entry in `artifacts/citecheck.json`; links to this
repository are not references.

**D13. Honest stubs.** `make demo`, `make report`, and `make reproduce` exist from day one
(section 10.1 step 7) and exit 1 with "not built yet" until built, so no gate can pass
on them.

**D14. Python versions.** The local and ship-check environment uses Python 3.11 (the
lowest supported version, `make setup PY=3.11`); CI covers 3.11 and 3.12.

**D15. apiKeyHelper detection.** The guard reads Claude Code settings files only to test
whether the `apiKeyHelper` key is present; it never prints or stores a value. An
unreadable settings file fails closed.

**D16. ship_check --fast.** Fast mode uses the same fresh clone and the same checks, but
does not re-run `make ci` (G3 then requires its parts to pass in G1, G2, and G4) and
deselects tests marked `slow`. Only a full run counts.

**D17. G9 latency sample size.** "Measured latency" requires at least 20 recorded samples
so the median is meaningful; the median must be under 5 seconds (section 4).

**D18. G13 first screen.** "First screen" is the first 60 lines of README.md.

## 2026-10-23 (goal_turn 1)

**D19. Raj's launch settings: ALLOW_PUSH=1.** Raj's `/goal` message states his launch
settings for this Claude Code on the web session and says to treat them as set:
`ALLOW_PUSH=1`, so every commit is pushed to this session's working branch
(`claude/sweet-newton-r3x6t3`) on `origin`, never force-pushed, never with tags, and
without touching repository settings. This supersedes D3. The settings are recorded in
`launch.toml` because the runtime does not expose them as environment variables.

**D20. Raj's launch settings: CAP_SHARE=0.2.** Five projects share one Max plan. The
effective share is the stricter of the `CAP_SHARE` environment variable and
`launch.toml` `cap_share = 0.2`, applied by `receipts.budget.effective_cap_share` and
shown by `make budget`. Every `claude_*` cap is multiplied by it (section 8), giving
per day 6 agent runs, 60 single calls, 1 review run, and 8 turns per headless run.
These only matter once the billing guard clears (D4).

**D21. Parallel work ("ultracode").** Raj asked for parallel subagent workflows for
independent work with one owner per gate and no two agents editing the same file at
once. Each workflow agent gets an explicit list of files and directories it owns, may
read anything, and does not commit; the main session integrates, runs the checks, and
commits and pushes. Shared contracts (ledger event schema, claim and verdict types,
dependencies in pyproject.toml) are written by the main session before a workflow
starts and are read-only for the agents.

**D22. Sandbox upgrade (supersedes the D5 fallback).** bubblewrap 0.9.0 installs from apt
in this container and works, and the Docker daemon starts with `dockerd --iptables=false`
(`docker run --network none` verified). The executor prefers Docker, then bubblewrap,
then `unshare -rn`; bubblewrap confines writes to the workspace, so third-party task code
and subject agents may run under it. Docker Hub rate-limits image pulls (HTTP 429 seen
once), so the Docker backend uses locally cached images and bubblewrap is the dependable
default. `tools/provision.sh` reinstalls all of this in a fresh container.

**D23. Local model backend.** GitHub release downloads are blocked by this container's
proxy (no Ollama or llama.cpp binaries), but PyPI and Hugging Face are reachable. The
local backend is the llama-cpp-python 0.3.36 OpenAI-compatible server, built from the PyPI
source distribution into `/opt/receipts-llm` (outside the repository), serving pinned
GGUF files from the vendors' own repositories, verified by the LFS SHA-256:
Qwen/Qwen2.5-Coder-7B-Instruct-GGUF at 13fb94bf (q4_k_m, Apache-2.0) and
ibm-granite/granite-3.3-8b-instruct-GGUF at e40e9dd7 (Q4_K_M, Apache-2.0). Two vendors give
two model families for G7 alongside Claude. Weights are never committed (git-ignored and
stored outside the repository); docs/DATA.md records source, license, and retrieval date.
