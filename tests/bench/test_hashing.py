"""Tests for receipts.bench.hashing (the task tree hash shared with tools/ship_check.py).

Every tree built here is synthetic test data written by this suite.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import ship_check
from receipts.bench import hashing

TASKS = Path(__file__).resolve().parents[2] / "bench" / "tasks"
ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"


def _write(root: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_file_sha256_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"synthetic\n")
    assert hashing.file_sha256(path) == hashlib.sha256(b"synthetic\n").hexdigest()


def test_tree_sha256_follows_the_documented_formula(tmp_path: Path) -> None:
    _write(tmp_path, {"b.txt": b"two", "a/x.py": b"one"})
    digest = hashlib.sha256()
    for rel, data in (("a/x.py", b"one"), ("b.txt", b"two")):
        digest.update(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    assert hashing.tree_sha256(tmp_path) == digest.hexdigest()


def test_tree_sha256_matches_ship_check_on_tricky_names(tmp_path: Path) -> None:
    # Path-part order and string order differ for these names ("a-b/c" vs "a/b").
    _write(
        tmp_path,
        {
            "a/b": b"1",
            "a-b/c": b"2",
            "a.b": b"3",
            "A/z": b"4",
            "deep/er/still/f.txt": b"5",
            f"unicode/{ACUTE}t{ACUTE}.md": ACUTE.encode(),
            ".hidden/file": b"6",
        },
    )
    (tmp_path / "empty-dir").mkdir()
    assert hashing.tree_sha256(tmp_path) == ship_check.tree_sha256(tmp_path)


def test_tree_sha256_ignores_empty_directories_and_sees_every_change(tmp_path: Path) -> None:
    _write(tmp_path, {"x/y.txt": b"content"})
    before = hashing.tree_sha256(tmp_path)
    (tmp_path / "x" / "empty").mkdir()
    assert hashing.tree_sha256(tmp_path) == before
    (tmp_path / "x" / "y.txt").write_bytes(b"changed")
    changed = hashing.tree_sha256(tmp_path)
    assert changed != before
    (tmp_path / "x" / "y.txt").rename(tmp_path / "x" / "z.txt")
    assert hashing.tree_sha256(tmp_path) not in (before, changed)


def test_tree_sha256_of_an_empty_directory(tmp_path: Path) -> None:
    assert hashing.tree_sha256(tmp_path) == hashlib.sha256(b"").hexdigest()


def test_tree_sha256_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        hashing.tree_sha256(tmp_path / "missing")


@pytest.mark.parametrize("task", sorted(p.name for p in TASKS.glob("pilot-*")))
def test_pilot_task_hashes_match_ship_check(task: str) -> None:
    assert hashing.tree_sha256(TASKS / task) == ship_check.tree_sha256(TASKS / task)


def test_text_sha256() -> None:
    assert hashing.text_sha256("abc") == hashlib.sha256(b"abc").hexdigest()
