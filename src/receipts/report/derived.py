"""Artifacts derived from other banked artifacts, re-derived by ``make freshness`` (G10).

A derived artifact is written by a committed script from other banked artifacts, its
inputs: ``artifacts/exploratory/smoke_outcomes.json`` is ``tools/smoke_outcomes.py``'s
summary of the banked smoke run records. The numbers registry reads the derived
artifact, so a registry that is fresh against it is only as fresh as the artifact is
against its inputs. :func:`check` therefore runs each script again into a temporary file
and requires that:

1. the inputs the committed artifact records (``provenance.inputs``, path to SHA-256)
   are exactly the files its input pattern matches now, with their current hashes, so a
   run banked, removed, or changed after the artifact was written makes it stale; and
2. the fresh artifact equals the committed one in everything except when, where, and
   how it was made (``provenance`` keys :data:`VOLATILE`), so no summary value can be
   typed in.

``make freshness`` and ``make reproduce`` report what :func:`check` finds; ``make
report`` calls :func:`refresh` first, which rewrites a derived artifact only when its
content would change, so rebuilding does not churn its timestamp.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Derived:
    """A derived artifact: its path, the script that writes it, and its input pattern.

    The script must accept ``--out PATH`` and read its inputs from the repository it
    sits in. All paths are relative to the repository root.
    """

    path: str
    script: str
    inputs: str


#: Every derived artifact that a number in README.md or docs/REPORT.md depends on.
DERIVED: tuple[Derived, ...] = (
    Derived(
        "artifacts/exploratory/smoke_outcomes.json",
        "tools/smoke_outcomes.py",
        "artifacts/studies/smoke/runs/*/run.json",
    ),
)
#: Provenance keys that record when, where, and how an artifact was made, not what it
#: holds: a derivation on another commit, Python, or machine gives the same content.
VOLATILE: frozenset[str] = frozenset({"git_sha", "command", "created", "environment"})


class DerivedError(RuntimeError):
    """A derivation script failed while its inputs exist."""


def comparable(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """``artifact`` without the provenance keys in :data:`VOLATILE`."""
    out = dict(artifact)
    prov = out.get("provenance")
    if isinstance(prov, Mapping):
        out["provenance"] = {k: v for k, v in prov.items() if k not in VOLATILE}
    return out


def current_inputs(root: Path, item: Derived) -> dict[str, str]:
    """The files ``item``'s input pattern matches under ``root``, path to SHA-256."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob(item.inputs))
        if p.is_file()
    }


def derive(root: Path, item: Derived) -> dict[str, Any]:
    """Run ``item``'s script into a temporary file and return what it wrote.

    Raises:
        DerivedError: The script is missing, fails, or writes no JSON object.
    """
    script = root / item.script
    if not script.is_file():
        raise DerivedError(f"{item.script} is missing")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / Path(item.path).name
        proc = subprocess.run(
            [sys.executable, item.script, "--out", str(out)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or ["no output"]
            raise DerivedError(f"{item.script} failed: {tail[0]}")
        data = json.loads(out.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DerivedError(f"{item.script} wrote no JSON object")
    return data


def _differing_keys(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    keys = sorted(set(a) | set(b))
    out = [k for k in keys if k != "provenance" and a.get(k) != b.get(k)]
    pa, pb = a.get("provenance") or {}, b.get("provenance") or {}
    if isinstance(pa, Mapping) and isinstance(pb, Mapping):
        out += [f"provenance.{k}" for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)]
    return out


def check(root: Path, items: Sequence[Derived] = DERIVED) -> list[str]:
    """Every way a committed derived artifact differs from a fresh derivation."""
    problems: list[str] = []
    for item in items:
        target = root / item.path
        inputs = current_inputs(root, item)
        if not target.is_file():
            if inputs:
                problems.append(
                    f"{item.path}: missing, though {item.inputs} matches {len(inputs)} "
                    "file(s); run make report"
                )
            continue
        try:
            committed = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{item.path}: not JSON ({exc})")
            continue
        if not isinstance(committed, dict):
            problems.append(f"{item.path}: not a JSON object")
            continue
        recorded = (committed.get("provenance") or {}).get("inputs")
        if recorded != inputs:
            recorded = recorded if isinstance(recorded, dict) else {}
            added = sorted(inputs.keys() - recorded.keys())
            gone = sorted(recorded.keys() - inputs.keys())
            changed = sorted(k for k in inputs.keys() & recorded.keys() if inputs[k] != recorded[k])
            detail = "; ".join(
                f"{label}: {', '.join(paths)}"
                for label, paths in (("new", added), ("removed", gone), ("changed", changed))
                if paths
            )
            problems.append(
                f"{item.path}: its recorded inputs are not the current {item.inputs} files "
                f"({detail or 'malformed'}); run make report"
            )
        try:
            fresh = derive(root, item)
        except DerivedError as exc:
            problems.append(f"{item.path}: {exc}")
            continue
        if comparable(fresh) != comparable(committed):
            keys = ", ".join(_differing_keys(comparable(fresh), comparable(committed)))
            problems.append(
                f"{item.path}: differs from a fresh derivation by {item.script} ({keys}); "
                "run make report"
            )
    return problems


def refresh(root: Path, items: Sequence[Derived] = DERIVED) -> list[str]:
    """Rewrite each derived artifact whose content a fresh derivation changes.

    An artifact with no inputs and no committed file is skipped. Returns the paths
    written.

    Raises:
        DerivedError: A script failed while its inputs exist.
    """
    written: list[str] = []
    for item in items:
        target = root / item.path
        if not target.is_file() and not current_inputs(root, item):
            continue
        fresh = derive(root, item)
        if target.is_file():
            try:
                committed = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                committed = None
            if isinstance(committed, dict) and comparable(committed) == comparable(fresh):
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(item.path)
    return written
