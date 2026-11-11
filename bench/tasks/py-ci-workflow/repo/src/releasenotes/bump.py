"""Suggest the next version from the commits since the last release."""

from __future__ import annotations

import re
from collections.abc import Iterable

from releasenotes.commits import Commit

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def suggest_bump(commits: Iterable[Commit]) -> str:
    """``"major"``, ``"minor"``, ``"patch"``, or ``"none"`` for these commits.

    A breaking commit is major, a feature is minor, a fix or performance change is patch,
    and anything else (docs, refactor, tests, build, ci, chore) does not need a release.
    """
    level = "none"
    for commit in commits:
        if commit.breaking:
            return "major"
        if commit.type == "feat":
            level = "minor"
        elif commit.type in ("fix", "perf") and level == "none":
            level = "patch"
    return level


def next_version(current: str, bump: str) -> str:
    """Apply ``bump`` to the ``MAJOR.MINOR.PATCH`` version ``current``.

    Raises:
        ValueError: ``current`` is not ``MAJOR.MINOR.PATCH`` or ``bump`` is unknown.
    """
    match = _VERSION.match(current)
    if match is None:
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {current!r}")
    major, minor, patch = (int(part) for part in match.groups())
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if bump == "none":
        return current
    raise ValueError(f"unknown bump: {bump!r}")
