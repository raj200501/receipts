goal_turn: 0
STATE: ACTIVE

# Status

Updated 2026-10-23 at bootstrap (docs/BUILD_BRIEF.md section 10.1). History is in docs/LOG.md.

## Gates

Not run yet at this commit; the first `python tools/ship_check.py --fast` result is
recorded in the next commit.

## Now

Bootstrap: scaffold, `make doctor`, gate harness, integrity tools, CLAUDE.md, subagents.

## Next three actions

1. M1: `receipts.ledger` (hash-chained JSONL ledger, local sandbox executor, pytest and
   JUnit parsers), test-first.
2. M1: `receipts.claims` deterministic extractors and `receipts.verify` checkers for the
   common claim types, then recorded fixtures and `make demo` with its golden output.
3. M1: try installing bubblewrap so the sandbox can confine filesystem writes (D5).

## Environment (`make doctor`, 2026-10-23)

- Platform: Linux x86_64 cloud container (Claude Code on the web); RAM 15.7 GB; free disk 32 GB; 4 CPUs; no GPU
- Python 3.11 and 3.12 available (venv on 3.11); uv 0.11.32; git 2.43; node 22, npm 10
- docker: binary present, daemon not reachable
- claude: 2.1.309 installed, unusable: billing guard tripped by `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_CCR_V2`
- ollama, llama.cpp, gemini, codex: not installed; free tiers: not confirmed
- sandbox: `unshare -rn` works; no bubblewrap; no Docker; not macOS
- Usable backends: claude=no, local=no, free_tier=no
- local_model_max_params_b that fits RAM: 8 (cap unchanged)
- Fallbacks: local sandbox via `unshare -rn` plus scrubbed environment, rlimits, temp
  workspace, only for this project's own generated tasks (D5); pipeline jobs and review via
  Claude Code subagents (D4); local models need Ollama or llama.cpp installed first

## Usage to date

cash_usd = 0. Claude agent runs 0, single calls 0, review runs 0. Local model runs 0.
Subagent use: none yet.

## Needs Raj

1. **Commits are not pushed and this container is temporary.** `ALLOW_PUSH` is not set, so
   every commit stays in this cloud container and is lost when it is reclaimed. Action: in
   the session's cloud environment settings (environment menu in the title bar, then Edit),
   add the environment variable `ALLOW_PUSH=1` and start a new session, or tell Claude in
   this chat that pushing to `origin` is allowed; or run the build on your own machine.
2. **Claude subject runs are disabled here (billing guard).** This runtime sets
   `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_USE_CCR_V2`, which section 8 treats as possible
   per-token billing. E1 needs at least two Claude tiers as subjects, so G7 to G9 cannot
   finish here. Action: run the build on a machine where `claude` is logged in to your Max
   plan and `env | grep -E '^(ANTHROPIC_|CLAUDE_CODE_USE_)'` prints nothing (section 0 step 4).
   Work that needs no Claude children (M1 to M4 with local models) continues meanwhile.

## Blocked

Nothing yet.

## Backlog (suggestions for Raj, not ladder rungs)

- Publish the claim-type taxonomy and verifier as a small standalone spec so other agent
  CLIs can emit evidence-linked reports that receipts can check without a ledger adapter.
