"""Build the report outputs: the numbers registry, figures, and their manifest.

``build`` runs every registered derivation and figure over the banked artifacts and
writes ``artifacts/report/numbers.json``, the SVG figures under ``docs/figures/``, and
``artifacts/report/manifest.json`` listing every generated file with its hash. The
manifest is what gate G13 uses to confirm the README's headline figure came from
``make report``. ``reproduce`` rebuilds everything into a temporary directory and
reports every file that differs from the committed one.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from receipts.report.registry import Registry, build_registry, write_registry

FigureFn = Callable[[Path], str | None]
NUMBERS = Path("artifacts/report/numbers.json")
MANIFEST = Path("artifacts/report/manifest.json")


@dataclass
class ReportSpec:
    """Everything ``make report`` produces: numbers and figures."""

    numbers: Registry = field(default_factory=Registry)
    figures: dict[str, FigureFn] = field(default_factory=dict)

    def figure(self, rel_path: str) -> Callable[[FigureFn], FigureFn]:
        """Decorator registering a figure written to ``rel_path`` (an ``.svg`` path)."""

        def wrap(fn: FigureFn) -> FigureFn:
            if not rel_path.endswith(".svg"):
                raise ValueError("figures are SVG files")
            self.figures[rel_path] = fn
            return fn

        return wrap


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, spec: ReportSpec, out_root: Path | None = None) -> dict[str, object]:
    """Write the registry, figures, and manifest under ``out_root`` (default ``root``)."""
    out = root if out_root is None else out_root
    numbers = build_registry(root, spec.numbers)
    write_registry(out / NUMBERS, numbers)
    figures: list[str] = []
    for rel, fn in sorted(spec.figures.items()):
        svg = fn(root)
        if svg is None:
            continue
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(svg, encoding="utf-8")
        figures.append(rel)
    manifest: dict[str, object] = {
        "schema": "receipts.report-manifest/1",
        "figures": figures,
        "files": {rel: _sha(out / rel) for rel in [str(NUMBERS), *figures]},
        "numbers": len(numbers),
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    return manifest


def numbers_only(root: Path, spec: ReportSpec, out: Path) -> Mapping[str, Mapping[str, str]]:
    """Rebuild only the registry, into ``out`` (used by ``make freshness``)."""
    numbers = build_registry(root, spec.numbers)
    write_registry(out, numbers)
    return numbers


def reproduce(root: Path, spec: ReportSpec) -> list[str]:
    """Rebuild into a temporary directory; return committed files that differ or are missing."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(root, spec, Path(tmp))
        files = manifest["files"]
        assert isinstance(files, dict)
        problems = []
        for rel in [*files, str(MANIFEST)]:
            committed = root / rel
            fresh = Path(tmp) / rel
            if not committed.is_file():
                problems.append(f"{rel}: not committed")
            elif committed.read_bytes() != fresh.read_bytes():
                problems.append(f"{rel}: differs from a fresh rebuild")
        return problems
