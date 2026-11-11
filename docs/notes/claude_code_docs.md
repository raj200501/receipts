# Claude Code facts receipts depends on

Read from the official documentation on 2026-10-23 (Claude Code 2.1.309 installed here).
Re-check before relying on a detail; the docs change faster than this file.

## Hooks (https://code.claude.com/docs/en/hooks)

- Configuration: `{"hooks": {"<Event>": [{"matcher": "<tool pattern>", "hooks": [{"type":
  "command", "command": "...", "args": [], "timeout": 30}]}]}}`. Default timeout for
  `command` hooks is 600 seconds.
- Common stdin fields: `session_id`, `prompt_id`, `transcript_path`, `cwd`,
  `scratchpad_dir`, `permission_mode`, `effort`, `hook_event_name` (plus `agent_id`,
  `agent_type` in subagents). `transcript_path` is written asynchronously and may lag the
  current turn.
- PreToolUse: adds `tool_name`, `tool_input`, `tool_use_id`. Bash `tool_input` has
  `command`, `description`, `timeout`, `run_in_background`.
- PostToolUse: adds `tool_response` and `duration_ms`. Bash `tool_response` has `stdout`,
  `stderr`, `interrupted`, `isImage`: **no exit code**. A failing command is reported
  through the PostToolUseFailure event, whose `error` string contains `Exit code N`.
  Write `tool_response`: `{"filePath": ..., "type": "create"}`.
- Stop: adds `stop_hook_active` (true when Claude is already continuing because of a stop
  hook) and `last_assistant_message` (the text of Claude's final response, so the
  transcript need not be parsed). JSON output `{"decision": "block", "reason": "..."}`
  prevents stopping and tells Claude why; exit code 2 also prevents stopping. Claude Code
  caps consecutive stop-hook continuations at 8 (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`).
- `--settings '{"disableAllHooks": true}'` turns hooks off for one run.

## CLI (https://code.claude.com/docs/en/cli-reference)

- `--restricted`: for evaluation harnesses on shared machines. Removes built-in tools that
  run commands or code (and WebFetch) unless named in `--tools`; confines file tools to the
  working directories; loads only managed settings and `--settings`; refuses
  `bypassPermissions`. Requires 2.1.248 or later.
- `--tools "Bash,Edit,Read"` restricts built-in tools (`""` disables all). It does not
  affect MCP tools: also pass `--strict-mcp-config` and `--disallowedTools "mcp__*"`.
- `--max-turns N`: print mode only; exits with an error at the limit.
- `--settings <file or JSON>`: overrides the same keys for this session.
- `--permission-mode`: `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`,
  `bypassPermissions`, `manual`. `--permission-prompts none` denies prompts nobody can
  answer.
- `--no-session-persistence`: print mode; the session is not saved to disk.
- `--bare`: skips hooks, plugins, MCP, CLAUDE.md. Section 8 of the brief forbids it.
- `--max-budget-usd` uses a client-side cost estimate; it is not a cash control.
- `claude auth status` prints JSON and exits 0 when logged in; `authMethod` is one of
  `none`, `claude.ai`, `oauth_token`, `api_key`, `api_key_helper`, `third_party`. Only
  `claude.ai` is a subscription login.
