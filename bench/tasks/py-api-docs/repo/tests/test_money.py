import pytest
from tariffs import format_money


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "0.00 EUR"),
        (5, "0.05 EUR"),
        (99, "0.99 EUR"),
        (100, "1.00 EUR"),
        (123456, "1234.56 EUR"),
    ],
)
def test_amounts_are_printed_with_two_decimals(cents, expected):
    assert format_money(cents) == expected


def test_the_currency_can_be_changed():
    assert format_money(1250, "GBP") == "12.50 GBP"


def test_a_negative_amount_is_rejected():
    with pytest.raises(ValueError, match="must not be negative"):
        format_money(-1)


@pytest.mark.parametrize("value", [1.5, "100", None, True])
def test_only_integers_are_accepted(value):
    with pytest.raises(TypeError, match="must be an integer"):
        format_money(value)
