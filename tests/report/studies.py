"""SYNTHETIC study repositories whose artifacts are written by the real analysis tools.

The re-derivation tests (``tests/report/test_derived.py`` and the G7 to G9 gate tests)
need artifacts that are what their committed scripts write, so that a fresh derivation
can equal them, and so that a value typed in afterwards is the only difference. Each
builder here makes a throwaway git repository from the SYNTHETIC fixtures of the tool's
own tests, copies in the tool and the tools modules it imports, and runs the tool as its
operator does: ``python tools/<script> [arguments]`` from the repository root, so the
recorded command names no ``--root``. Every row, run, ledger, transcript, judge reply,
and result here is SYNTHETIC; none is a model result or a real-world result.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

import receipts
import run_judges
from tests.repo_tools import test_analyze as analyze_fixtures
from tests.repo_tools import test_analyze_e4 as e4_fixtures
from tests.repo_tools import test_run_judges as judge_fixtures

#: This repository.
REPO = Path(__file__).resolve().parents[2]
#: Where the receipts package that this test process runs comes from.
SRC = Path(str(receipts.__file__)).resolve().parents[1]
E1 = "artifacts/e1/results.json"
E2 = "artifacts/e2/mechanism.json"
E3 = "artifacts/e3/judges.json"
E3_REPLIES = "artifacts/e3/replies.jsonl"
E4 = "artifacts/e4/results.json"


def git(root: Path, *args: str) -> str:
    """``git -C root <args>`` stdout; raises when git fails."""
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def new_repo(root: Path) -> Path:
    """An empty git repository at ``root`` with a local identity, ignoring ``/runs/`` as
    this repository does (the pid file, the response cache, the live failure log)."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text("/runs/\n", encoding="utf-8")
    return root


def commit_all(root: Path, message: str) -> str:
    """Commit everything in ``root`` and return the new commit."""
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def fresh_clone(root: Path, to: Path) -> Path:
    """A fresh clone of ``root`` at ``to`` (another absolute path, without ``/runs/``)."""
    subprocess.run(["git", "clone", "-q", str(root), str(to)], check=True)
    return to


def copy_tools(root: Path, *names: str) -> None:
    """Copy this repository's ``tools/<name>`` files to ``root/tools/``."""
    (root / "tools").mkdir(exist_ok=True)
    for name in names:
        shutil.copyfile(REPO / "tools" / name, root / "tools" / name)


def environment() -> dict[str, str]:
    """The environment of a tool run here: this process's, with the receipts package it
    imports first on the path."""
    paths = [str(SRC), *filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep))]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}


def operator(root: Path, *argv: str) -> None:
    """Run ``python <argv>`` in ``root`` as the tool's operator does; it must succeed."""
    proc = subprocess.run(
        [sys.executable, *argv],
        cwd=root,
        env=environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def edit(root: Path, rel: str, change: Callable[[dict[str, Any]], None]) -> None:
    """Change the JSON artifact ``rel`` in place, as a hand edit would."""
    path = root / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def e1_study(root: Path) -> Path:
    """A SYNTHETIC E1 study banked after a frozen preregistration (the fixture of
    tests/repo_tools/test_analyze.py) with the E1 and E2 artifacts: E1 from an
    exploratory run with 10 bootstrap resamples (``tools/analyze.py e1 --n-boot 10``,
    which keeps the test fast), E2 with its default arguments."""
    new_repo(root)
    analyze_fixtures.freeze_inputs(root, commit_all)  # copies tools/analyze.py too
    copy_tools(root, "prereg.py", "gitutil.py")  # tools/analyze.py imports them
    commit_all(root, "SYNTHETIC E1 rows and runs, banked after the freeze")
    operator(root, "tools/analyze.py", "e1", "--n-boot", "10")
    operator(root, "tools/analyze.py", "e2")
    commit_all(root, "SYNTHETIC E1 and E2 artifacts")
    return root


def e3_study(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """SYNTHETIC E1 rows and transcripts judged by two SYNTHETIC judges (the fixture of
    tests/repo_tools/test_run_judges.py): ``tools/run_judges.py`` run from the
    repository root with its default arguments, which writes ``artifacts/e3/judges.json``
    and the banked replies."""
    new_repo(root)
    judge_fixtures.setup(root)
    copy_tools(root, "run_judges.py")
    commit_all(root, "SYNTHETIC E1 rows, transcripts, and E3 preregistration")
    monkeypatch.setattr(run_judges, "ROOT", root)  # its default root: no --root recorded
    monkeypatch.setattr(run_judges, "serve", judge_fixtures.fake_serve)
    with redirect_stdout(io.StringIO()):
        assert run_judges.main([]) == 0
    commit_all(root, "SYNTHETIC E3 artifact and replies")
    return root


def e4_study(root: Path) -> Path:
    """A SYNTHETIC E4 study (the fixture of tests/repo_tools/test_analyze_e4.py) analyzed
    by ``tools/analyze_e4.py`` with its preregistered settings."""
    new_repo(root)
    e4_fixtures.layout(root)
    copy_tools(root, "analyze_e4.py")
    commit_all(root, "SYNTHETIC E4 rows, runs, plans, and preregistration")
    operator(root, "tools/analyze_e4.py")
    commit_all(root, "SYNTHETIC E4 results")
    return root
