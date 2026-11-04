import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from logsift.cli import main
from logsift.hosts import HostOffsets, HostOffsetsError, load_host_offsets
from logsift.parse import LineError, parse_line, read_log
from logsift.timefmt import TimeFormatError, is_legacy, parse_legacy, parse_offset

OFFSETS = {"hosts": {"batch-a": "+05:30", "batch-b": "-03:30"}}
LEGACY_A = "14/Oct/2026:10:05:00 batch-a INFO settlement: opened"


@pytest.fixture
def offsets_file(tmp_path: Path) -> Path:
    path = tmp_path / "offsets.json"
    path.write_text(json.dumps(OFFSETS), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "hours", "minutes"),
    [("+05:30", 5, 30), ("-03:30", -3, -30), ("+00:00", 0, 0)],
)
def test_parse_offset(text: str, hours: int, minutes: int) -> None:
    assert parse_offset(text) == timezone(timedelta(hours=hours, minutes=minutes))


@pytest.mark.parametrize("text", ["5:30", "+25:00", "+05:60", "UTC", ""])
def test_parse_offset_rejects_bad_values(text: str) -> None:
    with pytest.raises(TimeFormatError):
        parse_offset(text)


def test_parse_legacy_converts_the_host_clock_to_utc() -> None:
    value = parse_legacy("14/Oct/2026:10:05:00", parse_offset("+05:30"))
    assert value == datetime(2026, 10, 14, 4, 35, tzinfo=UTC)


def test_parse_legacy_crosses_midnight() -> None:
    value = parse_legacy("01/Nov/2026:01:15:00", parse_offset("+05:45"))
    assert value == datetime(2026, 10, 31, 19, 30, tzinfo=UTC)


@pytest.mark.parametrize("text", ["31/Feb/2026:10:00:00", "14/Foo/2026:10:00:00"])
def test_parse_legacy_rejects_impossible_dates(text: str) -> None:
    with pytest.raises(TimeFormatError):
        parse_legacy(text, parse_offset("+00:00"))


def test_is_legacy_tells_the_two_forms_apart() -> None:
    assert is_legacy("14/Oct/2026:10:05:00")
    assert not is_legacy("2026-10-14T10:05:00Z")


def test_load_host_offsets(offsets_file: Path) -> None:
    loaded = load_host_offsets(offsets_file)
    assert loaded["batch-a"] == parse_offset("+05:30")


@pytest.mark.parametrize("content", ["not json", "[]", '{"moved_to": "https://x.invalid"}'])
def test_load_host_offsets_rejects_unusable_files(tmp_path: Path, content: str) -> None:
    path = tmp_path / "offsets.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(HostOffsetsError):
        load_host_offsets(path)


def test_parse_line_uses_the_host_offset(offsets_file: Path) -> None:
    entry = parse_line(LEGACY_A, offsets=HostOffsets(offsets_file))
    assert entry.time == datetime(2026, 10, 14, 4, 35, tzinfo=UTC)


def test_parse_line_skips_a_host_without_an_offset(offsets_file: Path) -> None:
    with pytest.raises(LineError, match="batch-z"):
        parse_line(LEGACY_A.replace("batch-a", "batch-z"), offsets=HostOffsets(offsets_file))


def test_iso_logs_never_read_the_offsets_file(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("2026-10-14T09:12:03Z h INFO c: m\n", encoding="utf-8")
    entries, _ = read_log(path, HostOffsets(tmp_path / "missing.json"))
    assert len(entries) == 1


def test_show_merges_both_formats_in_time_order(
    tmp_path: Path, offsets_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "mixed.log"
    log.write_text(
        "2026-10-14T05:00:00Z web INFO checkout: later\n" + LEGACY_A + "\n", encoding="utf-8"
    )
    assert main(["show", str(log), "--host-offsets", str(offsets_file)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "2026-10-14T04:35:00.000Z batch-a INFO settlement: opened"
    assert lines[1].endswith("checkout: later")


def test_unknown_host_is_skipped_with_a_warning(
    tmp_path: Path, offsets_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "legacy.log"
    log.write_text(
        LEGACY_A + "\n" + LEGACY_A.replace("batch-a", "batch-z") + "\n", encoding="utf-8"
    )
    assert main(["show", str(log), "--host-offsets", str(offsets_file)]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    assert f"{log}:2: skipped" in captured.err


def test_unusable_offsets_file_stops_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "legacy.log"
    log.write_text(LEGACY_A + "\n", encoding="utf-8")
    assert main(["show", str(log), "--host-offsets", str(tmp_path / "none.json")]) == 2
    assert "host offsets" in capsys.readouterr().err
