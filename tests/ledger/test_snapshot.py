"""Tests for take_snapshot, run through a subprocess-backed fake Sandbox in a temporary git repo.

Every repository, file, and command here is synthetic test data written by this
suite; nothing comes from a real agent run.
"""

from __future__ import annotations

import dataclasses
import json
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from receipts.ledger.events import Ledger, LedgerWriter, verify_chain
from receipts.ledger.recorder import Recorder
from receipts.ledger.snapshot import INDEX_NAME, SEPARATOR, diff_script, take_snapshot
from receipts.sandbox.api import CommandOutcome, Sandbox

from .helpers import FIXTURES, SubprocessSandbox, assert_payload_shape, fixture

PY = shlex.quote(sys.executable)
TEST_FILE = """\
def test_add():
    assert 1 + 1 == 2


def test_div():
    assert 1 / 1 == 2
"""
HIDDEN = (
    "print('running hidden checks'); "
    "print('3 passed in 0.01s'); "
    "import json; "
    "print(json.dumps({'checks': [{'name': 'adds', 'passed': True, 'requirement': 'R1'}, "
    "{'name': 'divides', 'passed': False}]}))"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _recorder(tmp_path: Path) -> Recorder:
    return Recorder(LedgerWriter(tmp_path / "ledger.jsonl"))


@pytest.fixture
def base_repo(git_repo: Path, commit: Callable[[Path, str], str]) -> tuple[Path, str]:
    _write(
        git_repo,
        {
            ".gitignore": "build/\n",
            "src/calc.py": "def add(a, b):\n    return a + b\n",
            "README.md": "# calc\n\nA small calculator used as test data.\n" * 3,
            "old.txt": "remove me\n",
            "requirements.txt": "requests==2.31.0\n",
            "web/package.json": json.dumps({"dependencies": {"zod": "^3.22.0"}}),
            "tests/test_calc.py": TEST_FILE,
        },
    )
    return git_repo, commit(git_repo, "base")


def test_snapshot_records_diff_rerun_and_hidden_checks(
    base_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, base = base_repo
    _write(
        repo,
        {
            "src/calc.py": (
                "def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    return a / b\n"
            ),
            "src/new_mod.py": "VALUE = 1\n",
            "requirements.txt": "requests==2.32.3\nrich>=13\n",
            "web/package.json": json.dumps({"dependencies": {"zod": "^3.23.8"}}),
            "build/out.bin": "ignored\n",
            "staged.txt": "staged by the agent\n",
        },
    )
    (repo / "old.txt").unlink()
    (repo / "docs").mkdir()
    (repo / "README.md").rename(repo / "docs" / "README.md")
    _git(repo, "add", "staged.txt")
    sandbox = SubprocessSandbox(repo)
    recorder = _recorder(tmp_path)
    test_cmd = f"{PY} -m pytest -q -p no:cacheprovider tests"
    hidden_cmd = f"{PY} -c {shlex.quote(HIDDEN)}"

    result = take_snapshot(sandbox, recorder, base, test_cmd, hidden_cmd)

    assert result.problems == ()
    ledger = Ledger.load(tmp_path / "ledger.jsonl")
    assert verify_chain(ledger.events) == []
    for event in ledger:
        assert event.source == "snapshot"
        assert_payload_shape(event.kind, event.data)
    assert [e.kind for e in ledger] == ["diff", "command", "test_run", "command", "hidden_check"]

    assert result.diff_seq == 0
    diff = ledger.get(0).data
    assert diff["base"] == base
    files = {f["path"]: f for f in diff["files"]}
    assert files["src/calc.py"]["status"] == "M" and files["src/calc.py"]["added"] == 4
    assert files["src/new_mod.py"]["status"] == "A"
    assert files["staged.txt"]["status"] == "A"
    assert files["old.txt"]["status"] == "D"
    assert files["docs/README.md"]["status"] == "R"
    assert files["docs/README.md"]["old_path"] == "README.md"
    assert not any(path.startswith("build/") for path in files)
    assert diff["dependency_changes"] == [
        {
            "manifest": "requirements.txt",
            "name": "requests",
            "change": "changed",
            "old": "==2.31.0",
            "new": "==2.32.3",
        },
        {
            "manifest": "requirements.txt",
            "name": "rich",
            "change": "added",
            "old": None,
            "new": ">=13",
        },
        {
            "manifest": "web/package.json",
            "name": "zod",
            "change": "changed",
            "old": "^3.22.0",
            "new": "^3.23.8",
        },
    ]

    assert result.test_command_seq == 1
    assert result.test_run_seqs == (2,)
    test_run = ledger.get(2).data
    assert (test_run["framework"], test_run["passed"], test_run["failed"]) == ("pytest", 1, 1)
    assert test_run["failing"] == ["tests/test_calc.py::test_div"]
    assert test_run["command_seq"] == 1

    assert result.hidden_command_seq == 3
    assert ledger.get(3).data["call_seq"] is None
    assert result.hidden_check_seq == 4
    hidden = ledger.get(4).data
    assert (hidden["passed"], hidden["failed"], hidden["total"]) == (1, 1, 2)
    assert hidden["checks"][0] == {"name": "adds", "passed": True, "requirement": "R1"}

    # The workspace's own index is untouched and the temporary index is gone.
    assert _git(repo, "diff", "--cached", "--name-only").split() == ["staged.txt"]
    assert "?? src/new_mod.py" in _git(repo, "status", "--porcelain")
    assert not (repo / ".git" / INDEX_NAME).exists()
    assert len(sandbox.commands) == 7  # diff, two git show, two cat, rerun, hidden


def test_snapshot_with_no_changes_and_no_hidden_checks(
    base_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, _base = base_repo
    jest_output = shlex.quote(str(FIXTURES / "jest" / "fail_npm.txt"))
    (repo / "run_tests.sh").write_text(f"#!/bin/sh\ncat {jest_output} >&2\nexit 1\n")
    recorder = _recorder(tmp_path)
    result = take_snapshot(SubprocessSandbox(repo), recorder, "HEAD", "sh run_tests.sh")
    events = recorder.writer.events
    assert result.problems == ()
    assert events[0].data["files"] == [
        {"path": "run_tests.sh", "status": "A", "added": 3, "removed": 0}
    ]
    assert events[0].data["dependency_changes"] == []
    assert events[2].kind == "test_run" and events[2].data["framework"] == "jest"
    assert (result.hidden_command_seq, result.hidden_check_seq) == (None, None)


def test_snapshot_reports_failed_steps_and_keeps_going(
    base_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, _ = base_repo
    recorder = _recorder(tmp_path)
    crash = "print('3 passed in 0.1s')\nraise SystemExit(2)"
    hidden_cmd = f"{PY} -c {shlex.quote(crash)}"
    result = take_snapshot(SubprocessSandbox(repo), recorder, "0" * 40, "true", hidden_cmd)
    assert result.diff_seq is None
    assert result.test_run_seqs == ()
    assert result.hidden_check_seq is None
    assert [e.kind for e in recorder.writer.events] == ["command", "command"]
    problems = "\n".join(result.problems)
    assert f"git diff against {'0' * 40} failed (exit 128" in problems
    assert "no test summary recognized in the output of 'true'" in problems
    assert "hidden check output did not end with a JSON line" in problems
    assert "(exit 2)" in problems


@pytest.mark.parametrize("base", ["-x", "--output=/tmp/x", "HEAD; rm -rf /", "", "a b"])
def test_snapshot_rejects_revisions_that_could_be_options(base: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a git revision"):
        take_snapshot(SubprocessSandbox(tmp_path), _recorder(tmp_path), base, "true")


def _rewriting(
    match: str, change: Callable[[CommandOutcome], CommandOutcome]
) -> Callable[[CommandOutcome], CommandOutcome]:
    def rewrite(result: CommandOutcome) -> CommandOutcome:
        return change(result) if result.cmd.startswith(match) else result

    return rewrite


def test_snapshot_skips_manifests_it_cannot_read(
    base_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, base = base_repo
    _write(repo, {"requirements.txt": "rich\n", "web/package.json": "{}"})
    failing_show = _rewriting(
        "git show", lambda r: dataclasses.replace(r, exit_code=128, stderr="fatal: bad object\n")
    )
    recorder = _recorder(tmp_path)
    result = take_snapshot(SubprocessSandbox(repo, rewrite=failing_show), recorder, base, "true")
    assert recorder.writer.events[0].data["dependency_changes"] == []
    assert any(
        "could not read requirements.txt at" in p and "fatal: bad object" in p
        for p in result.problems
    )

    cut_cat = _rewriting("cat --", lambda r: dataclasses.replace(r, stdout_truncated=True))
    recorder = Recorder(LedgerWriter(tmp_path / "second.jsonl"))
    result = take_snapshot(SubprocessSandbox(repo, rewrite=cut_cat), recorder, base, "true")
    assert recorder.writer.events[0].data["dependency_changes"] == []
    assert any("web/package.json was truncated" in p for p in result.problems)


def test_snapshot_flags_a_truncated_diff(base_repo: tuple[Path, str], tmp_path: Path) -> None:
    repo, base = base_repo
    _write(repo, {"src/calc.py": "changed = True\n"})
    cut = _rewriting("set -eu", lambda r: dataclasses.replace(r, stdout_truncated=True))
    recorder = _recorder(tmp_path)
    result = take_snapshot(SubprocessSandbox(repo, rewrite=cut), recorder, base, "true")
    assert result.diff_seq == 0
    assert any("the file list is partial" in p for p in result.problems)


def test_snapshot_manifest_added_deleted_and_renamed(
    git_repo: Path, commit: Callable[[Path, str], str], tmp_path: Path
) -> None:
    _write(
        git_repo,
        {
            "requirements.txt": "click>=8\n",
            "deps.txt": "attrs>=23\n" * 1,
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx>=0.27"]\n',
        },
    )
    base = commit(git_repo, "base")
    (git_repo / "requirements.txt").rename(git_repo / "requirements.bak")
    (git_repo / "deps.txt").rename(git_repo / "requirements-dev.txt")
    (git_repo / "pyproject.toml").unlink()
    _write(git_repo, {"web/package.json": json.dumps({"devDependencies": {"jest": "^29.7.0"}})})
    recorder = _recorder(tmp_path)
    result = take_snapshot(SubprocessSandbox(git_repo), recorder, base, "true")
    assert result.diff_seq == 0
    changes = [
        (c["manifest"], c["name"], c["change"])
        for c in recorder.writer.events[0].data["dependency_changes"]
    ]
    assert sorted(changes) == [
        ("pyproject.toml", "httpx", "removed"),
        ("requirements-dev.txt", "attrs", "added"),
        ("requirements.txt", "click", "removed"),
        ("web/package.json", "jest", "added"),
    ]


def test_diff_script_quotes_the_base_and_prints_the_separator() -> None:
    script = diff_script("main@{1}")
    assert "'main@{1}'" in script
    assert f"echo {SEPARATOR}" in script
    assert "GIT_INDEX_FILE" in script and INDEX_NAME in script


def test_fake_sandbox_satisfies_the_protocol(tmp_path: Path) -> None:
    sandbox = SubprocessSandbox(tmp_path)
    assert isinstance(sandbox, Sandbox)
    assert sandbox.backend == "fake" and sandbox.workspace == tmp_path
    echoed = sandbox.run("cat", stdin="hi")
    assert (echoed.stdout, echoed.exit_code) == ("hi", 0)
    assert fixture("pytest/quiet_pass.txt").endswith("8 passed in 0.05s\n")
