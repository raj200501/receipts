from decimal import Decimal

import pytest
from invoicer.money import format_amount, format_rate, parse_number, round_cents


def test_parse_number_reads_decimal_numbers_exactly() -> None:
    assert parse_number("12.50") == Decimal("12.50")
    assert parse_number(" -3 ") == Decimal("-3")
    assert parse_number("0.895") == Decimal("0.895")
    assert isinstance(parse_number("5.5"), Decimal)


@pytest.mark.parametrize(
    "text", ["", "  ", "abc", "12,50", "1.2.3", "NaN", "nan", "inf", "-Infinity", "sNaN"]
)
def test_parse_number_rejects_other_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize(
    ("value", "rounded"),
    [
        ("185", "185.00"),
        ("2.125", "2.12"),
        ("2.135", "2.14"),
        ("0.525", "0.52"),
        ("2.675", "2.68"),
        ("2.6751", "2.68"),
        ("-2.685", "-2.68"),
    ],
)
def test_round_cents_rounds_half_to_even(value: str, rounded: str) -> None:
    assert str(round_cents(Decimal(value))) == rounded


def test_format_amount_has_two_decimal_places() -> None:
    assert format_amount(Decimal("1234.5")) == "1234.50"
    assert format_amount(Decimal("-0.75")) == "-0.75"
    assert format_amount(Decimal("3")) == "3.00"


def test_format_rate_drops_trailing_zeros() -> None:
    assert format_rate(Decimal("20")) == "20"
    assert format_rate(Decimal("20.0")) == "20"
    assert format_rate(Decimal("5.50")) == "5.5"
    assert format_rate(Decimal("0")) == "0"
