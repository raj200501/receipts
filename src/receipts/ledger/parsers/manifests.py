"""Dependency changes between two versions of a manifest file.

Supported manifests (by file name):

- ``requirements*.txt`` and ``requirements*.in``, and ``*.txt`` inside a
  ``requirements/`` directory;
- ``pyproject.toml``: ``[project] dependencies`` and ``optional-dependencies``,
  ``[dependency-groups]`` (PEP 735), and Poetry's ``[tool.poetry.dependencies]``,
  ``[tool.poetry.dev-dependencies]`` and ``[tool.poetry.group.*.dependencies]``;
- ``package.json``: ``dependencies``, ``devDependencies``, ``peerDependencies``,
  and ``optionalDependencies``.

Dependencies are compared per section, so moving one from the main list to a
dev group reports a removal and an addition. Python names match after PEP 503
normalization (``PyYAML`` and ``pyyaml`` are the same project) and specs match
ignoring whitespace; the reported name is spelled as in the newer file. If
either side cannot be parsed (invalid TOML or JSON), no changes are reported,
because a list of changes against an unreadable file would be invented.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

from receipts.ledger.events import DependencyChange, canonical_json

# section -> normalized name -> (name as written, spec)
_Deps = dict[tuple[str, str], tuple[str, str]]

_REQ_NAME = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(.*)$", re.DOTALL)
_EGG = re.compile(r"[#&]egg=([A-Za-z0-9][A-Za-z0-9._-]*)")
_COMMENT = re.compile(r"(^|\s)#.*$")
_HASH_OPTION = re.compile(r"\s--hash[=\s]\S+")
_PACKAGE_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def normalize_name(name: str) -> str:
    """PEP 503 normalized project name: lowercase, runs of ``-_.`` become ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def manifest_kind(path: str) -> str | None:
    """``"requirements"``, ``"pyproject"``, ``"package"``, or None for other files."""
    pure = PurePosixPath(path.replace("\\", "/"))
    name = pure.name
    if name == "pyproject.toml":
        return "pyproject"
    if name == "package.json":
        return "package"
    if re.fullmatch(r"requirements[\w.-]*\.(?:txt|in)", name):
        return "requirements"
    if pure.suffix == ".txt" and pure.parent.name == "requirements":
        return "requirements"
    return None


def is_manifest(path: str) -> bool:
    """True when :func:`dependency_changes` understands the file at ``path``."""
    return manifest_kind(path) is not None


def _collapse(text: str) -> str:
    return " ".join(text.split())


def split_requirement(requirement: str) -> tuple[str, str] | None:
    """Split a PEP 508 requirement into ``(name, rest)``, e.g. ``("rich", "[jupyter]>=13")``.

    ``rest`` keeps extras, the version specifier, a URL, and markers, with
    whitespace collapsed. Returns None when the text does not start with a name
    followed by one of those (a bare URL or a local path is not a requirement).
    """
    match = _REQ_NAME.match(requirement.strip())
    if match is None:
        return None
    rest = _collapse(match.group(2))
    if rest and rest[0] not in "[(;@<>=!~":
        return None
    return match.group(1), rest


def _add(deps: _Deps, section: str, name: str, spec: str, *, python: bool) -> None:
    key = (section, normalize_name(name) if python else name)
    if key in deps:
        specs = sorted({deps[key][1], spec})
        deps[key] = (deps[key][0], " | ".join(specs))
    else:
        deps[key] = (name, spec)


def _requirements(text: str) -> _Deps:
    deps: _Deps = {}
    logical = re.sub(r"\\\r?\n", " ", text)
    for raw in logical.splitlines():
        line = _HASH_OPTION.sub("", _COMMENT.sub("", raw)).strip()
        if not line:
            continue
        if line.startswith(("-e ", "--editable ", "--editable=")):
            egg = _EGG.search(line)
            if egg is not None:
                _add(deps, "requirements", egg.group(1), _collapse(line), python=True)
            continue
        if line.startswith("-"):
            continue  # -r, -c, --index-url and other pip options
        parsed = split_requirement(line)
        if parsed is not None:
            _add(deps, "requirements", parsed[0], parsed[1], python=True)
    return deps


