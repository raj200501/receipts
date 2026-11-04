"""Source hygiene of the claims package, with the rules that tools/ship_check.py applies."""

from __future__ import annotations

from pathlib import Path

import ship_check

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(
    [
        *(ROOT / "src" / "receipts" / "claims").glob("*.py"),
        *(ROOT / "tests" / "claims").glob("*.py"),
        *(ROOT / "tests" / "fixtures" / "claims").glob("*.json"),
    ]
)


def test_sources_are_found() -> None:
    names = {path.name for path in SOURCES}
    assert {"patterns.py", "segment.py", "model.py", "test_hygiene.py", "dev_reports.json"} <= names


def test_every_type_ignore_has_a_code_and_a_reason() -> None:
    """Gate G2 rejects a ``type: ignore`` without an error code and a reason."""
    bad = {
        str(path.relative_to(ROOT)): lines
        for path in SOURCES
        if path.suffix == ".py"
        and (lines := ship_check.unexplained_type_ignores(path.read_text(encoding="utf-8")))
    }
    assert bad == {}


def test_no_em_dash_anywhere() -> None:
    """Plain-writing rule: no em dash in code, tests, or fixtures (chr(0x2014))."""
    offenders = [
        str(path.relative_to(ROOT))
        for path in SOURCES
        if ship_check.EM_DASH in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
