import json
from datetime import date
from pathlib import Path

import pytest
from bizdays.calendar import CalendarError, load_closures, parse_closures


def _write(root: Path, name: str, document: object) -> None:
    (root / name).write_text(json.dumps(document), encoding="utf-8")


def test_parse_closures_reads_the_days() -> None:
    text = json.dumps({"name": "x", "days": {"2026-12-24": "Winter closure"}})
    assert parse_closures(text, "x.json") == frozenset({date(2026, 12, 24)})


def test_load_closures_reads_a_file_relative_to_the_root(tmp_path: Path) -> None:
    _write(tmp_path, "closures.json", {"days": {"2026-05-01": "Labour Day"}})
    assert load_closures("closures.json", tmp_path) == frozenset({date(2026, 5, 1)})


def test_missing_file_is_a_calendar_error(tmp_path: Path) -> None:
    with pytest.raises(CalendarError, match="not found"):
        load_closures("missing.json", tmp_path)


def test_invalid_json_is_a_calendar_error() -> None:
    with pytest.raises(CalendarError, match="not valid JSON"):
        parse_closures("{", "x.json")


def test_days_must_be_a_mapping() -> None:
    with pytest.raises(CalendarError, match="'days'"):
        parse_closures(json.dumps({"days": ["2026-12-24"]}), "x.json")


def test_invalid_date_is_a_calendar_error() -> None:
    with pytest.raises(CalendarError, match="invalid date"):
        parse_closures(json.dumps({"days": {"2026-13-01": "?"}}), "x.json")


def test_unsupported_source_scheme_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CalendarError, match="unsupported"):
        load_closures("ftp://example.invalid/closures.json", tmp_path)


def test_bundled_closures_load() -> None:
    root = Path(__file__).resolve().parents[1]
    closures = load_closures("data/closures.json", root)
    assert date(2026, 12, 24) in closures
