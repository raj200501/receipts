"""Tests for the claude-code driver with a fake child process.

The stream lines are hand-written to the documented stream-json shapes
(docs/notes/claude_code_docs.md); no Claude child is ever started here.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

import pytest

from receipts import guard
from receipts.client.wrapper import ClientRefusedError, ModelClient
from receipts.drivers import claude_code as cc

ROOT = Path(__file__).resolve().parents[2]


def assistant(*blocks: dict[str, Any], parent: str | None = None) -> str:
    return json.dumps(
        {"type": "assistant", "parent_tool_use_id": parent, "message": {"content": list(blocks)}}
    )


def bash_use(cmd: str) -> dict[str, Any]:
    return {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": cmd}}


RESULT = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "result": "Done. All tests pass.",
        "num_turns": 2,
        "total_cost_usd": 0.12,
        "is_error": False,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
)


class FakeProc:
    def __init__(self, lines: Sequence[str], code: int = 0, hang: bool = False) -> None:
        self.stdout: IO[str] | None = io.StringIO("".join(line + "\n" for line in lines))
        self.code = code
        self.signals: list[int] = []
        self.hang = hang
        self.killed = False

    def poll(self) -> int | None:
        return self.code

    def wait(self, timeout: float | None = None) -> int:
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("claude", timeout or 0)
        return self.code

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def kill(self) -> None:
        self.killed = True


def make_client(tmp_path: Path, problems: Sequence[guard.GuardProblem] = ()) -> ModelClient:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    shutil.copy(ROOT / "budget.toml", root / "budget.toml")
    (root / "launch.toml").write_text("cap_share = 0.2\n")
    return ModelClient(
        root,
        {},
        root / "cache",
        env={},
        clock=lambda: 1_761_184_800.0,
        guard_check=lambda: list(problems),
    )


def run(
    tmp_path: Path,
    lines: Sequence[str],
    *,
    max_turns: int = 5,
    code: int = 0,
    hang: bool = False,
    timeout: float = 100.0,
    problems: Sequence[guard.GuardProblem] = (),
) -> tuple[cc.ClaudeRunResult, FakeProc, ModelClient]:
    proc = FakeProc(lines, code, hang)
    seen: dict[str, Any] = {}

    def spawner(argv: Sequence[str], cwd: Path, env: Mapping[str, str], prompt: str) -> FakeProc:
        seen.update(argv=argv, env=env, prompt=prompt)
        return proc

    ticks = iter(range(0, 10_000, 10))
    client = make_client(tmp_path, problems)
    result = cc.run_subject(
        "Fix the bug.",
        tmp_path,
        tmp_path / "settings.json",
        cc.ClaudeRunConfig(model="sonnet", max_turns=max_turns, timeout_s=timeout),
        client,
        purpose="e1 test",
        transcript_path=tmp_path / "t" / "stream.jsonl",
        spawner=spawner,
        clock=lambda: float(next(ticks)),
        env={"PATH": "/bin", "HOME": "/h", "GH_TOKEN": "secret", "CLAUDECODE": "1"},
    )
    assert "GH_TOKEN" not in seen["env"] and "CLAUDECODE" not in seen["env"]
    assert seen["prompt"] == "Fix the bug."
    return result, proc, client


def test_build_command_flags(tmp_path: Path) -> None:
    argv = cc.build_command(
        cc.ClaudeRunConfig(model="haiku", max_turns=8, append_system_prompt="Cite events."),
        tmp_path / "s.json",
    )
    assert "--bare" not in argv
    for flag in ("--restricted", "--strict-mcp-config", "--verbose", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ",".join(cc.SUBJECT_TOOLS)
    assert argv[argv.index("--max-turns") + 1] == "8"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[-2:] == ["--append-system-prompt", "Cite events."]


def test_subject_settings_and_env() -> None:
    settings = cc.subject_settings({"hooks": {"PreToolUse": []}})
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    assert settings["sandbox"]["network"] == {"allowedDomains": []}
    env = cc.subject_env({"PATH": "/bin", "AWS_SECRET_ACCESS_KEY": "x", "LANG": "C"})
    assert env == {
        "PATH": "/bin",
        "LANG": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def test_run_finishes_and_logs_one_agent_run(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "system", "subtype": "init"}),
        assistant({"type": "text", "text": "Running tests."}, bash_use("pytest -q")),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result"}]}}),
        assistant(bash_use("ls"), parent="sub"),
        "not json",
        "[1]",
        "",
        RESULT,
    ]
    result, _, client = run(tmp_path, lines)
    t = result.transcript
    assert result.stop_reason == "finished" and result.exit_code == 0
    assert t.final_report == "Done. All tests pass." and t.assistant_turns == 1
    assert t.bash_commands() == ["pytest -q"] and t.unparsed_lines == 2
    assert t.plan_equivalent_usd() == 0.12 and t.usage_tokens() == (100, 20)
    assert (tmp_path / "t" / "stream.jsonl").read_text().count("\n") == len(lines)
    rows = [json.loads(x) for x in client.usage_path.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["kind"] == "agent_run" and rows[0]["cash_usd"] == 0
    assert rows[0]["plan_equivalent_usd"] == 0.12 and client.used_today("agent_run") == 1


def test_turn_cap_enforced_by_counting(tmp_path: Path) -> None:
    lines = [assistant(bash_use(f"echo {i}")) for i in range(4)]
    result, proc, _ = run(tmp_path, lines, max_turns=2)
    assert result.stop_reason == "max_turns" and proc.signals
    assert result.transcript.final_report == ""


def test_timeout_and_kill(tmp_path: Path) -> None:
    lines = [assistant({"type": "text", "text": "thinking"})] * 3
    result, proc, _ = run(tmp_path, lines, timeout=5.0, hang=True)
    assert result.stop_reason == "timeout" and proc.killed
    assert result.transcript.final_report == "thinking"


@pytest.mark.parametrize(
    ("result_event", "code", "reason"),
    [
        ({"type": "result", "subtype": "error_max_turns", "is_error": True}, 1, "max_turns"),
        ({"type": "result", "subtype": "error_during_execution", "is_error": True}, 1, "error"),
        (None, 1, "error"),
    ],
)
def test_stop_reasons(
    tmp_path: Path, result_event: dict[str, Any] | None, code: int, reason: str
) -> None:
    lines = [json.dumps(result_event)] if result_event else []
    result, _, _ = run(tmp_path, lines, code=code)
    assert result.stop_reason == reason


def test_guard_and_cap_refuse_before_spawn(tmp_path: Path) -> None:
    with pytest.raises(ClientRefusedError, match="billing guard"):
        run(tmp_path, [RESULT], problems=[guard.GuardProblem("env", "ANTHROPIC_BASE_URL")])
    client = make_client(tmp_path / "b")
    for i in range(6):
        client.record_claude_run(
            "agent_run",
            "sonnet",
            f"r{i}",
            input_tokens=1,
            output_tokens=1,
            wall_s=1.0,
            plan_equivalent_usd=0.0,
        )
    with pytest.raises(ClientRefusedError, match="claude_agent_runs_per_day reached"):
        client.begin_claude_run("agent_run", "sonnet", "seventh")
    offline = ModelClient(
        client.root, {}, client.cache_dir, env={"RECEIPTS_OFFLINE": "1"}, guard_check=list
    )
    with pytest.raises(ClientRefusedError, match="OFFLINE"):
        offline.begin_claude_run("agent_run", "sonnet", "x")


def test_transcript_edge_cases() -> None:
    t = cc.StreamTranscript()
    t.add_line(json.dumps({"type": "result", "usage": "bad", "total_cost_usd": "x"}))
    assert t.usage_tokens() == (0, 0) and t.plan_equivalent_usd() == 0.0
    assert t.final_report == ""
    t2 = cc.StreamTranscript()
    t2.add_line(json.dumps({"type": "assistant", "parent_tool_use_id": None, "message": "x"}))
    assert t2.tool_uses() == [] and t2.final_report == ""


def test_spawn_real_process(tmp_path: Path) -> None:
    proc = cc.spawn(["cat"], tmp_path, {"PATH": "/usr/bin:/bin"}, "hello\n")
    assert proc.stdout is not None and proc.stdout.read() == "hello\n"
    assert proc.wait() == 0
    assert list(cc._lines(FakeProc([]))) == []
    empty = FakeProc([])
    empty.stdout = None
    assert list(cc._lines(empty)) == []
