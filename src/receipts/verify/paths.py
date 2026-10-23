"""Path normalization, claim-to-path resolution, and test-file classification."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_LINE_SUFFIX = re.compile(r":\d+(?:[-:]\d+)?$")
_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_TEST_NAME = re.compile(
    r"^(test_.+\.py|.+_test\.py|.+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs|mts|cts))$"
)


def normalize_path(path: str) -> str:
    """Return ``path`` in workspace-relative POSIX form for comparison.

    Strips whitespace, quotes, and backticks, converts backslashes to slashes,
    removes a leading ``./``, collapses repeated slashes, drops a trailing slash,
    and removes a trailing ``:line`` or ``:start-end`` location.
    """
    text = path.strip().strip("'\"`").replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    while text.startswith("./"):
        text = text[2:]
    text = _LINE_SUFFIX.sub("", text)
    return text.rstrip("/") if len(text) > 1 else text


@dataclass(frozen=True)
class PathMatch:
    """Result of resolving a claimed path against the paths a ledger knows about.

    Attributes:
        path: The one candidate the claim refers to, or None.
        ambiguous: Every candidate when the claim matches more than one by suffix.
    """

    path: str | None
    ambiguous: tuple[str, ...] = ()


def resolve_path(claimed: str, candidates: Iterable[str]) -> PathMatch:
    """Resolve ``claimed`` to one of ``candidates``.

    An exact match wins. Otherwise a candidate matches when the claimed path is a
    suffix of it at a ``/`` boundary ("config.py" matches "src/app/config.py"), or
    when it is a suffix of the claimed path (an absolute path in the report). A
    match counts only if it is unique; several suffix matches are ambiguous.
    """
    wanted = normalize_path(claimed)
    pool = sorted({normalize_path(c) for c in candidates if c})
    if not wanted:
        return PathMatch(None)
    if wanted in pool:
        return PathMatch(wanted)
    hits = [c for c in pool if c.endswith("/" + wanted)]
    if not hits:
        hits = [c for c in pool if wanted.endswith("/" + c)]
    if len(hits) == 1:
        return PathMatch(hits[0])
    return PathMatch(None, tuple(hits))


def is_test_path(path: str) -> bool:
    """True for test files: under a tests/test/__tests__/spec directory, or named like a test.

    Test names are ``test_*.py``, ``*_test.py``, ``*.test.ts`` and ``*.spec.ts``
    (also ``.tsx``, ``.js``, ``.jsx``, ``.mjs``, ``.cjs``, ``.mts``, ``.cts``).
    """
    parts = normalize_path(path).split("/")
    return any(part in _TEST_DIRS for part in parts[:-1]) or bool(_TEST_NAME.match(parts[-1]))
