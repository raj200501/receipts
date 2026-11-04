from datetime import date

import pytest
from dateseq.formats import FORMATS, format_dates

DAY = date(2026, 3, 2)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("iso", "2026-03-02"),
        ("compact", "20260302"),
        ("eu", "02.03.2026"),
        ("weekday", "Mon 2026-03-02"),
    ],
)
def test_each_format(name: str, text: str) -> None:
    assert FORMATS[name](DAY) == text


def test_weekday_names_do_not_depend_on_the_locale() -> None:
    assert FORMATS["weekday"](date(2026, 3, 8)) == "Sun 2026-03-08"


def test_format_dates_keeps_the_order() -> None:
    assert list(format_dates([date(2026, 3, 3), DAY], "compact")) == ["20260303", "20260302"]


def test_unknown_format_raises_key_error() -> None:
    with pytest.raises(KeyError):
        list(format_dates([DAY], "us"))
