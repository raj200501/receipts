from pathlib import Path

import pytest
from logsift.cli import main

LOG = (
    "2026-10-14T09:12:03.120Z shop-web-01 INFO checkout: Order 1042 accepted\n"
    "2026-10-14T09:12:41.007Z shop-web-02 WARN gateway: Upstream pricing took 1840 ms\n"
    "2026-10-14T11:20:09.000+02:00 shop-web-01 ERROR checkout: Order 1043 failed\n"
    "broken line\n"
    "2026-10-14T09:30:00.000Z shop-web-02 FATAL gateway: Out of file descriptors\n"
)


@pytest.fixture
def log(tmp_path: Path) -> str:
    path = tmp_path / "web.log"
    path.write_text(LOG, encoding="utf-8")
    return str(path)


def test_show_prints_entries_in_time_order_in_utc(
    log: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["show", log]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "2026-10-14T09:12:03.120Z shop-web-01 INFO checkout: Order 1042 accepted"
    assert out[2].startswith("2026-10-14T09:20:09.000Z shop-web-01 ERROR")
    assert len(out) == 4


def test_show_warns_about_damaged_lines_on_stderr(
    log: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["show", log]) == 0
    assert f"logsift: {log}:4: skipped: " in capsys.readouterr().err


def test_since_and_until_bound_the_range(log: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", log, "--since", "2026-10-14T09:15", "--until", "2026-10-14T09:30"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert "ERROR checkout" in out[0]


def test_host_and_component_filters(log: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", log, "--host", "shop-web-02", "--component", "gateway"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_summary_counts_the_matching_entries(log: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", log, "--component", "checkout"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("entries: 2\n")
    assert "  ERROR 1\n" in out


def test_several_files_are_merged(
    tmp_path: Path, log: str, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other.log"
    other.write_text("2026-10-14T09:00:00Z shop-web-03 INFO search: first\n", encoding="utf-8")
    assert main(["show", log, str(other)]) == 0
    assert capsys.readouterr().out.splitlines()[0].endswith("search: first")


def test_a_missing_file_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["show", str(tmp_path / "nope.log")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_bad_time_exits_with_status_2(log: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", log, "--since", "tomorrow"]) == 2
    assert "tomorrow" in capsys.readouterr().err


def test_an_unknown_option_exits_with_status_2(log: str) -> None:
    assert main(["show", log, "--colour"]) == 2


def test_the_shipped_example_log_is_readable(capsys: pytest.CaptureFixture[str]) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "web-2026-10-14.log"
    assert main(["summary", str(example)]) == 0
    assert capsys.readouterr().out.startswith("entries: 8\n")