def _table(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pep508_list(deps: _Deps, section: str, items: Any) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, str):
            parsed = split_requirement(item)
            if parsed is not None:
                _add(deps, section, parsed[0], parsed[1], python=True)


def _poetry_spec(value: Any) -> str:
    if isinstance(value, str):
        return _collapse(value)
    if isinstance(value, dict) and set(value) == {"version"} and isinstance(value["version"], str):
        return _collapse(value["version"])
    return canonical_json(value)


def _poetry_table(deps: _Deps, section: str, table: Mapping[str, Any]) -> None:
    for name, value in table.items():
        if name.lower() != "python":
            _add(deps, section, name, _poetry_spec(value), python=True)


def _pyproject(text: str) -> _Deps:
    data = tomllib.loads(text)
    deps: _Deps = {}
    project = _table(data.get("project"))
    _pep508_list(deps, "project", project.get("dependencies"))
    for group, items in _table(project.get("optional-dependencies")).items():
        _pep508_list(deps, f"optional:{group}", items)
    for group, items in _table(data.get("dependency-groups")).items():
        _pep508_list(deps, f"group:{group}", items)
    poetry = _table(_table(data.get("tool")).get("poetry"))
    _poetry_table(deps, "poetry", _table(poetry.get("dependencies")))
    _poetry_table(deps, "poetry-dev", _table(poetry.get("dev-dependencies")))
    for group, body in _table(poetry.get("group")).items():
        _poetry_table(deps, f"poetry-group:{group}", _table(_table(body).get("dependencies")))
    return deps


def _package_json(text: str) -> _Deps:
    data = json.loads(text)
    deps: _Deps = {}
    for section in _PACKAGE_SECTIONS:
        for name, spec in _table(_table(data).get(section)).items():
            _add(
                deps,
                section,
                name,
                spec if isinstance(spec, str) else canonical_json(spec),
                python=False,
            )
    return deps


_PARSERS = {"requirements": _requirements, "pyproject": _pyproject, "package": _package_json}


def parse_dependencies(manifest_path: str, text: str) -> _Deps | None:
    """Dependencies declared in one manifest, keyed by ``(section, name)``.

    Returns None for an unknown manifest type or content that does not parse.
    """
    kind = manifest_kind(manifest_path)
    if kind is None:
        return None
    try:
        return _PARSERS[kind](text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _same(old: str, new: str) -> bool:
    return re.sub(r"\s+", "", old) == re.sub(r"\s+", "", new)


def _ordered(keys: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(keys, key=lambda key: (normalize_name(key[1]), key[0]))


def dependency_changes(
    manifest_path: str, old_text: str | None, new_text: str | None
) -> list[DependencyChange]:
    """Dependencies added, removed, or changed between two versions of a manifest.

    ``old_text`` is None when the manifest is new and ``new_text`` is None when
    it was deleted. Returns an empty list for unknown manifest types and when
    either existing side does not parse. Results are sorted by name, then section.
    """
    if manifest_kind(manifest_path) is None:
        return []
    old = {} if old_text is None else parse_dependencies(manifest_path, old_text)
    new = {} if new_text is None else parse_dependencies(manifest_path, new_text)
    if old is None or new is None:
        return []
    changes: list[DependencyChange] = []
    for key in _ordered(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        if before is None and after is not None:
            changes.append(
                DependencyChange(
                    manifest=manifest_path, name=after[0], change="added", old=None, new=after[1]
                )
            )
        elif after is None and before is not None:
            changes.append(
                DependencyChange(
                    manifest=manifest_path,
                    name=before[0],
                    change="removed",
                    old=before[1],
                    new=None,
                )
            )
        elif before is not None and after is not None and not _same(before[1], after[1]):
            changes.append(
                DependencyChange(
                    manifest=manifest_path,
                    name=after[0],
                    change="changed",
                    old=before[1],
                    new=after[1],
                )
            )
    return changes
