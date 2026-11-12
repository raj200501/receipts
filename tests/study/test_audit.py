"""The path audit of a run's ledger (review N18, DECISIONS D67).

Every ledger here is a SYNTHETIC test fixture written with the real recorder: the
workspace path, the commands, and the files are made up, and nothing runs. The audit
is lexical, so the workspace never has to exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from receipts.ledger.events import LedgerWriter
from receipts.ledger.recorder import Recorder
from receipts.sandbox.api import CommandOutcome
from receipts.study.audit import (
    RunAudit,
    audit_ledger,
    content_findings,
    format_audit,
    path_findings,
    shell_findings,
)

WS = "/home/synthetic/receipts/runs/work/smoke/run-1"
CHECKOUT = "/home/synthetic/receipts"


def outcome(cmd: str, cwd: str = ".") -> CommandOutcome:
    """A SYNTHETIC command outcome (nothing ran)."""
    return CommandOutcome(
        cmd=cmd,
        cwd=cwd,
        exit_code=0,
        stdout="",
        stderr="",
        duration_s=0.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_sha256="0" * 64,
        stderr_sha256="0" * 64,
        backend="synthetic",
    )


class Run:
    """A SYNTHETIC minimal-agent run written to ``<root>/ledger.jsonl``."""

    def __init__(self, root: Path, *, workspace: str | None = WS) -> None:
        self.root = root
        self.recorder = Recorder(LedgerWriter(root / "ledger.jsonl"))
        self.recorder.record_run_start(
            run_id="synthetic-run",
            task_id="py-synthetic",
            agent="minimal-agent",
            model="synthetic-model",
            config_id="synthetic-arm",
            workspace="" if workspace is None else workspace,
            base_commit="0" * 40,
        )

    def act(self, tool: str, error: bool = False, **args: str) -> int:
        """One tool call with its result; a bash call also gets its command event."""
        seq = self.recorder.record_tool_call(tool, {"tool": tool, "args": args, "thought": "t"})
        if tool == "bash":
            self.recorder.record_command(outcome(args["cmd"]), seq, "agent", derive=False)
        shown = "error: path escapes the repository" if error else "ok"
        self.recorder.record_tool_result(seq, shown, is_error=error)
        return seq

    def tests(self, cmd: str = "python3 -m pytest -q", cwd: str = ".") -> int:
        """A run_tests call: the command is the task's, not the agent's text."""
        seq = self.recorder.record_tool_call("run_tests", {"tool": "run_tests", "args": {}})
        command = self.recorder.record_command(outcome(cmd, cwd), seq, "agent", derive=False)
        self.recorder.record_tool_result(seq, "ok")
        return command

    def call(self, tool: str, tool_input: dict[str, Any]) -> int:
        """A Claude Code style tool call (flat input)."""
        seq = self.recorder.record_tool_call(tool, tool_input)
        self.recorder.record_tool_result(seq, "ok")
        return seq

    def audit(self) -> RunAudit:
        return audit_ledger(self.root)


@pytest.fixture
def run(tmp_path: Path) -> Run:
    return Run(tmp_path / "run")


def kinds(audit: RunAudit) -> list[tuple[int | None, str]]:
    return [(f.seq, f.kind) for f in audit.findings]


# The four cases the review asked for ----------------------------------------------------


def test_a_clean_ledger_has_no_findings(run: Run) -> None:
    run.act("read", path="src/app.py")
    run.act("write", path="tests/test_app.py", content="from app import add\n")
    run.act("edit", path="src/app.py", old="a - b", new="a + b")
    run.act("bash", cmd="python3 -m pytest -q 2>/dev/null | tail -n 5")
    run.act("bash", cmd=f"cd src && ls -la && cat {WS}/README.md")
    run.tests()
    run.act("finish", report="Fixed add in src/app.py; the tests pass.")
    audit = run.audit()
    assert audit.clean and audit.findings == ()
    assert (audit.tool_calls, audit.commands, audit.workspace) == (7, 3, WS)
    assert format_audit(audit)[0].endswith("CLEAN")


def test_a_read_that_climbs_out_of_the_workspace_is_found(run: Run) -> None:
    seq = run.act("read", error=True, path="../../bench/tasks/x/hidden/check.py")
    audit = run.audit()
    assert kinds(audit) == [(seq, "file_path")]
    (finding,) = audit.findings
    assert "../../bench/tasks/x/hidden/check.py" in finding.detail
    assert "error" in finding.detail  # the tool refused it; still reported


def test_an_absolute_path_in_a_bash_command_is_found_once(run: Run) -> None:
    seq = run.act("bash", cmd=f"cat {CHECKOUT}/bench/tasks/x/hidden/check.py")
    audit = run.audit()
    # The command event repeats the tool call's text, so it is reported at the call.
    assert kinds(audit) == [(seq, "absolute")]
    assert f"{CHECKOUT}/bench/tasks/x/hidden/check.py" in audit.findings[0].detail


def test_cd_to_the_root_is_found(run: Run) -> None:
    seq = run.act("bash", cmd="cd / && ls")
    assert {k for s, k in kinds(run.audit()) if s == seq} == {"cd", "absolute"}


# Shell commands ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cmd", "kind"),
    [
        ("cd ..", "dotdot"),
        ("cd .. && ls", "cd"),
        ("cd", "cd"),
        ("cd -", "cd"),
        ("cd $SOMEWHERE", "cd"),
        ('cd "$(git rev-parse --show-toplevel)"', "cd"),
        ("pushd /tmp", "cd"),
        ("ls ~", "home"),
        ("cat ~/.netrc", "home"),
        ("cat $HOME/.netrc", "home"),
        ("cat ${HOME}/.netrc", "home"),
        ("git -C.. status", "dotdot"),
        ("tar -C/home/synthetic -cf - receipts", "absolute"),
        ("python3 -c \"print(open('/etc/hostname').read())\"", "absolute"),
        ("python3 -c \"import os; os.chdir('..')\"", "dotdot"),
        ("cat \\/etc/hostname", "absolute"),
        (f"PATH={WS}/bin:/opt/tools ls", "absolute"),
        ("echo x > /tmp/scratch", "absolute"),
        ("ls /", "absolute"),
        ("find / -name check.py", "absolute"),
        ("cat /proc/self/root/home/synthetic/receipts/private/notes.txt", "absolute"),
        ("curl file:///etc/hostname", "absolute"),
        (f"cat {WS}/../run-2/.receipts_hidden/check.py", "absolute"),
        ("ls src/../..", "dotdot"),
    ],
)
def test_shell_commands_that_leave_the_workspace(cmd: str, kind: str) -> None:
    found = shell_findings(cmd, WS)
    assert kind in {k for k, _ in found}, found


@pytest.mark.parametrize(
    "cmd",
    [
        "python3 -m pytest -v tests/test_app.py::test_add",
        "npm test 2>&1 | tail -n 20",
        f"cat {WS}/src/app.py > /dev/null",
        "cd src/pkg && python3 -m pytest",
        "git log --oneline HEAD~1..HEAD",
        "echo 'all done...'",
        "pip download https://pypi.org/simple/pytest/",
        "grep -n 'a/b' src/app.py",
        "echo $((6 * 7))",
    ],
)
def test_shell_commands_inside_the_workspace_are_not_found(cmd: str) -> None:
    assert shell_findings(cmd, WS) == []


def test_a_run_tests_command_with_a_cwd_outside_is_found(run: Run) -> None:
    assert run.tests() and run.audit().clean
    seq = run.tests(cwd="../run-2")
    assert (seq, "cwd") in kinds(run.audit())


def test_a_command_that_no_shell_call_wrote_is_scanned_at_its_own_seq(run: Run) -> None:
    # run_tests runs the task's test command; its text is not in the tool call.
    seq = run.tests(cmd=f"python3 -m pytest {CHECKOUT}/bench/tasks/x/hidden")
    audit = run.audit()
    assert kinds(audit) == [(seq, "absolute")]
    assert audit.findings[0].tool == "command"


# File tools -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "found"),
    [
        ("src/app.py", False),
        (f"{WS}/src/app.py", False),
        ("../run-2/src/app.py", True),
        ("src/../../run-2", True),
        ("src/../tests/test_app.py", True),  # stays inside, but a symlink could make it leave
        ("/etc/hostname", True),
        (f"{CHECKOUT}/private/notes.txt", True),
        ("~/.netrc", True),
        (WS + "-other/x", True),
    ],
)
def test_file_tool_paths(path: str, found: bool) -> None:
    assert bool(path_findings(path, WS)) is found


def test_claude_code_file_tools_are_audited(run: Run) -> None:
    read = run.call("Read", {"file_path": f"{CHECKOUT}/bench/tasks/x/hidden/check.py"})
    run.call("Read", {"file_path": f"{WS}/src/app.py"})
    glob = run.call("Glob", {"pattern": "../**/*.py"})
    grep = run.call("Grep", {"pattern": "def check", "path": "/home"})
    run.call("Grep", {"pattern": "/etc/hostname", "path": "src"})  # a pattern, not a path
    edit = run.call("Edit", {"file_path": "/etc/hosts", "old_string": "a", "new_string": "b"})
    bash = run.call("Bash", {"command": "cat ../../../../bench/tasks/x/hidden/check.py"})
    found = kinds(run.audit())
    for seq in (read, glob, grep, edit):
        assert (seq, "file_path") in found, (seq, found)
    assert (bash, "dotdot") in found
    assert len({s for s, _ in found}) == 5


def test_an_unknown_tool_is_reported(run: Run) -> None:
    seq = run.call("WebFetch", {"url": "https://example.invalid/"})
    assert kinds(run.audit()) == [(seq, "unknown_tool")]


# Text the agent wrote into files ---------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "text", "found"),
    [
        ("tests/test_app.py", f"open('{CHECKOUT}/bench/tasks/x/hidden/check.py')\n", True),
        ("tests/test_app.py", "data = open('/etc/hostname').read()\n", True),
        ("tests/test_app.py", "HERE = os.path.join(here, '..', '..', 'bench')\n", True),
        ("tests/test_x.test.ts", "import { add } from '../src/add.ts';\n", False),
        ("src/stringify.ts", "import { isObject } from '../../utils';\n", True),
        ("src/pkg/mod.py", "from .. import helpers\n", False),
        ("scripts/run.py", "#!/usr/bin/env python3\nprint('hi')\n", False),
        ("scripts/run.sh", "#!/bin/sh -c 'cat /etc/hostname'\n", True),
        ("README.md", "See https://example.invalid/docs/api for the /api/users route.\n", False),
        ("src/app.py", "x = a / b; y = a // b  # division, not paths\n", False),
        ("src/app.py", "out = Path('~/.cache').expanduser()\n", True),
        ("src/app.py", f"LOG = '{WS}/logs/app.log'\n", False),
        ("src/app.py", "sys.stdout.write(open('/dev/null').read())\n", False),
    ],
)
def test_written_text_that_names_a_path_outside(written: str, text: str, found: bool) -> None:
    assert bool(content_findings(text, WS, written)) is found


def test_written_content_is_audited_for_every_write_tool(run: Run) -> None:
    write = run.act("write", path="tests/test_x.py", content="open('/etc/hostname')\n")
    edit = run.act("edit", path="src/a.ts", old="x", new="from '../../utils'")
    multi = run.call(
        "MultiEdit",
        {"file_path": f"{WS}/src/b.py", "edits": [{"old_string": "a", "new_string": "'/root'"}]},
    )
    found = kinds(run.audit())
    for seq in (write, edit, multi):
        assert (seq, "content") in found, (seq, found)


# Ledgers the audit cannot read whole -----------------------------------------------------


def test_a_ledger_without_a_workspace_cannot_be_audited(tmp_path: Path) -> None:
    run = Run(tmp_path / "run", workspace=None)
    run.act("read", path="src/app.py")
    audit = run.audit()
    assert [f.kind for f in audit.findings] == ["ledger"]
    assert "workspace" in audit.findings[0].detail


def test_an_incomplete_last_line_is_reported(run: Run) -> None:
    run.act("read", path="src/app.py")
    with (run.root / "ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 4, "kind": "tool_call", "data": {"tool": "ba')
    audit = run.audit()
    assert [f.kind for f in audit.findings] == ["ledger"]
    assert "still being written" in audit.findings[0].detail


def test_a_broken_hash_chain_is_reported(run: Run) -> None:
    run.act("read", path="src/app.py")
    path = run.root / "ledger.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[1])
    event["data"]["input"]["args"]["path"] = "src/other.py"
    lines[1] = json.dumps(event)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert "hash chain" in " ".join(f.detail for f in run.audit().findings)


def test_a_missing_ledger_cannot_be_audited(tmp_path: Path) -> None:
    audit = audit_ledger(tmp_path / "nowhere")
    assert not audit.clean and audit.findings[0].kind == "ledger"


def test_the_report_names_each_seq_and_whether_the_run_is_banked(run: Run) -> None:
    seq = run.act("bash", cmd="cat /etc/hostname")
    lines = format_audit(run.audit())
    assert "in progress" in lines[0] and "1 finding" in lines[0]
    assert lines[1].startswith(f"  seq {seq} bash absolute: /etc/hostname")
    (run.root / "run.json").write_text("{}", encoding="utf-8")
    assert "banked" in format_audit(run.audit())[0]
