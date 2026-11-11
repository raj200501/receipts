"""Tests that docs/BENCH.md states the rules the framework enforces.

The authoring spec is read by independent task authors, so its limits, its list of
pressure phrases, and its table of exemplar tasks must match the code and the pilot
tasks in bench/tasks/.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from pathlib import Path

from receipts.bench import spec
from receipts.bench.spec import load_task

from .factory import EXEMPLARS

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "BENCH.md"
TASKS = ROOT / "bench" / "tasks"
LIMIT_ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]*)` \| (.+?) \| `(receipts\.bench\.\w+)` \|$")
PILOT_ROW = re.compile(r"^\| `(pilot-[a-z0-9-]+)` \| (\w+) \| (\w+) \| (\w+) \|", re.MULTILINE)


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _render(value: object) -> str:
    """How the limits table writes a value."""
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, int) for v in value):
        return f"{value[0]} to {value[1]}"
    if isinstance(value, frozenset):
        return ", ".join(sorted(str(item) for item in value))
    if isinstance(value, Mapping):
        return ", ".join(f"{key} {item}" for key, item in value.items())
    return str(value)


def test_limits_table_matches_the_code() -> None:
    section = _text().split("## 13. Limits", 1)[1]
    rows = [match.groups() for line in section.splitlines() if (match := LIMIT_ROW.match(line))]
    assert len(rows) >= 18
    for name, shown, module_name in rows:
        module = importlib.import_module(module_name)
        assert _render(getattr(module, name)) == shown, name


def test_every_pressure_phrase_is_listed() -> None:
    text = " ".join(_text().split())
    for phrase in spec.PRESSURE_PHRASES:
        assert f"`{phrase}`" in text, phrase


def test_exemplar_table_matches_the_pilot_tasks() -> None:
    # The four exemplars, not every pilot-* directory: the catalog allows pilot tasks
    # to be added later without editing this table.
    rows = PILOT_ROW.findall(_text())
    assert sorted(row[0] for row in rows) == sorted(EXEMPLARS)
    assert all((TASKS / name / "task.toml").is_file() for name in EXEMPLARS)
    for name, language, category, method in rows:
        task = load_task(TASKS / name)
        assert (task.language, task.category, task.manifest.m1.method) == (
            language,
            category,
            method,
        )


def test_the_spec_points_to_the_catalog_and_has_no_em_dash() -> None:
    text = _text()
    assert "(BENCH_CATALOG.md)" in text
    assert "\N{EM DASH}" not in text
    for name in ("check.py", "check.mjs", "run_case.mjs", "--capture-prior-work", "--phase"):
        assert name in text, name
