"""Tests for E0b ledger completeness (transcripts and ledgers below are synthetic)."""

from __future__ import annotations

import json
from pathlib import Path

from receipts.drivers.minimal_agent.boundary import TRANSIENT_ERRORS
from receipts.evaluation import completeness
from receipts.ledger.events import Ledger, LedgerWriter


def act(tool: str, **args: str) -> dict[str, str]:
    return {"role": "assistant", "content": json.dumps({"tool": tool, "args": args})}


def obs(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


MESSAGES = [
    {"role": "system", "content": "s"},
    obs("Fix it."),
    act("bash", cmd="ls -la"),
    obs("Result of bash:\nfile\n[exit code 0]"),
    act("run_tests"),
    obs("Result of run_tests:\n" + TRANSIENT_ERRORS[0]),
    act("run_tests"),
    obs("Result of run_tests:\n1 passed"),
    {"role": "assistant", "content": "not an action"},
    obs("Your last reply could not be used"),
    act("read", path="a.py"),
    obs("x = 1"),
    act("bash", cmd="echo last"),
]


def ledger(tmp_path: Path, cmds: list[str]) -> Ledger:
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    for cmd in cmds:
        w.append("command", {"cmd": cmd, "exit_code": 0, "source": "agent"})
    w.append("command", {"cmd": "pytest -q", "exit_code": 0, "source": "snapshot"})
    return Ledger(w.events)


def test_transcript_commands_skip_flaky_and_non_commands() -> None:
    assert completeness.transcript_commands(MESSAGES, "pytest -q") == [
        "ls -la",
        "pytest -q",
        "echo last",
    ]


def test_complete_and_incomplete_runs(tmp_path: Path) -> None:
    full = completeness.check_run(
        "r1", MESSAGES, ledger(tmp_path, ["ls -la", "pytest -q", "echo last"]), "pytest -q"
    )
    assert full.missing == [] and full.to_dict()["missing"] == []
    gap = completeness.check_run("r2", MESSAGES, ledger(tmp_path / "b", ["ls -la"]), "pytest -q")
    assert gap.missing == ["echo last", "pytest -q"]
    assert gap.to_dict()["ledger_commands"] == ["ls -la"]


def test_an_action_answering_the_final_report_request_is_not_a_command() -> None:
    from receipts.drivers.minimal_agent import loop

    messages = [
        {"role": "assistant", "content": '{"tool": "bash", "args": {"cmd": "ls"}}'},
        {"role": "user", "content": "Result of bash:\nfile\n"},
        {"role": "user", "content": loop.FINAL_REPORT_REQUEST.format(turns=1)},
        {"role": "assistant", "content": '{"tool": "bash", "args": {"cmd": "rm -rf x"}}'},
        {"role": "user", "content": loop.NOT_RUN_AT_CAP},
    ]
    assert completeness.transcript_commands(messages, "pytest -q") == ["ls"]


def test_a_reply_the_run_rejected_is_not_a_command_under_a_newer_parser() -> None:
    from receipts.drivers.minimal_agent import protocol

    # Synthetic transcript: a bash action with a backslash JSON cannot escape (\d). The
    # strict parser of older runs rejected it and the loop answered with a protocol
    # error, so it never ran; the current parser accepts it (D45), and completeness must
    # still skip it because the observation says it was not run.
    rejected = '{"tool": "bash", "args": {"cmd": "grep -E \'\\d+\' log.txt"}}'
    assert protocol.parse_action(rejected).args["cmd"] == "grep -E '\\d+' log.txt"
    error = protocol.format_protocol_error(protocol.ProtocolError("no JSON action found"))
    messages = [
        {"role": "assistant", "content": rejected},
        {"role": "user", "content": error},
        act("bash", cmd="ls"),
        obs("Result of bash:\nfile\n[exit code 0]"),
    ]
    assert completeness.never_run(error) and not completeness.never_run("file\n[exit code 0]")
    assert completeness.transcript_commands(messages, "pytest -q") == ["ls"]
