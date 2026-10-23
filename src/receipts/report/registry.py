"""The numbers registry: every result number in the documents, derived from artifacts.

A *derivation* is a registered function that reads one banked artifact and returns
the displayed value of one number (already formatted as it appears in the text).
:func:`build_registry` runs every derivation whose source exists and returns
``{key: {"value", "source", "source_sha256", "derivation"}}``, the format
``tools/claimcheck.py`` and ``tools/freshness.py`` check documents against.

Derivations never take a number from anywhere but their source artifact, and the
source's hash is recorded so a changed artifact makes the committed registry stale.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Derive = Callable[[Any], str]


@dataclass(frozen=True)
class Derivation:
    """One registered number."""

    key: str
    source: str  # artifact path relative to the repository root
    fn: Derive
    name: str  # "module:function", recorded in the registry


class Registry:
    """A set of derivations, keyed by number key."""

    def __init__(self) -> None:
        self._items: dict[str, Derivation] = {}

    def add(self, key: str, source: str) -> Callable[[Derive], Derive]:
        """Decorator registering ``fn`` as the derivation of ``key`` from ``source``."""

        def wrap(fn: Derive) -> Derive:
            if key in self._items:
                raise ValueError(f"number key {key!r} registered twice")
            self._items[key] = Derivation(key, source, fn, f"{fn.__module__}:{fn.__qualname__}")
            return fn

        return wrap

    def __iter__(self) -> Iterator[Derivation]:
        return iter(sorted(self._items.values(), key=lambda d: d.key))

    def __len__(self) -> int:
        return len(self._items)


def load_artifact(path: Path) -> Any:
    """Load a JSON or JSONL artifact (JSONL becomes a list of rows)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def build_registry(root: Path, registry: Registry) -> dict[str, dict[str, str]]:
    """Run every derivation whose source artifact exists under ``root``."""
    out: dict[str, dict[str, str]] = {}
    cache: dict[str, tuple[Any, str]] = {}
    for item in registry:
        path = root / item.source
        if not path.is_file():
            continue
        if item.source not in cache:
            cache[item.source] = (
                load_artifact(path),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        data, digest = cache[item.source]
        out[item.key] = {
            "value": item.fn(data),
            "source": item.source,
            "source_sha256": digest,
            "derivation": item.name,
        }
    return out


def write_registry(path: Path, numbers: Mapping[str, Mapping[str, str]]) -> None:
    """Write the registry file in a stable form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "receipts.numbers/1", "numbers": {k: dict(v) for k, v in numbers.items()}}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fmt_rate(value: float, digits: int = 2) -> str:
    """Format a proportion for prose, e.g. ``0.23``."""
    return f"{value:.{digits}f}"


def fmt_pct(value: float, digits: int = 0) -> str:
    """Format a proportion as a percentage, e.g. ``23%``."""
    return f"{100 * value:.{digits}f}%"


def fmt_ci(low: float, high: float, digits: int = 2) -> str:
    """Format an interval, e.g. ``[0.18, 0.29]``."""
    return f"[{low:.{digits}f}, {high:.{digits}f}]"
