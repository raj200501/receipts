"""The claude-code driver: one headless Claude Code run as a test subject.

The command line follows docs/BUILD_BRIEF.md section 8 and the current docs
(docs/notes/claude_code_docs.md):

- ``claude -p --output-format stream-json --verbose`` with ``--model`` choosing the tier;
- ``--restricted --strict-mcp-config`` plus an explicit ``--tools`` list and matching
  ``--allowedTools``, ``--disallowedTools "mcp__*"``, ``--permission-mode dontAsk`` and
  ``--permission-prompts none``, so Raj's settings, hooks, plugins and MCP servers do not
  load and nothing waits on a prompt;
- ``--settings <file>`` written outside the workspace, carrying the receipts recorder hooks
  and Claude Code's built-in Bash sandbox with no network and no unsandboxed fallback;
- ``--max-turns``; the driver also counts assistant turns in the stream and stops the
  child at the cap in case the flag is ignored;
- never ``--bare`` (it authenticates only with an API key).

The billing guard and the daily ``claude_agent_runs_per_day`` cap are checked through
:class:`receipts.client.ModelClient` before anything starts; each run counts once.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol

from receipts.client.wrapper import ModelClient

SUBJECT_TOOLS: tuple[str, ...] = ("Bash", "Read", "Edit", "Write", "Glob", "Grep")

#: Environment passed to a Claude child: an allowlist, so host tokens never reach it.
CHILD_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
)

SANDBOX_SETTINGS: Mapping[str, Any] = {
    "enabled": True,
    "allowUnsandboxedCommands": False,
    "failIfUnavailable": True,
    "network": {"allowedDomains": []},
}


def subject_env(env: Mapping[str, str]) -> dict[str, str]:
    """Build the child environment from the allowlist (parent-session markers excluded)."""
    out = {k: env[k] for k in CHILD_ENV_ALLOWLIST if k in env}
    out["GIT_CONFIG_NOSYSTEM"] = "1"
    out["GIT_CONFIG_GLOBAL"] = "/dev/null"
    return out


def subject_settings(hooks: Mapping[str, Any]) -> dict[str, Any]:
    """Merge receipts hooks with the sandbox block into one ``--settings`` object."""
    return {**dict(hooks), "sandbox": dict(SANDBOX_SETTINGS)}


@dataclass(frozen=True)
class ClaudeRunConfig:
    """One Claude Code subject configuration.

    Attributes:
        model: Model alias or full ID (``haiku``, ``sonnet``, ``opus``, ...).
        max_turns: Agentic turn cap (already scaled by CAP_SHARE by the caller).
        timeout_s: Wall-clock limit for the whole run.
        executable: The ``claude`` binary.
        append_system_prompt: Optional text appended to the default system prompt (for
            mitigation arms such as the honesty instruction or evidence-linked format).
    """

    model: str
    max_turns: int
    timeout_s: float = 3600.0
    executable: str = "claude"
    append_system_prompt: str | None = None


def build_command(config: ClaudeRunConfig, settings_path: Path) -> list[str]:
    """The exact command line, recorded in run provenance."""
    tools = ",".join(SUBJECT_TOOLS)
    argv = [
        config.executable,
        "-p",
        "--model",
        config.model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--restricted",
        "--strict-mcp-config",
        "--tools",
        tools,
        "--allowedTools",
        tools,
        "--disallowedTools",
        "mcp__*",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--settings",
        str(settings_path),
        "--max-turns",
        str(config.max_turns),
        "--no-session-persistence",
    ]
    if config.append_system_prompt:
        argv += ["--append-system-prompt", config.append_system_prompt]
    return argv


@dataclass
class StreamTranscript:
    """The parsed ``stream-json`` output of one run (the native transcript)."""

    events: list[dict[str, Any]] = field(default_factory=list)
    unparsed_lines: int = 0

    def add_line(self, line: str) -> dict[str, Any] | None:
        """Parse and keep one stream line; returns the event or None if unparseable."""
        if not line.strip():
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self.unparsed_lines += 1
            return None
        if not isinstance(event, dict):
            self.unparsed_lines += 1
            return None
        self.events.append(event)
        return event

    @staticmethod
    def is_main_assistant(event: Mapping[str, Any]) -> bool:
        """True for an assistant message of the main conversation (not a subagent)."""
        return event.get("type") == "assistant" and event.get("parent_tool_use_id") is None

    @property
    def assistant_turns(self) -> int:
        """Main-conversation assistant messages seen so far."""
        return sum(1 for e in self.events if self.is_main_assistant(e))

    @property
    def result(self) -> Mapping[str, Any] | None:
        """The final ``result`` event, if the run produced one."""
        results = [e for e in self.events if e.get("type") == "result"]
        return results[-1] if results else None

    @property
    def final_report(self) -> str:
        """The final report text (``result.result``), or the last assistant text."""
        result = self.result
        if result is not None and isinstance(result.get("result"), str):
            return str(result["result"])
        for event in reversed(self.events):
            if self.is_main_assistant(event):
                texts = [b.get("text", "") for b in _content(event) if b.get("type") == "text"]
                if any(texts):
                    return "\n".join(t for t in texts if t)
        return ""

    def tool_uses(self) -> list[dict[str, Any]]:
        """Every ``tool_use`` block the main conversation issued, in order."""
        return [
            block
            for event in self.events
            if self.is_main_assistant(event)
            for block in _content(event)
            if block.get("type") == "tool_use"
        ]

    def bash_commands(self) -> list[str]:
        """Commands of every Bash tool use (for the ledger-completeness check, E0b)."""
        return [
            str(block.get("input", {}).get("command", ""))
            for block in self.tool_uses()
            if block.get("name") == "Bash"
        ]

    def plan_equivalent_usd(self) -> float:
        """``total_cost_usd`` from the result: an API-price estimate, never cash."""
        result = self.result or {}
        value = result.get("total_cost_usd", 0.0)
        return float(value) if isinstance(value, int | float) else 0.0

    def usage_tokens(self) -> tuple[int, int]:
        """Input and output tokens from the result's ``usage``."""
        usage = (self.result or {}).get("usage") or {}
        if not isinstance(usage, dict):
            return 0, 0
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def _content(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


class Process(Protocol):
    """The subset of ``subprocess.Popen`` the driver uses (fakeable in tests)."""

    stdout: IO[str] | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def send_signal(self, sig: int) -> None: ...

    def kill(self) -> None: ...


Spawner = Callable[[Sequence[str], Path, Mapping[str, str], str], Process]


def spawn(argv: Sequence[str], cwd: Path, env: Mapping[str, str], prompt: str) -> Process:
    """Start the child with the prompt on stdin and stdout piped as text."""
    proc = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(prompt)
    proc.stdin.close()
    return proc


@dataclass(frozen=True)
class ClaudeRunResult:
    """How one subject run ended."""

    transcript: StreamTranscript
    exit_code: int
    stop_reason: str  # "finished", "max_turns", "timeout", "error"
    wall_s: float
    command: Sequence[str]


def _stop(proc: Process) -> int:
    """End the child: SIGINT first so the turn ends cleanly, then kill."""
    proc.send_signal(signal.SIGINT)
    try:
        return proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=20)


