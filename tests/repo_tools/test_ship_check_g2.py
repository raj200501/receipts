"""Gate G2 of tools/ship_check.py on synthetic projects (findings H04 to H06).

Every project built here is SYNTHETIC: a tiny ``receipts`` package made only to exercise
``ship_check.g2``; nothing in it is a model result or a real-world result. The projects
run the real ``make``, ruff, and mypy through ``uv run --no-sync``; their ``.venv`` is a
symlink to the venv running these tests and their ``setup`` target is a no-op.

Each case runs ruff and mypy in subprocesses, so the module is marked ``slow``.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import ship_check

Commit = Callable[[Path, str], str]

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.prefix == sys.base_prefix or not (shutil.which("uv") and shutil.which("make")),
        reason="needs make, uv, and a virtualenv to link synthetic projects to",
    ),
]

MAKEFILE = """\
# SYNTHETIC test project for tools/ship_check.py gate G2 (not a real project).
SHELL := /bin/bash
PY ?= 3.11
PYTEST_ARGS ?=
RUN := uv run --no-sync

setup:
\t@true

lint:
\t$(RUN) ruff check .
\t$(RUN) ruff format --check .

typecheck:
\t$(RUN) mypy --strict
"""

PYPROJECT = """\
# SYNTHETIC test project for tools/ship_check.py gate G2.
[project]
name = "synthetic-receipts"
version = "0"
requires-python = ">=3.11"

