"""Static rules on a benchmark task's file tree (no code is run).

:func:`check_layout` returns one plain sentence per broken rule, each starting
with the path it is about (relative to the task directory, or to the repository
root for shared files). docs/BENCH.md explains every rule; in short:

- the task directory holds exactly ``task.toml``, ``manifest.json``, ``repo/``,
  ``hidden/``, ``reference/``, ``variants/m1/``, ``variants/m2/``, and
  ``prior_work.json`` when M4 uses it;
- every file is UTF-8 text without NUL bytes or em dashes, at most
  :data:`MAX_FILE_BYTES` (the whole task at most :data:`MAX_TASK_BYTES`); there are
  no symlinks, no empty directories, and no names the repository's ``.gitignore``
  drops (git would silently leave them out of every clone, changing the task);
- ``repo/`` is a small realistic repository: a README, a ``.gitignore`` for test
  caches, 3 to 10 source files, visible tests, no third-party dependencies
  (Python: the standard library and pytest; TypeScript: ``node:`` built-ins and
  relative imports only);
- the overlays (``reference/``, ``variants/m1/``, ``variants/m2/``) touch pairwise
  disjoint files, so any combination of them can be applied in any order.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from receipts.bench.spec import PRIOR_WORK_FILE, TaskSpec

MAX_FILE_BYTES = 200_000
MAX_TASK_BYTES = 2_000_000
SOURCE_FILES_RANGE: tuple[int, int] = (3, 10)
ROOT_ENTRIES = frozenset(
    {"task.toml", "manifest.json", "repo", "hidden", "reference", "variants", PRIOR_WORK_FILE}
)
VARIANT_ENTRIES = frozenset({"m1", "m2"})
REQUIRED_DIRS: tuple[str, ...] = ("repo", "hidden", "reference", "variants/m1", "variants/m2")
OVERLAYS: tuple[str, ...] = ("reference", "variants/m1", "variants/m2")
GITIGNORE_LINES: Mapping[str, tuple[str, ...]] = {
    "python": ("__pycache__/", ".pytest_cache/"),
    "typescript": ("node_modules/", ".npm/"),
}
PYTHON_ALLOWED: frozenset[str] = frozenset(sys.stdlib_module_names) | {
    "__future__",
    "pytest",
    "_pytest",
}
PYTHON_DEPENDENCIES_ALLOWED = frozenset({"pytest"})
#: Flags the TypeScript test script needs: type stripping, the test runner, a fixed
#: reporter (the default differs between terminals and pipes), and one test file at a
#: time (so the output order, and with it the M2 truncation point, never changes).
NODE_TEST_FLAGS: tuple[str, ...] = (
    "--experimental-strip-types",
    "--test",
    "--test-reporter=spec",
    "--test-concurrency=1",
)
NPM_DEPENDENCY_KEYS: tuple[str, ...] = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
    "bundleDependencies",
    "bundledDependencies",
)
EM_DASH = "\N{EM DASH}"

# Names the repository's .gitignore drops at any depth (a fresh clone would lack
# them), plus caches, version-control data, and lint configuration.
_IGNORED_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "dist",
        "build",
        "models",
        ".ollama",
        ".idea",
        ".vscode",
        "private",
        "runs",
    }
)
_IGNORED_FILES = frozenset({".DS_Store", ".coverage", "coverage.json"})
_IGNORED_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".gguf",
    ".safetensors",
    ".bin",
    ".pt",
    ".onnx",
)
_OTHER_DIRS = frozenset({".git", "node_modules", "venv", ".receipts_hidden"})
_OTHER_FILES = frozenset({".git", "ruff.toml", ".ruff.toml", ".receipts_hidden"})
_TS_SPECIFIER = re.compile(
    r"""(?:\bfrom\s+|\bimport\s*\(?\s*|\brequire\s*\(\s*)(["'])([^"'\n]+)\1"""
)
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass(frozen=True)
class _Entry:
    rel: PurePosixPath
    path: Path
    is_dir: bool
    is_symlink: bool


def forbidden_reason(rel: Path | PurePosixPath, *, is_dir: bool) -> str | None:
    """Why a file or directory name may not appear in a task, or None when it may."""
    name = rel.name
    if name.startswith(".env") and name != ".env.example":
        return "ignored by the repository's .gitignore (git would drop it from every clone)"
    if is_dir:
        if name in _IGNORED_DIRS or name.endswith(".egg-info"):
            return "ignored by the repository's .gitignore (git would drop it from every clone)"
        if name in _OTHER_DIRS:
            return "version-control data, installed packages, or a reserved name"
        return None
    if name in _IGNORED_FILES or name.startswith(".coverage.") or name.endswith(_IGNORED_SUFFIXES):
        return "ignored by the repository's .gitignore (git would drop it from every clone)"
    if name in _OTHER_FILES:
        return "version-control data, lint configuration, or a reserved name"
    return None


def _walk(root: Path) -> list[_Entry]:
    """Every entry under ``root`` (not following symlinks), sorted by path."""
    entries: list[_Entry] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        for name in [*dirnames, *filenames]:
            path = base / name
            rel = PurePosixPath(path.relative_to(root).as_posix())
            link = path.is_symlink()
            entries.append(_Entry(rel, path, is_dir=path.is_dir() and not link, is_symlink=link))
    return sorted(entries, key=lambda e: e.rel.parts)


def _files_under(root: Path) -> list[PurePosixPath]:
    """Regular files under ``root`` relative to it (empty when ``root`` is missing)."""
    if not root.is_dir():
        return []
    return [e.rel for e in _walk(root) if not e.is_dir and not e.is_symlink]


def _check_tree(task: TaskSpec, out: list[str]) -> None:
    total = 0
    for entry in _walk(task.root):
        rel = entry.rel.as_posix()
        if entry.is_symlink:
            out.append(f"{rel}: symlinks are not allowed")
            continue
        reason = forbidden_reason(entry.rel, is_dir=entry.is_dir)
        if reason:
            out.append(f"{rel}: forbidden name ({reason})")
        if entry.is_dir:
            if not any(entry.path.iterdir()):
                out.append(f"{rel}: empty directory (git does not keep it)")
            continue
        size = entry.path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            out.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes")
            continue
        data = entry.path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is None or "\0" in text:
            out.append(f"{rel}: not a UTF-8 text file")
            continue
        if EM_DASH in text:
            out.append(f"{rel}: contains an em dash (use commas, colons, or parentheses)")
    if total > MAX_TASK_BYTES:
        out.append(f"task is larger than {MAX_TASK_BYTES} bytes ({total})")


def _check_entries(task: TaskSpec, out: list[str]) -> None:
    for path in sorted(task.root.iterdir()):
        if path.name not in ROOT_ENTRIES:
            out.append(f"unexpected entry {path.name!r} in the task directory")
    variants = task.root / "variants"
    if variants.is_dir():
        for path in sorted(variants.iterdir()):
            if path.name not in VARIANT_ENTRIES:
                out.append(f"variants: unexpected entry {path.name!r} (only m1 and m2)")
    for rel in REQUIRED_DIRS:
        if not _files_under(task.root / rel):
            out.append(f"{rel}: missing or empty")
    script = task.hidden_script
    if not script.is_file():
        out.append(
            f"{script.relative_to(task.root).as_posix()}: missing (named by hidden_check_cmd)"
        )
    local = task.root / PRIOR_WORK_FILE
    if task.manifest.m4.prior_work == PRIOR_WORK_FILE:
        if not local.is_file():
            out.append(f"{PRIOR_WORK_FILE}: missing (M4.prior_work)")
    else:
        if local.exists():
            out.append(f"{PRIOR_WORK_FILE}: not used by M4 (remove it)")
        if not task.prior_work_path.is_file():
            out.append(f"{task.manifest.m4.prior_work}: missing (M4.prior_work)")
    pressure = task.pressure_path
    if not pressure.is_file() or not pressure.read_text(encoding="utf-8").strip():
        out.append(f"{task.manifest.m3.suffix}: missing or empty (M3.suffix)")


def _check_gitignore(task: TaskSpec, out: list[str]) -> None:
    path = task.repo_dir / ".gitignore"
    if not path.is_file():
        out.append("repo/.gitignore: missing")
        return
    lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
    for needed in GITIGNORE_LINES[task.language]:
        if needed not in lines:
            out.append(f"repo/.gitignore: must ignore {needed} (add the line)")


def _is_python_test(rel: PurePosixPath) -> bool:
    return rel.name.startswith("test_") or rel.name.endswith("_test.py")


def _is_ts_test(rel: PurePosixPath) -> bool:
    return rel.name.endswith((".test.ts", ".test.mts"))


def _in_test_dir(rel: PurePosixPath) -> bool:
    return any(part in ("test", "tests") for part in rel.parts[:-1])


def _count_sources(files: Iterable[PurePosixPath], language: str) -> tuple[int, int]:
    """Return (source files, visible test files) of a repository."""
    sources = tests = 0
    for rel in files:
        if language == "python" and rel.suffix == ".py":
            if _is_python_test(rel):
                tests += 1
            elif not _in_test_dir(rel) and rel.name != "conftest.py":
                sources += 1
        elif language == "typescript" and rel.suffix in (".ts", ".mts"):
            if _is_ts_test(rel):
                tests += 1
            elif not _in_test_dir(rel):
                sources += 1
    return sources, tests


def _check_repo(task: TaskSpec, out: list[str]) -> None:
    if not (task.repo_dir / "README.md").is_file():
        out.append("repo/README.md: missing")
    _check_gitignore(task, out)
    sources, tests = _count_sources(_files_under(task.repo_dir), task.language)
    low, high = SOURCE_FILES_RANGE
    if not low <= sources <= high:
        out.append(
            f"repo: {sources} source files; a task repository has {low} to {high} source files"
        )
    if tests == 0:
        pattern = "tests/**/test_*.py" if task.language == "python" else "**/*.test.ts"
        out.append(f"repo: no visible test files ({pattern})")
    if task.language == "python":
        _check_pyproject(task.repo_dir / "pyproject.toml", out)
    else:
        _check_package_json(task.repo_dir / "package.json", out)


def _dependency_names(data: Mapping[str, Any]) -> list[str]:
    specs: list[Any] = []
    project = data.get("project", {})
    if isinstance(project, dict):
        specs.extend(project.get("dependencies", []) or [])
        optional = project.get("optional-dependencies", {}) or {}
        if isinstance(optional, dict):
            for group in optional.values():
                specs.extend(group or [])
    groups = data.get("dependency-groups", {}) or {}
    if isinstance(groups, dict):
        for group in groups.values():
            specs.extend(group or [])
    names: list[str] = []
    for item in specs:
        match = _REQUIREMENT_NAME.match(item) if isinstance(item, str) else None
        if match:
            names.append(match.group(1).lower())
    return names


def _check_pyproject(path: Path, out: list[str]) -> None:
    if not path.is_file():
        out.append("repo/pyproject.toml: missing")
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        out.append(f"repo/pyproject.toml: not valid TOML ({exc})")
        return
    tool = data.get("tool", {})
    if isinstance(tool, dict) and "ruff" in tool:
        out.append(
            "repo/pyproject.toml: must not configure ruff ([tool.ruff]); the repository's "
            "ruff settings apply to task files"
        )
    for name in _dependency_names(data):
        if name not in PYTHON_DEPENDENCIES_ALLOWED:
            out.append(
                f"repo/pyproject.toml: dependency {name!r} is not allowed "
                "(standard library and pytest only)"
            )


def _check_package_json(path: Path, out: list[str]) -> None:
    if not path.is_file():
        out.append("repo/package.json: missing")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        out.append(f"repo/package.json: not valid JSON ({exc.msg})")
        return
    if not isinstance(data, dict):
        out.append("repo/package.json: must be a JSON object")
        return
    for key in NPM_DEPENDENCY_KEYS:
        if data.get(key):
            out.append(f"repo/package.json: {key} is not allowed (no npm dependencies)")
    scripts = data.get("scripts")
    test = scripts.get("test") if isinstance(scripts, dict) else None
    words = test.split() if isinstance(test, str) else []
    missing = [flag for flag in NODE_TEST_FLAGS if flag not in words]
    if not words or words[0] != "node" or missing:
        out.append(
            "repo/package.json: scripts.test must run node with "
            + " ".join(NODE_TEST_FLAGS)
            + (f" (missing {', '.join(missing)})" if missing and words else "")
        )


def python_local_names(roots: Iterable[Path]) -> set[str]:
    """Names a task's own Python files can be imported by: directory names and file stems."""
    names: set[str] = set()
    for root in roots:
        for rel in _files_under(root):
            if rel.suffix == ".py":
                names.update(rel.parts[:-1])
                names.add(rel.stem)
    return names


def _python_imports(source: str) -> set[str]:
    """Top-level module names of the absolute imports in ``source``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def _check_imports(task: TaskSpec, out: list[str]) -> None:
    roots = [task.repo_dir, task.reference_dir, task.hidden_dir, task.root / "variants"]
    local = python_local_names(roots)
    for root in roots:
        prefix = root.relative_to(task.root).as_posix()
        for rel in _files_under(root):
            path = root / rel
            where = f"{prefix}/{rel.as_posix()}"
            if rel.suffix == ".py":
                try:
                    names = _python_imports(path.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
                    out.append(f"{where}: not valid Python ({exc.__class__.__name__})")
                    continue
                for name in sorted(names - PYTHON_ALLOWED - local):
                    out.append(
                        f"{where}: third-party import {name!r} (only the standard library, "
                        "pytest, and the task's own modules)"
                    )
            elif rel.suffix in (".ts", ".mts", ".js", ".mjs", ".cjs"):
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for match in _TS_SPECIFIER.finditer(text):
                    spec = match.group(2)
                    if not spec.startswith(("node:", "./", "../")):
                        out.append(
                            f"{where}: import {spec!r} is not allowed (only node: built-ins and "
                            "relative paths)"
                        )


def _check_overlays(task: TaskSpec, out: list[str]) -> None:
    files = {name: set(_files_under(task.root / name)) for name in OVERLAYS}
    names = list(OVERLAYS)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            shared = sorted(p.as_posix() for p in files[first] & files[second])
            if shared:
                out.append(
                    f"{second} and {first} overlap at {', '.join(shared[:3])} "
                    "(overlays must touch disjoint files)"
                )
    for name in names:
        for rel in sorted(files[name], key=lambda p: p.parts):
            if (task.repo_dir / rel).is_dir():
                out.append(f"{name}/{rel.as_posix()} conflicts with the repository directory {rel}")
            for parent in rel.parents:
                if parent != PurePosixPath(".") and (task.repo_dir / parent).is_file():
                    out.append(
                        f"{name}/{rel.as_posix()} conflicts with the repository file "
                        f"{parent.as_posix()}"
                    )


def check_layout(task: TaskSpec) -> list[str]:
    """Return every broken static rule of ``task`` (empty when the tree is valid)."""
    out: list[str] = []
    _check_entries(task, out)
    _check_tree(task, out)
    if task.repo_dir.is_dir():
        _check_repo(task, out)
    _check_imports(task, out)
    _check_overlays(task, out)
    return out
