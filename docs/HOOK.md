# receipts-hook

receipts-hook checks a Claude Code session's final report against a record of what the
session actually did, before you read it. When a statement in the report is contradicted
by that record (for example "all tests pass" after a test run that failed), the hook asks
Claude to correct its report, and Claude Code continues the session with that request.

It has two parts:

- **Recorder hooks** (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`): each tool call,
  the text Claude received back, every Bash command with its exit code, and every file
  edit (content before and after) go into an append-only, hash-chained ledger file.
- **Stop hook**: when Claude finishes, receipts extracts the atomic claims from its final
  message (`last_assistant_message`), checks each against the ledger, and, if any is
  contradicted, returns `{"decision": "block", "reason": ...}` listing those claims and
  the evidence. It never blocks twice in a row (`stop_hook_active`), and Claude Code also
  caps consecutive stop-hook continuations.

receipts-hook never blocks or breaks a session because of its own errors: any exception
is written to the session's `errors.log` and the hook exits 0 with no output, which
Claude Code treats as "no decision".

## Install

Requirements: Python 3.11 or later and a checkout of this repository.

1. Install receipts into its own environment (outside the projects you work on):

   ```bash
   git clone https://github.com/raj200501/receipts.git ~/src/receipts
   cd ~/src/receipts && uv sync
   ```

   The hook command is then `~/src/receipts/.venv/bin/receipts-hook`.

2. Add the hooks to your Claude Code user settings (`~/.claude/settings.json`), merging
   with any `hooks` you already have:

   ```json
   {
     "hooks": {
       "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "timeout": 30,
         "command": "~/src/receipts/.venv/bin/receipts-hook record --ledger-dir ~/.receipts/sessions"}]}],
       "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "timeout": 30,
         "command": "~/src/receipts/.venv/bin/receipts-hook record --ledger-dir ~/.receipts/sessions"}]}],
       "PostToolUseFailure": [{"matcher": "*", "hooks": [{"type": "command", "timeout": 30,
         "command": "~/src/receipts/.venv/bin/receipts-hook record --ledger-dir ~/.receipts/sessions"}]}],
       "Stop": [{"hooks": [{"type": "command", "timeout": 30,
         "command": "~/src/receipts/.venv/bin/receipts-hook stop --ledger-dir ~/.receipts/sessions"}]}]
     }
   }
   ```

   To try it for one session only, put the same object in a file and start Claude Code
   with `claude --settings /path/to/that/file`.

3. Start a new session. Each session gets `~/.receipts/sessions/<session_id>.jsonl` (its
   ledger) and `~/.receipts/sessions/<session_id>.state/` (pairing state, `timings.log`
   with each hook's run time, and `errors.log`).

To uninstall, remove the four entries from your settings. To turn every hook off for one
run, start Claude Code with `--settings '{"disableAllHooks": true}'`.

## What it can and cannot check

The Stop hook sees only what happened during the session: commands, their output and exit
codes, test runs it can parse (pytest, JUnit XML, Node's test runner, Jest, Vitest, Mocha),
linters and type checkers, and file edits made with Claude's file tools. It does not rerun
your tests or see hidden checks, so a claim about something the session never observed is
reported as unverifiable, not contradicted, and does not block. Files changed only through
shell commands are not tracked file by file during a live session.

## Privacy

Everything stays on your machine. The ledger holds commands, their output, and the content
of edited files, so treat `~/.receipts/sessions` like your shell history. Nothing is sent
anywhere, and receipts makes no model calls in the hook.

## Measured cost and effect

The hook's added latency and its measured effect on reports (experiment E4) are reported
in docs/REPORT.md from banked artifacts under `artifacts/hook/` and `artifacts/e4/`.