[tool.ruff]
line-length = 100
src = ["src"]
{ruff}
[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP"]
{lint}
[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = ["src"]
files = {files}
{mypy}"""

GOOD = '''"""Synthetic typed module."""


def double(x: int) -> int:
    """Return twice ``x``."""
    return 2 * x
'''

BAD_TYPES = '''"""Synthetic module with two mypy --strict errors."""


def double(x):
    return 2 * x


VALUE: int = "not an int"
'''

BAD_LINT = '''"""Synthetic module with two lint errors (unused import, mutable default)."""

import os


def append(item: int, items: list[int] = []) -> list[int]:
    items.append(item)
    return items
'''

MISFORMATTED = '"""Synthetic module that ruff format would change."""\n\nx  =  1\n'

STUB = """from llama_cpp import Llama  # type: ignore

def load(path: str) -> Llama: ...
"""

LOADER = '''"""Synthetic runtime loader whose types live in ext.pyi."""

from typing import Any


def load(path: str) -> Any:
    """Load a model lazily (never called here)."""
    import llama_cpp

    return llama_cpp.Llama(model_path=path)
'''


def build(
    root: Path,
    commit: Commit,
    *,
    files: dict[str, str] | None = None,
    ruff: str = "",
    lint: str = "",
    mypy_files: str = '["src/receipts"]',
    mypy: str = "",
    tables: str = "",
) -> ship_check.Context:
    """Write a SYNTHETIC G2 project into ``root``, commit it, and return its Context."""
    layout = {
        "Makefile": MAKEFILE,
        "pyproject.toml": PYPROJECT.format(ruff=ruff, lint=lint, files=mypy_files, mypy=mypy)
        + tables,
        ".gitignore": ".venv\n.mypy_cache/\n.ruff_cache/\n",
        "src/receipts/__init__.py": '"""Synthetic package."""\n',
        "src/receipts/good.py": GOOD,
    }
    layout.update(files or {})
    for rel, text in layout.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    sha = commit(root, "synthetic G2 project")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)


def test_clean_synthetic_project_passes(git_repo: Path, commit: Commit) -> None:
    assert "mypy --strict clean" in ship_check.g2(build(git_repo, commit))


def test_plain_type_errors_fail(git_repo: Path, commit: Commit) -> None:
    ctx = build(git_repo, commit, files={"src/receipts/bad.py": BAD_TYPES})
    with pytest.raises(ship_check.GateError, match="mypy --strict failed"):
        ship_check.g2(ctx)


# ---------------------------------------------------------------- H04 (old code: PASS)


@pytest.mark.parametrize(
    ("variant", "first_lines", "match"),
    [
        ("ignore-errors", "# mypy: ignore-errors\n", "relaxes --strict"),
        (
            "disable-without-reason",
            '# mypy: disable-error-code="no-untyped-def,assignment"\n',
            "without a reason",
        ),
        (
            "allow-untyped",
            '# mypy: allow-untyped-defs, disable-error-code="assignment"\n',
            "relaxes --strict",
        ),
    ],
)
def test_inline_mypy_settings_need_a_code_and_reason(
    git_repo: Path, commit: Commit, variant: str, first_lines: str, match: str
) -> None:
    ctx = build(git_repo, commit, files={"src/receipts/bad.py": first_lines + BAD_TYPES})
    with pytest.raises(ship_check.GateError, match=match):
        ship_check.g2(ctx)


def test_disable_error_code_with_a_reason_is_allowed(git_repo: Path, commit: Commit) -> None:
    header = (
        "# Reason: synthetic module-level ignore, the same rule as type: ignore[code].\n"
        '# mypy: disable-error-code="no-untyped-def,assignment"\n'
    )
    ctx = build(git_repo, commit, files={"src/receipts/bad.py": header + BAD_TYPES})
    assert "mypy --strict clean" in ship_check.g2(ctx)


def test_aliased_no_type_check_is_a_suppression(git_repo: Path, commit: Commit) -> None:
    source = (
        '"""Synthetic module silencing mypy with an aliased no_type_check."""\n\n'
        "from typing import no_type_check as unchecked\n\n\n"
        "@unchecked\ndef double(x: int) -> int:\n    y: str = x\n    return y\n"
    )
    ctx = build(git_repo, commit, files={"src/receipts/bad.py": source})
    with pytest.raises(ship_check.GateError, match="no_type_check"):
        ship_check.g2(ctx)


@pytest.mark.parametrize(
    ("variant", "mypy_files", "mypy"),
    [
        (
            "override-ignore-errors",
            '["src/receipts"]',
            '\n[[tool.mypy.overrides]]\nmodule = ["receipts.bad"]\nignore_errors = true\n',
        ),
        (
            "override-relaxed",
            '["src/receipts"]',
            '\n[[tool.mypy.overrides]]\nmodule = ["receipts.bad"]\n'
            'disallow_untyped_defs = false\ndisable_error_code = ["assignment"]\n',
        ),
        (
            "global-disable",
            '["src/receipts"]',
            'disable_error_code = ["assignment", "no-untyped-def"]\n',
        ),
        ("files-narrowed", '["src/receipts/good.py"]', ""),
        ("exclude", '["src/receipts"]', r"exclude = ['^src/receipts/bad\.py$']" + "\n"),
    ],
)
def test_mypy_config_cannot_narrow_the_package(
    git_repo: Path, commit: Commit, variant: str, mypy_files: str, mypy: str
) -> None:
    ctx = build(
        git_repo, commit, files={"src/receipts/bad.py": BAD_TYPES}, mypy_files=mypy_files, mypy=mypy
    )
    with pytest.raises(ship_check.GateError, match="mypy --strict on every package file"):
        ship_check.g2(ctx)


def test_ruff_extend_exclude_cannot_hide_package_files(git_repo: Path, commit: Commit) -> None:
    ctx = build(
        git_repo,
        commit,
        files={"src/receipts/analysis/__init__.py": '"""Synthetic."""\n'}
        | {"src/receipts/analysis/glmm.py": BAD_LINT},
        ruff='extend-exclude = ["src/receipts/analysis"]\n',
    )
    with pytest.raises(ship_check.GateError, match="ruff check on every package file"):
        ship_check.g2(ctx)


def test_nested_ruff_config_cannot_hide_package_files(git_repo: Path, commit: Commit) -> None:
    files = {
        "src/receipts/sub/__init__.py": '"""Synthetic."""\n',
        "src/receipts/sub/m.py": BAD_LINT,
        "src/receipts/sub/ruff.toml": '[lint]\nignore = ["ALL"]\n',
    }
    ctx = build(git_repo, commit, files=files)
    with pytest.raises(ship_check.GateError, match="ruff check on every package file"):
        ship_check.g2(ctx)


def test_blanket_file_level_noqa_is_a_suppression(git_repo: Path, commit: Commit) -> None:
    ctx = build(git_repo, commit, files={"src/receipts/bad.py": "# ruff: noqa\n" + BAD_LINT})
    with pytest.raises(ship_check.GateError, match="file-level noqa"):
        ship_check.g2(ctx)


def test_per_file_ignores_all_is_a_suppression(git_repo: Path, commit: Commit) -> None:
    ctx = build(
        git_repo,
        commit,
        files={"src/receipts/bad.py": BAD_LINT},
        lint='per-file-ignores = {"src/receipts/bad.py" = ["ALL"]}\n',
    )
    with pytest.raises(ship_check.GateError, match=r"= ALL silences src/receipts/bad\.py"):
        ship_check.g2(ctx)


def test_format_exclude_cannot_hide_package_files(git_repo: Path, commit: Commit) -> None:
    ctx = build(
        git_repo,
        commit,
        files={"src/receipts/messy.py": MISFORMATTED},
        tables='\n[tool.ruff.format]\nexclude = ["src/receipts/messy.py"]\n',
    )
    with pytest.raises(ship_check.GateError, match="ruff format --check on every package file"):
        ship_check.g2(ctx)


# ---------------------------------------------------------------- H05 (old code: PASS)


def test_bare_type_ignore_in_a_stub_is_audited(git_repo: Path, commit: Commit) -> None:
    files = {"src/receipts/ext.pyi": STUB, "src/receipts/ext.py": LOADER}
    ctx = build(git_repo, commit, files=files)
    with pytest.raises(ship_check.GateError, match=r"src/receipts/ext\.pyi:1"):
        ship_check.g2(ctx)


# ---------------------------------------------------------------- H06 (old code: FAIL)


def test_type_ignore_grammar_matches_mypy(git_repo: Path, commit: Commit) -> None:
    source = (
        '"""Synthetic module: a reason with no space, and prose that names the rule."""\n\n'
        'B: int = "s"  # type: ignore[assignment]# no space before the reason\n'
        'C: int = 1  # see the "# type: ignore" policy\n'
    )
    ctx = build(git_repo, commit, files={"src/receipts/ok.py": source})
    assert "every type: ignore has a code and reason" in ship_check.g2(ctx)
