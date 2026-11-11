"""``receipts wrap`` end to end: real git workspaces, a real pytest rerun, real verdicts.

Every workspace, agent edit, and report here is a synthetic test fixture. The agent is
a function that edits files and returns a report, except in the ``main`` tests, which
run a real ``python -c`` subprocess as the agent. Tests run through the fake
``SubprocessSandbox`` of the ledger tests, which confines nothing and is used only for
these fixture commands.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from receipts.claims.types import ClaimType
from receipts.hook.wrap import WrapResult, main, start_state, wrap
from receipts.ledger.events import Ledger
from receipts.verify import Label
from tests.ledger.helpers import SubprocessSandbox

TEST_CMD = f"{sys.executable} -m pytest -q -p no:cacheprovider"
Runner = Callable[[Sequence[str], Path], tuple[int, str]]


def git(workspace: Path, *args: str) -> str:
    """Run git in ``workspace`` with a fixed identity and no user configuration."""
    return subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
    ).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A committed repository with one module and one passing test."""
    ws = tmp_path / "calc"
    (ws / "tests").mkdir(parents=True)
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    (ws / ".gitignore").write_text("*.log\n", encoding="utf-8")
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "start")
    return ws


def agent(report: str, edits: Mapping[str, str] | None = None, exit_code: int = 0) -> Runner:
    """A stand-in agent: writes ``edits`` into the workspace, then reports."""

    def run(command: Sequence[str], workspace: Path) -> tuple[int, str]:
        del command
        for rel, text in (edits or {}).items():
            path = workspace / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return exit_code, report

    return run


def run_wrap(workspace: Path, tmp_path: Path, runner: Runner, **kwargs: Path) -> WrapResult:
    return wrap(
        ["fake-agent"],
        workspace,
        TEST_CMD,
        tmp_path / "run.jsonl",
        SubprocessSandbox(workspace),
        runner=runner,
        **kwargs,
    )


def labels(result: WrapResult) -> dict[ClaimType, set[Label]]:
    out: dict[ClaimType, set[Label]] = {}
    verification = result.verification
    for claim, verdict in zip(verification.claims, verification.verdicts, strict=True):
        out.setdefault(claim.type, set()).add(verdict.label)
    return out


def test_command_claims_are_unverifiable_and_the_snapshot_settles_the_rest(
    workspace: Path, tmp_path: Path
) -> None:
    (workspace / "notes.txt").write_text("untracked before the run\n", encoding="utf-8")
    new_test = "from calc import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n"
    report = "I ran `pytest -q` and all tests pass. I added tests/test_zero.py."
    result = run_wrap(workspace, tmp_path, agent(report, {"tests/test_zero.py": new_test}))

    found = labels(result)
    assert found[ClaimType.RAN_COMMAND] == {Label.UNVERIFIABLE}
    assert found[ClaimType.TESTS_PASS] == {Label.SUPPORTED}
    assert Label.CONTRADICTED not in set().union(*found.values())
    ledger = Ledger.load(tmp_path / "run.jsonl")
    start = ledger.run_start()
    assert start is not None and start.data["records_agent_commands"] is False
    (diff,) = ledger.of_kind("diff")
    paths = {f["path"]: f["status"] for f in diff.data["files"]}
    assert paths == {"tests/test_zero.py": "A"}  # notes.txt was there before the run
    assert result.exit_code == 0 and result.report == report
    assert "[unverifiable] I ran `pytest -q`" in result.annotation
    assert "no record of the agent's commands" in result.annotation
    assert "0 contradicted" in result.annotation


def test_a_failing_rerun_contradicts_the_report_and_the_exit_code_passes_through(
    workspace: Path, tmp_path: Path
) -> None:
    broken = {"calc.py": "def add(a, b):\n    return a - b\n"}
    result = run_wrap(workspace, tmp_path, agent("Fixed it. All tests pass.", broken, exit_code=3))

    assert labels(result)[ClaimType.TESTS_PASS] == {Label.CONTRADICTED}
    assert "[CONTRADICTED] All tests pass." in result.annotation
    assert "1 contradicted" in result.annotation
    assert result.exit_code == 3
    end = Ledger.load(tmp_path / "run.jsonl").of_kind("run_end")[-1]
    assert end.data["stop_reason"] == "exit 3"


def test_the_report_file_wins_over_stdout_and_an_old_ledger_is_replaced(
    workspace: Path, tmp_path: Path
) -> None:
    (tmp_path / "run.jsonl").write_text("not a ledger\n", encoding="utf-8")
    report_file = tmp_path / "report.md"
    report_file.write_text("All tests pass.\n", encoding="utf-8")
    result = run_wrap(
        workspace, tmp_path, agent("stdout is not the report"), report_file=report_file
    )

    assert result.report == "All tests pass.\n"
    assert labels(result) == {ClaimType.TESTS_PASS: {Label.SUPPORTED}}
    assert Ledger.load(tmp_path / "run.jsonl").events[0].kind == "run_start"


def test_a_report_without_claims_says_so(workspace: Path, tmp_path: Path) -> None:
    result = run_wrap(workspace, tmp_path, agent("Hello."))

    assert "no checkable claims found in the report" in result.annotation
    assert result.annotation.rstrip().endswith("0 supported, 0 contradicted, 0 unverifiable")


def test_start_state_holds_untracked_and_modified_files_and_changes_nothing(
    workspace: Path,
) -> None:
    head = git(workspace, "rev-parse", "HEAD")
    assert start_state(workspace) == head  # nothing uncommitted: HEAD itself

    (workspace / "calc.py").write_text("def add(a, b):\n    return b + a\n", encoding="utf-8")
    (workspace / "notes.txt").write_text("draft\n", encoding="utf-8")
    (workspace / "debug.log").write_text("ignored by .gitignore\n", encoding="utf-8")
    status = git(workspace, "status", "--porcelain")
    commit = start_state(workspace)

    assert commit != head
    assert git(workspace, "rev-parse", f"{commit}^") == head
    files = set(git(workspace, "ls-tree", "-r", "--name-only", commit).splitlines())
    assert {"calc.py", "notes.txt", ".gitignore", "tests/test_calc.py"} <= files
    assert "debug.log" not in files
    assert "b + a" in git(workspace, "show", f"{commit}:calc.py")
    assert git(workspace, "status", "--porcelain") == status  # working tree and index
    assert git(workspace, "stash", "list") == ""
    assert git(workspace, "rev-parse", "HEAD") == head


def test_main_runs_a_real_agent_process_and_prints_report_and_verdicts(
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "receipts.sandbox.select.make_sandbox", lambda ws, policy: SubprocessSandbox(ws)
    )
    script = "import sys; print('All tests pass.'); print('agent log', file=sys.stderr)"
    argv = ["--workspace", str(workspace), "--test-cmd", TEST_CMD, "--", sys.executable, "-c"]
    code = main([*argv, script])

    out, err = capsys.readouterr()
    assert code == 0
    assert out.startswith("All tests pass.\n")
    assert "---- receipts ----" in out and "[ok] All tests pass." in out
    assert "agent log" in err  # the agent's stderr is passed through
    assert (tmp_path / f".receipts-{workspace.name}.jsonl").is_file()  # default ledger


def test_main_requires_an_agent_command(workspace: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--workspace", str(workspace), "--test-cmd", TEST_CMD, "--"])
    assert exc.value.code == 2
