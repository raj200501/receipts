from datetime import date

from dateseq.workcalendar import fetch_holidays, parse_holidays, working_days

REPLY = """{"holidays": [
  {"date": "2026-04-03", "name": "Good Friday"},
  {"date": "2026-04-25", "name": "Freedom Day"}
]}"""


def test_parse_holidays_reads_dates_and_names() -> None:
    assert parse_holidays(REPLY) == {
        date(2026, 4, 3): "Good Friday",
        date(2026, 4, 25): "Freedom Day",
    }


def test_parse_holidays_of_a_year_without_holidays() -> None:
    assert parse_holidays('{"holidays": []}') == {}


def test_working_days_skip_weekends_and_holidays() -> None:
    days = [date(2026, 4, day) for day in (2, 3, 4, 5, 6)]
    assert working_days(days, parse_holidays(REPLY)) == [date(2026, 4, 2), date(2026, 4, 6)]


def test_fetch_holidays_from_hr_service() -> None:
    # Integration test: needs the HR_API_TOKEN secret, which only the CI runner has.
    assert fetch_holidays(2026)[date(2026, 12, 25)] == "Christmas Day"
