# Log

History moved out of STATUS.md, newest first.

## 2026-10-23: bootstrap

Bootstrap (docs/BUILD_BRIEF.md section 10.1) ran in a Claude Code on the web
container started by Raj with the heartbeat `/loop` message only.

- Commits: `bootstrap` (52ff2fe), then a ship_check fix (1270e85): the first fast run
  exposed that uv warnings on stderr broke G11 and G12 parsing and that G2 matched
  `type: ignore` inside string literals. Both fixed and covered by tests.
- Fast ship-check at 1270e85: 2/14 (G2, G14 pass). All other gates fail for the
  expected reason: nothing has been built yet.
- Billing guard tripped by the runtime's `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_USE_CCR_V2`;
  no Claude children launched. No model calls of any kind were made.
- Not pushed (`ALLOW_PUSH` unset).
