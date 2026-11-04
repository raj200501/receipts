"""Tests for minimal-agent's protocol, tool boundary, and loop (fake model, fake runtime)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from receipts.client.wrapper import ModelClient, ModelRequest, ModelResponse
from receipts.drivers.minimal_agent import boundary, loop, protocol
from receipts.drivers.minimal_agent.protocol import Action, ProtocolError, parse_action

ROOT = Path(__file__).resolve().parents[2]


def act(tool: str, **args: str) -> str:
    return "```json\n" + json.dumps({"thought": "t", "tool": tool, "args": args}) + "\n```"


def test_parse_action_variants() -> None:
    assert parse_action(act("bash", cmd="ls")) == Action("bash", {"cmd": "ls"}, "t")
    bare = 'I will run tests. {"tool": "run_tests", "args": {}} done'
    assert parse_action(bare).tool == "run_tests"
    two = (
        'Example: {"tool": "read", "args": {"path": "a"}} '
        'now {"tool": "finish", "args": {"report": "x"}}'
    )
    assert parse_action(two).tool == "finish"
    extra = '{"tool": "read", "args": {"path": "a", "junk": 1}}'
    assert parse_action(extra).args == {"path": "a"}
    braces = '{"tool": "write", "args": {"path": "a.py", "content": "d = {\\"k\\": \\"}\\"}"}}'
    assert parse_action(braces).args["content"] == 'd = {"k": "}"}'


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("no json here", "no JSON action"),
        ('{"tool": "rm", "args": {}}', "unknown tool"),
        ('{"tool": "bash", "args": []}', "args must be"),
        ('{"tool": "bash", "args": {}}', "needs args: cmd"),
        ('{"tool": "bash", "args": {"cmd": 3}}', "must be a string"),
        ('{not json} {"x": 1}', "no JSON action"),
    ],
)
def test_parse_action_errors(text: str, match: str) -> None:
    with pytest.raises(ProtocolError, match=match):
        parse_action(text)


def test_protocol_error_message_and_action_dict() -> None:
    msg = protocol.format_protocol_error(ProtocolError("bad"))
    assert "bad" in msg and "```json" in msg
    assert Action("bash", {"cmd": "x"}).to_dict() == {
        "tool": "bash",
        "args": {"cmd": "x"},
        "thought": "",
    }
    assert "finish" in protocol.SYSTEM_PROMPT and "\N{EM DASH}" not in protocol.SYSTEM_PROMPT


def test_truncation_policy() -> None:
    out = "".join(f"line {i}\n" for i in range(10))
    full = boundary.TruncationPolicy().apply("bash", out)
    assert full == boundary.Shown(out, len(out), False)
    cut = boundary.TruncationPolicy(max_lines=3).apply("run_tests", out)
    assert cut.truncated and cut.text.startswith("line 0\nline 1\nline 2\n")
    assert "7 more lines not shown" in cut.text and cut.full_chars == len(out)
    assert not boundary.TruncationPolicy(max_lines=3).apply("read", out).truncated
    assert not boundary.TruncationPolicy(max_lines=30).apply("bash", out).truncated


def test_flakiness_policy_is_seeded() -> None:
    a = boundary.FlakinessPolicy(0.5, seed=7)
    b = boundary.FlakinessPolicy(0.5, seed=7)
    seq_a = [a.should_fail("bash") for _ in range(20)]
    assert seq_a == [b.should_fail("bash") for _ in range(20)]
    assert any(seq_a) and not all(seq_a)
    assert boundary.FlakinessPolicy(1.0).should_fail("read") is None
    assert boundary.FlakinessPolicy(0.0).should_fail("bash") is None
    assert boundary.FlakinessPolicy(1.0).should_fail("bash") in boundary.TRANSIENT_ERRORS
    with pytest.raises(ValueError):
        boundary.FlakinessPolicy(1.5)
    assert boundary.frozen(["a"]) == frozenset({"a"})


def test_compact_elides_oldest_tool_results() -> None:
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}]
    for i in range(10):
        msgs += [{"role": "assistant", "content": f"a{i}"}, {"role": "user", "content": "x" * 100}]
    out = loop.compact(msgs, budget_chars=500, keep_recent=4)
    assert out[1]["content"] == "task" and out[2]["content"] == "a0"
    assert out[3]["content"] == loop.ELIDED and out[-1]["content"] == "x" * 100
    assert sum(len(m["content"]) for m in out) <= 500 or all(
        m["content"] in (loop.ELIDED, "s", "task") or m["role"] == "assistant" for m in out[:-4]
    )
    assert loop.compact(msgs, budget_chars=10**6) == msgs


class ScriptedBackend:
    """Replies with a fixed script of actions (synthetic)."""

    name = "local"
    is_claude = False

    def __init__(self, replies: Sequence[str]) -> None:
        self.replies = list(replies)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.replies.pop(0), 1, 1, 0.0, "stop")


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.results: list[tuple[str, boundary.Shown, bool]] = []

    def record_call(self, action: Action) -> int:
        self.calls.append(action.tool)
        return len(self.calls) - 1

    def execute(self, action: Action, call_seq: int) -> tuple[str, bool]:
        return "".join(f"out {i}\n" for i in range(5)), action.tool == "run_tests"

    def record_result(
        self, action: Action, call_seq: int, shown: boundary.Shown, is_error: bool
    ) -> None:
        self.results.append((action.tool, shown, is_error))


def make_client(tmp_path: Path, backend: ScriptedBackend) -> ModelClient:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    shutil.copy(ROOT / "budget.toml", root / "budget.toml")
    return ModelClient(root, {"local": backend}, root / "cache", env={}, guard_check=list)


def test_run_agent_finishes_with_truncation(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        ["garbage", act("bash", cmd="ls"), act("run_tests"), act("finish", report="Done.")]
    )
    runtime = FakeRuntime()
    config = loop.AgentConfig(
        backend="local", model="m", truncation=boundary.TruncationPolicy(max_lines=2)
    )
    result = loop.run_agent(
        "Fix it.",
        make_client(tmp_path, backend),
        config,
        runtime,
        prior_messages=[{"role": "user", "content": "earlier"}],
    )
    assert (result.report, result.turns, result.stop_reason, result.protocol_errors) == (
        "Done.",
        4,
        "finished",
        1,
    )
    assert runtime.calls == ["bash", "run_tests", "finish"]
    assert all(shown.truncated for _, shown, _ in runtime.results)
    assert runtime.results[1][2] is True
    first = backend.requests[0].messages
    assert first[0]["content"] == protocol.SYSTEM_PROMPT and first[1]["content"] == "earlier"
    assert "Result of bash:\nout 0\nout 1\n" in result.messages[6]["content"]


def test_run_agent_flaky_and_max_turns(tmp_path: Path) -> None:
    backend = ScriptedBackend([act("bash", cmd=f"echo {i}") for i in range(3)])
    runtime = FakeRuntime()
    config = loop.AgentConfig(
        backend="local", model="m", max_turns=3, flakiness_rate=1.0, final_report_request=False
    )
    result = loop.run_agent("Task", make_client(tmp_path, backend), config, runtime)
    assert result.stop_reason == "max_turns" and result.report == "" and result.turns == 3
    assert all(
        is_error and shown.text in boundary.TRANSIENT_ERRORS
        for _, shown, is_error in runtime.results
    )


def test_on_finish_revision_and_event_labels(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [act("run_tests"), act("finish", report="All pass."), act("finish", report="1 fails.")]
    )
    runtime = FakeRuntime()
    config = loop.AgentConfig(
        backend="local", model="m", system_suffix="Cite events.", label_events=True
    )
    seen: list[str] = []

    def check(report: str) -> str | None:
        seen.append(report)
        return (
            "receipts: 'All pass.' is contradicted by event 0." if report == "All pass." else None
        )

    result = loop.run_agent(
        "Task", make_client(tmp_path, backend), config, runtime, on_finish=check
    )
    assert result.report == "1 fails." and result.drafts == ("All pass.",)
    assert seen == ["All pass."]
    assert backend.requests[0].messages[0]["content"].endswith("\n\nCite events.")
    assert "Result of run_tests (event 0):" in result.messages[3]["content"]
    assert "contradicted by event 0" in result.messages[5]["content"]


def test_on_finish_not_called_past_revision_limit(tmp_path: Path) -> None:
    backend = ScriptedBackend([act("finish", report="a"), act("finish", report="b")])
    config = loop.AgentConfig(backend="local", model="m", max_report_revisions=1)
    result = loop.run_agent(
        "T", make_client(tmp_path, backend), config, FakeRuntime(), on_finish=lambda r: "again"
    )
    assert result.report == "b" and result.drafts == ("a",)
    last_turn = loop.AgentConfig(backend="local", model="m", max_turns=1)
    one = ScriptedBackend([act("finish", report="only")])
    out = loop.run_agent(
        "T", make_client(tmp_path / "b", one), last_turn, FakeRuntime(), on_finish=lambda r: "again"
    )
    assert out.report == "only" and out.drafts == ()


def cap_config() -> loop.AgentConfig:
    return loop.AgentConfig(backend="local", model="m", max_turns=2)


def test_the_turn_limit_asks_once_for_the_final_report(tmp_path: Path) -> None:
    replies = [act("bash", cmd="ls"), act("bash", cmd="ls"), act("finish", report="Partly done.")]
    backend = ScriptedBackend(replies)
    runtime = FakeRuntime()
    result = loop.run_agent("Task", make_client(tmp_path, backend), cap_config(), runtime)
    assert (result.report, result.turns, result.stop_reason) == (
        "Partly done.",
        3,
        "finished_at_cap",
    )
    assert runtime.calls == ["bash", "bash", "finish"]
    request = backend.requests[-1]
    assert request.purpose.endswith("final report")
    assert request.messages[-1]["content"] == loop.FINAL_REPORT_REQUEST.format(turns=2)


def test_an_action_after_the_turn_limit_is_never_run(tmp_path: Path) -> None:
    replies = [act("bash", cmd="ls"), act("bash", cmd="ls"), act("bash", cmd="rm -rf x")]
    backend = ScriptedBackend(replies)
    runtime = FakeRuntime()
    result = loop.run_agent("Task", make_client(tmp_path, backend), cap_config(), runtime)
    assert (result.report, result.turns, result.stop_reason) == ("", 2, "max_turns")
    assert runtime.calls == ["bash", "bash"] and len(runtime.results) == 2
    assert result.messages[-1] == {"role": "user", "content": loop.NOT_RUN_AT_CAP}


def test_a_malformed_reply_at_the_turn_limit_ends_without_a_report(tmp_path: Path) -> None:
    backend = ScriptedBackend([act("bash", cmd="ls"), act("bash", cmd="ls"), "no json here"])
    result = loop.run_agent("Task", make_client(tmp_path, backend), cap_config(), FakeRuntime())
    assert (result.report, result.stop_reason, result.protocol_errors) == ("", "max_turns", 1)
