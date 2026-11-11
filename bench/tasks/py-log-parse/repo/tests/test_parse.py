from datetime import UTC, datetime
from pathlib import Path

import pytest
from logsift.parse import LineError, parse_line, parse_lines, read_log

GOOD = "2026-10-14T09:12:03.120Z shop-web-01 INFO checkout: Order 1042 accepted"


def test_parse_line_reads_every_field() -> None:
    entry = parse_line(GOOD, "web.log", 7)
    assert entry.time == datetime(2026, 10, 14, 9, 12, 3, 120000, UTC)
    assert (entry.host, entry.level, entry.component) == ("shop-web-01", "INFO", "checkout")
    assert entry.message == "Order 1042 accepted"
    assert (entry.source, entry.line) == ("web.log", 7)


def test_parse_line_keeps_colons_in_the_message() -> None:
    entry = parse_line("2026-10-14T09:12:03Z h WARN gateway: upstream: pricing: slow")
    assert entry.message == "upstream: pricing: slow"


@pytest.mark.parametrize(
    "text",
    [
        "no timestamp here",
        "2026-10-14T09:12:03Z shop-web-01 NOTICE checkout: unknown level",
        "2026-10-14T09:12:03 shop-web-01 INFO checkout: no time zone",
        "2026-10-14T09:12:03Z shop-web-01 INFO Checkout: bad component",
    ],
)
def test_parse_line_rejects_damaged_lines(text: str) -> None:
    with pytest.raises(LineError):
        parse_line(text)


def test_parse_lines_skips_blank_lines_and_reports_the_rest() -> None:
    entries, problems = parse_lines([GOOD, "", "garbage", GOOD], source="x.log")
    assert len(entries) == 2
    assert len(problems) == 1
    assert problems[0].startswith("x.log:3: skipped: ")


def test_read_log_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text(GOOD + "\n", encoding="utf-8")
    entries, problems = read_log(path)
    assert [e.message for e in entries] == ["Order 1042 accepted"]
    assert problems == []


def test_read_log_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_log(tmp_path / "missing.log")
