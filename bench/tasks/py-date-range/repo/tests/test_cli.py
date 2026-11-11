import pytest
from dateseq.cli import main


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str], str]:
    status = main(list(argv))
    captured = capsys.readouterr()
    return status, captured.out.splitlines(), captured.err


def test_list_prints_one_date_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    status, lines, _ = _run(capsys, "list", "2026-03-02", "2026-03-31")
    assert status == 0
    assert lines[:3] == ["2026-03-02", "2026-03-03", "2026-03-04"]


def test_list_weekdays(capsys: pytest.CaptureFixture[str]) -> None:
    status, lines, _ = _run(capsys, "list", "2026-03-05", "2026-03-08", "--weekdays")
    assert (status, lines) == (0, ["2026-03-05", "2026-03-06"])


def test_list_in_another_format(capsys: pytest.CaptureFixture[str]) -> None:
    status, lines, _ = _run(capsys, "list", "2026-W10", "--weekdays", "--format", "eu")
    assert status == 0
    assert lines == ["02.03.2026", "03.03.2026", "04.03.2026", "05.03.2026", "06.03.2026"]


def test_list_with_the_end_before_the_start_prints_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(capsys, "list", "2026-03-09", "2026-03-02") == (0, [], "")


def test_count_days_of_a_month(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys, "count", "2026-03") == (0, ["31"], "")


def test_count_weekdays_of_a_month(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys, "count", "2026-03", "--weekdays") == (0, ["22"], "")


def test_count_of_an_iso_week(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys, "count", "2026-W10") == (0, ["7"], "")


def test_count_from_one_month_to_another(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys, "count", "2026-03", "2026-05") == (0, ["92"], "")


def test_invalid_date_exits_with_status_2(capsys: pytest.CaptureFixture[str]) -> None:
    status, lines, err = _run(capsys, "list", "2026-02-30")
    assert (status, lines) == (2, [])
    assert err == "dateseq: not a date: '2026-02-30' (expected YYYY-MM-DD)\n"


def test_invalid_week_exits_with_status_2(capsys: pytest.CaptureFixture[str]) -> None:
    status, _, err = _run(capsys, "count", "2027-W53")
    assert status == 2
    assert "2027 has weeks 01 to 52" in err


def test_unknown_format_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["list", "2026-03", "--format", "us"])
    assert stopped.value.code == 2
