"""The receipts-bench canary (``receipts.bench.canary``, ``tools/bench_canary.py``).

The task directories built here are synthetic test fixtures; the last test checks the
real benchmark under bench/tasks/.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

import bench_canary
from receipts.bench.canary import (
    CANARY,
    add_canary,
    canary_problems,
    canary_targets,
    comment_for,
    remove_canary,
    with_canary,
    without_canary,
)
from receipts.bench.hashing import tree_sha256

ROOT = Path(__file__).resolve().parents[2]


def task(tmp_path: Path) -> Path:
    """A synthetic task with agent-visible, answer-key, and data files."""
    files = {
        "task.toml": 'id = "t1"\n',
        "repo/app.py": "def f():\n    return 1\n",
        "repo/README.md": "# App\n",
        "variants/m2/app.py": "def f():\n    return 2\n",
        "prior_work.json": '{"turns": []}\n',
        "hidden/check.py": '"""Hidden check."""\n',
        "hidden/run.mjs": "export const x = 1;\n",
        "hidden/golden.json": '{"a": 1}\n',
        "reference/app.py": "#!/usr/bin/env python3\ndef f():\n    return 3\n",
        "reference/README.md": "# App\n",  # identical to repo/README.md
        "reference/docs/usage.md": "# Usage\n\nRun it.\n",
    }
    root = tmp_path / "t1"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_comment_syntax_by_file_type() -> None:
    assert comment_for(PurePosixPath("a.py")) == f"# {CANARY}  # noqa: E501"
    assert comment_for(PurePosixPath("a.ts")) == f"// {CANARY}"
    assert comment_for(PurePosixPath("a.md")) == f"<!-- {CANARY} -->"
    assert comment_for(PurePosixPath("a.json")) is None
    with pytest.raises(ValueError, match="no comment syntax"):
        with_canary("{}", PurePosixPath("a.json"))


def test_placement_keeps_shebangs_and_titles_first_and_is_idempotent() -> None:
    script = with_canary("#!/bin/sh\necho hi\n", PurePosixPath("run.py"))
    assert script.splitlines()[:2] == ["#!/bin/sh", f"# {CANARY}  # noqa: E501"]
    doc = with_canary("# Title\n\nText", PurePosixPath("doc.md"))
    assert doc.splitlines()[0] == "# Title" and doc.endswith(f"<!-- {CANARY} -->\n")
    assert with_canary(doc, PurePosixPath("doc.md")) == doc


def test_targets_are_the_definition_and_the_answer_key_only(tmp_path: Path) -> None:
    root = task(tmp_path)
    rel = {p.relative_to(root).as_posix() for p in canary_targets(root)}
    assert rel == {
        "task.toml",
        "hidden/check.py",
        "hidden/run.mjs",
        "reference/app.py",
        "reference/docs/usage.md",
    }  # no JSON, no identical reference copy, nothing the agent sees


def test_add_then_check(tmp_path: Path) -> None:
    root = task(tmp_path)
    assert len(canary_problems(root)) == 5
    assert len(add_canary(root)) == 5
    assert canary_problems(root) == []
    assert add_canary(root) == []  # idempotent
    assert CANARY not in (root / "repo" / "app.py").read_text(encoding="utf-8")


def test_removal_restores_the_exact_bytes(tmp_path: Path) -> None:
    root = task(tmp_path)
    before = tree_sha256(root)
    add_canary(root)
    assert tree_sha256(root) != before
    assert len(remove_canary(root)) == 5
    assert tree_sha256(root) == before
    assert without_canary("no canary here\n", PurePosixPath("a.py")) == "no canary here\n"


def test_a_canary_the_agent_can_see_is_a_problem(tmp_path: Path) -> None:
    root = task(tmp_path)
    add_canary(root)
    leaked = root / "variants" / "m2" / "app.py"
    leaked.write_text(f"# {CANARY}\n" + leaked.read_text(encoding="utf-8"), encoding="utf-8")
    assert canary_problems(root) == ["variants/m2/app.py: agent can see the canary"]


def test_the_tool_checks_and_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    task(tmp_path)
    assert bench_canary.main(["--tasks-dir", str(tmp_path)]) == 1
    assert bench_canary.main(["--tasks-dir", str(tmp_path), "--write"]) == 0
    assert "CANARY: PASS (1 tasks)" in capsys.readouterr().out
    assert bench_canary.main(["--tasks-dir", str(tmp_path / "none")]) == 2


def test_every_real_task_carries_the_canary_and_hides_it_from_the_agent() -> None:
    assert bench_canary.main(["--tasks-dir", str(ROOT / "bench" / "tasks")]) == 0
