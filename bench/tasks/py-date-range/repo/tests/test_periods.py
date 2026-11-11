from datetime import date

import pytest
from dateseq.periods import PeriodError, parse_date, parse_period, resolve, weeks_in


def test_parse_date_reads_iso_dates() -> None:
    assert parse_date("2026-03-02") == date(2026, 3, 2)
    assert parse_date(" 2028-02-29 ") == date(2028, 2, 29)


@pytest.mark.parametrize(
    "text", ["2026-02-30", "2026-3-1", "20260301", "2026-W10-1", "03/01/2026", ""]
)
def test_parse_date_rejects_other_forms(text: str) -> None:
    with pytest.raises(PeriodError, match="not a date"):
        parse_date(text)


def test_a_date_is_a_period_of_one_day() -> None:
    assert parse_period("2026-03-05") == (date(2026, 3, 5), date(2026, 3, 5))


def test_month_period_runs_from_the_first_to_the_last_day() -> None:
    assert parse_period("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert parse_period("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))


def test_month_13_is_rejected() -> None:
    with pytest.raises(PeriodError, match="not a month"):
        parse_period("2026-13")


def test_iso_week_period_runs_from_monday_to_sunday() -> None:
    assert parse_period("2026-W10") == (date(2026, 3, 2), date(2026, 3, 8))


def test_first_iso_week_can_start_in_the_previous_year() -> None:
    assert parse_period("2026-W01") == (date(2025, 12, 29), date(2026, 1, 4))


def test_week_53_exists_only_in_long_years() -> None:
    assert parse_period("2026-W53") == (date(2026, 12, 28), date(2027, 1, 3))
    with pytest.raises(PeriodError, match="2027 has weeks 01 to 52"):
        parse_period("2027-W53")


def test_weeks_in() -> None:
    assert (weeks_in(2026), weeks_in(2027)) == (53, 52)


def test_unknown_period_is_rejected() -> None:
    with pytest.raises(PeriodError, match="expected YYYY-MM-DD, YYYY-MM, or YYYY-Www"):
        parse_period("2026-Q1")


def test_resolve_runs_to_the_end_of_the_end_period() -> None:
    assert resolve("2026-03", "2026-05") == (date(2026, 3, 1), date(2026, 5, 31))


def test_resolve_without_an_end_covers_the_start_period() -> None:
    assert resolve("2026-W10") == (date(2026, 3, 2), date(2026, 3, 8))