def run_subject(
    prompt: str,
    workspace: Path,
    settings_path: Path,
    config: ClaudeRunConfig,
    client: ModelClient,
    *,
    purpose: str,
    transcript_path: Path,
    spawner: Spawner = spawn,
    clock: Callable[[], float] = time.monotonic,
    env: Mapping[str, str] | None = None,
) -> ClaudeRunResult:
    """Run one subject, enforcing the guard, the run cap, the turn cap, and the timeout.

    The raw stream is written to ``transcript_path`` line by line as it arrives.
    """
    client.begin_claude_run("agent_run", config.model, purpose)
    argv = build_command(config, settings_path)
    start = clock()
    proc = spawner(argv, workspace, subject_env(os.environ if env is None else env), prompt)
    transcript = StreamTranscript()
    stop_reason = "finished"
    exit_code: int | None = None
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("w", encoding="utf-8") as raw:
        for line in _lines(proc):
            raw.write(line if line.endswith("\n") else line + "\n")
            transcript.add_line(line)
            if transcript.assistant_turns > config.max_turns:
                stop_reason = "max_turns"
                exit_code = _stop(proc)
                break
            if clock() - start > config.timeout_s:
                stop_reason = "timeout"
                exit_code = _stop(proc)
                break
    if exit_code is None:
        exit_code = proc.wait()
    result = transcript.result
    if stop_reason == "finished" and result is not None:
        subtype = str(result.get("subtype", ""))
        if subtype == "error_max_turns":
            stop_reason = "max_turns"
        elif result.get("is_error") or subtype not in ("", "success"):
            stop_reason = "error"
    elif stop_reason == "finished" and exit_code != 0:
        stop_reason = "error"
    wall = clock() - start
    tokens_in, tokens_out = transcript.usage_tokens()
    client.record_claude_run(
        "agent_run",
        config.model,
        purpose,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        wall_s=wall,
        plan_equivalent_usd=transcript.plan_equivalent_usd(),
    )
    return ClaudeRunResult(transcript, exit_code, stop_reason, wall, argv)


def _lines(proc: Process) -> Iterable[str]:
    if proc.stdout is None:
        return []
    return iter(proc.stdout.readline, "")
