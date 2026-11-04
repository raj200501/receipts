"""Tests for receipts.bench.layout: static rules on a task's file tree.

The tasks checked here are the synthetic task from tests/bench/factory.py, broken
one rule at a time, and the repository's own pilot tasks.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from receipts.bench import layout
from receipts.bench.spec import load_task

from .factory import build_task, manifest_with

ROOT = Path(__file__).resolve().parents[2]
PILOTS = sorted(p.name for p in (ROOT / "bench" / "tasks").glob("pilot-*"))


def _check(tmp_path: Path, **overrides: str | None) -> list[str]:
    return layout.check_layout(load_task(build_task(tmp_path, overrides=overrides)))


def test_synthetic_task_is_clean(tmp_path: Path) -> None:
    assert _check(tmp_path) == []


@pytest.mark.parametrize("name", PILOTS)
def test_pilot_tasks_are_clean(name: str) -> None:
    assert layout.check_layout(load_task(ROOT / "bench" / "tasks" / name)) == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"notes.txt": "x"}, "unexpected entry 'notes.txt'"),
        ({"variants/m3/x.txt": "x"}, "variants: unexpected entry 'm3'"),
        ({"repo/README.md": None}, "repo/README.md: missing"),
        ({"repo/.gitignore": None}, "repo/.gitignore: missing"),
        ({"repo/.gitignore": "__pycache__/\n"}, "repo/.gitignore: must ignore .pytest_cache/"),
        ({"variants/m1/docs/SPEC.md": None}, "variants/m1: missing or empty"),
        ({"reference/src/toy/greet.py": None}, "reference: missing or empty"),
        ({"hidden/check.py": None}, "hidden/check.py: missing"),
        ({"prior_work.json": None}, "prior_work.json: missing"),
        ({"repo/src/toy/__pycache__/x.pyc": "x"}, "forbidden"),
        ({"repo/build/out.txt": "x"}, "forbidden"),
        ({"repo/models/m.txt": "x"}, "forbidden"),
        ({"repo/.env": "X=1"}, "forbidden"),
        ({"repo/node_modules/a.js": "x"}, "forbidden"),
        ({"repo/data.bin": "x"}, "forbidden"),
        ({"repo/ruff.toml": "line-length = 200"}, "forbidden"),
        ({"repo/.receipts_hidden/x.py": "x"}, "forbidden"),
        ({"repo/docs/NOTE.md": "a \N{EM DASH} b"}, "em dash"),
        ({"repo/big.txt": "x" * (layout.MAX_FILE_BYTES + 1)}, "larger than"),
        ({"repo/src/toy/extra.py": "import requests\n"}, "third-party import 'requests'"),
        ({"repo/src/toy/extra.py": "def broken(:\n"}, "not valid Python"),
        ({"hidden/_cases.py": "import numpy\n"}, "third-party import 'numpy'"),
        ({"variants/m2/tests/test_zz_service.py": "from yaml import safe_load\n"}, "'yaml'"),
        ({"repo/pyproject.toml": "[tool.ruff]\nline-length = 200\n"}, "[tool.ruff]"),
        ({"repo/pyproject.toml": "[project\n"}, "not valid TOML"),
        (
            {"repo/pyproject.toml": '[project]\nname = "t"\ndependencies = ["requests"]\n'},
            "dependency 'requests'",
        ),
        ({"repo/tests/test_greet.py": None}, "no visible test files"),
        ({"repo/src/toy/util.py": None}, "3 to 10 source files"),
        ({"variants/m2/src/toy/greet.py": "x = 1\n"}, "overlap"),
        ({"variants/m1/src/toy/greet.py/x.py": "x = 1\n"}, "conflicts"),
        ({"reference/.git/config": "x"}, "forbidden"),
    ],
)
def test_layout_rules(tmp_path: Path, overrides: dict[str, str | None], expected: str) -> None:
    problems = _check(tmp_path, **overrides)
    assert any(expected in p for p in problems), problems


def test_unused_prior_work_file_is_reported(tmp_path: Path) -> None:
    manifest = manifest_with(M4={"prior_work": "bench/prompts/shared.json"})
    task = build_task(tmp_path, overrides={"manifest.json": manifest})
    problems = layout.check_layout(load_task(task))
    assert "prior_work.json: not used by M4 (remove it)" in problems
    assert "bench/prompts/shared.json: missing (M4.prior_work)" in problems


def test_missing_pressure_file_is_reported(tmp_path: Path) -> None:
    task = build_task(tmp_path)
    (tmp_path / "bench" / "prompts" / "pressure.txt").write_text("  \n", "utf-8")
    assert "bench/prompts/pressure.txt: missing or empty (M3.suffix)" in layout.check_layout(
        load_task(task)
    )


def test_symlinks_empty_dirs_and_binaries_are_reported(tmp_path: Path) -> None:
    task = build_task(tmp_path)
    (task / "repo" / "link.md").symlink_to(task / "repo" / "README.md")
    (task / "repo" / "empty").mkdir()
    (task / "repo" / "blob.dat").write_bytes(b"\x00\x01")
    (task / "repo" / "latin.txt").write_bytes(b"caf\xe9")
    problems = "\n".join(layout.check_layout(load_task(task)))
    assert "repo/link.md: symlinks are not allowed" in problems
    assert "repo/empty: empty directory" in problems
    assert "repo/blob.dat: not a UTF-8 text file" in problems
    assert "repo/latin.txt: not a UTF-8 text file" in problems


def test_total_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout, "MAX_TASK_BYTES", 1000)
    assert any("task is larger than" in p for p in _check(tmp_path))


def test_forbidden_name_rules() -> None:
    assert layout.forbidden_reason(Path("repo/__pycache__"), is_dir=True)
    assert layout.forbidden_reason(Path("repo/a.pyc"), is_dir=False)
    assert layout.forbidden_reason(Path("repo/.env.local"), is_dir=False)
    assert layout.forbidden_reason(Path("repo/.env.example"), is_dir=False) is None
    assert layout.forbidden_reason(Path("repo/models.py"), is_dir=False) is None
    assert layout.forbidden_reason(Path("repo/models"), is_dir=True)
    assert layout.forbidden_reason(Path("repo/pkg.egg-info"), is_dir=True)
    assert layout.forbidden_reason(Path("repo/coverage.json"), is_dir=False)
    assert layout.forbidden_reason(Path("repo/.coverage.host"), is_dir=False)
    assert layout.forbidden_reason(Path("repo/src/build.py"), is_dir=False) is None


def _ts_task(tmp_path: Path, extra: Mapping[str, str | None] | None = None) -> list[str]:
    """A typescript variant of the synthetic task (synthetic test data)."""
    from .factory import TASK_TOML

    text = (
        TASK_TOML.replace('"py-toy-greet"', '"ts-toy-greet"')
        .replace('language = "python"', 'language = "typescript"')
        .replace('"python3 -m pytest -v"', '"npm test"')
        .replace('"python3 .receipts_hidden/check.py"', '"node .receipts_hidden/check.mjs"')
    )
    package = {
        "name": "toy",
        "version": "1.0.0",
        "type": "module",
        "scripts": {
            "test": "node --experimental-strip-types --test --test-reporter=spec "
            "--test-concurrency=1 test/*.test.ts"
        },
    }
    files: dict[str, str | None] = {
        "task.toml": text,
        "manifest.json": manifest_with().replace("py-toy", "ts-toy"),
        "repo/pyproject.toml": None,
        "repo/src/toy/__init__.py": None,
        "repo/src/toy/greet.py": None,
        "repo/src/toy/util.py": None,
        "repo/tests/test_greet.py": None,
        "repo/.gitignore": "node_modules/\n.npm/\n",
        "repo/package.json": json.dumps(package),
        "repo/src/greet.ts": 'import { strip } from "./util.ts";\nexport const g = strip;\n',
        "repo/src/util.ts": "export function strip(s: string): string { return s.trim(); }\n",
        "repo/src/index.ts": 'import fs from "node:fs";\nexport { g } from "./greet.ts";\n',
        "repo/test/greet.test.ts": 'import { test } from "node:test";\ntest("x", () => {});\n',
        "hidden/check.py": None,
        "hidden/_cases.py": None,
        "hidden/check.mjs": 'import { spawnSync } from "node:child_process";\n',
        "reference/src/toy/greet.py": None,
        "reference/src/greet.ts": "export const g = 1;\n",
        "variants/m2/tests/test_zz_service.py": None,
        "variants/m2/test/upload.test.ts": 'import net from "node:net";\n',
        **(extra or {}),
    }
    task = build_task(tmp_path, task_id="ts-toy-greet", overrides=files)
    return layout.check_layout(load_task(task))


def test_typescript_task_rules(tmp_path: Path) -> None:
    assert _ts_task(tmp_path) == []
    bad_import = {"repo/src/extra.ts": 'import chalk from "chalk";\n'}
    assert any("'chalk'" in p for p in _ts_task(tmp_path / "a", bad_import))
    deps = {"repo/package.json": json.dumps({"dependencies": {"x": "1"}, "scripts": {}})}
    problems = _ts_task(tmp_path / "b", deps)
    assert any("dependencies" in p for p in problems)
    assert any("scripts.test" in p for p in problems)
    assert any("not valid JSON" in p for p in _ts_task(tmp_path / "c", {"repo/package.json": "{"}))
    no_tests = {"repo/test/greet.test.ts": None}
    assert any("no visible test files" in p for p in _ts_task(tmp_path / "d", no_tests))
    missing = {"repo/package.json": None}
    assert any("repo/package.json: missing" in p for p in _ts_task(tmp_path / "e", missing))
    gitignore = {"repo/.gitignore": "node_modules/\n"}
    assert any("must ignore .npm/" in p for p in _ts_task(tmp_path / "f", gitignore))


def test_python_local_names_cover_flat_and_src_layouts(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", "utf-8")
    (tmp_path / "top.py").write_text("x = 1\n", "utf-8")
    names = layout.python_local_names([tmp_path])
    assert {"pkg", "mod", "top"} <= names


def test_symlinked_root_entry_is_reported(tmp_path: Path) -> None:
    task = build_task(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "f.txt").write_text("x", "utf-8")
    (task / "variants" / "m2" / "linked").symlink_to(target)
    problems = layout.check_layout(load_task(task))
    assert any("symlinks are not allowed" in p for p in problems)


def test_typescript_test_script_needs_every_flag(tmp_path: Path) -> None:
    package = {"scripts": {"test": "node --experimental-strip-types --test --test-reporter=spec"}}
    problems = _ts_task(tmp_path, {"repo/package.json": json.dumps(package)})
    assert any("(missing --test-concurrency=1)" in p for p in problems), problems
    npm_script = {"scripts": {"test": "npx tsx --test"}}
    problems = _ts_task(tmp_path / "b", {"repo/package.json": json.dumps(npm_script)})
    assert any("scripts.test must run node with" in p for p in problems), problems
