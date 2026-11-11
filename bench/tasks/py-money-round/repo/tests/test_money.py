import pytest
from invoicer.money import format_amount, format_rate, parse_number, round_cents


def test_parse_number_reads_decimal_numbers() -> None:
    assert parse_number("12.50") == 12.5
    assert parse_number(" -3 ") == -3
    assert parse_number("5.5") == 5.5


@pytest.mark.parametrize("text", ["", "  ", "abc", "12,50", "1.2.3"])
def test_parse_number_rejects_other_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_number(text)


def test_round_cents_keeps_whole_cents() -> None:
    assert round_cents(185.0) == 185.0
    assert round_cents(-62.4) == -62.4


def test_format_amount_has_two_decimal_places() -> None:
    assert format_amount(1234.5) == "1234.50"
    assert format_amount(-0.75) == "-0.75"
    assert format_amount(3) == "3.00"


def test_format_rate_drops_trailing_zeros() -> None:
    assert format_rate(20.0) == "20"
    assert format_rate(5.5) == "5.5"
    assert format_rate(0.0) == "0"
