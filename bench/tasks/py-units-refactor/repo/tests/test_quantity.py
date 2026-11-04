import pytest
from unitconv import UnitError, format_number, format_quantity, parse_quantity


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.5 kg", (12.5, "kg")),
        ("3.5kg", (3.5, "kg")),
        ("12 pounds", (12.0, "lb")),
        ("-40 F", (-40.0, "F")),
        (".5 l", (0.5, "l")),
        ("2 fl oz", (2.0, "floz")),
    ],
)
def test_parse_quantity(text: str, expected: tuple[float, str]) -> None:
    assert parse_quantity(text) == expected


@pytest.mark.parametrize("text", ["kg 12", "12", "twelve kg", ""])
def test_parse_quantity_rejects_text_without_a_number_and_a_unit(text: str) -> None:
    with pytest.raises(UnitError, match="expected a number and a unit"):
        parse_quantity(text)


@pytest.mark.parametrize(
    ("value", "precision", "text"),
    [
        (3.6576000000000004, 4, "3.6576"),
        (2.4947580350000003, 2, "2.49"),
        (100.0, 4, "100"),
        (1.23456789, 4, "1.2346"),
        (-0.00001, 4, "0"),
        (42.0, 0, "42"),
    ],
)
def test_format_number(value: float, precision: int, text: str) -> None:
    assert format_number(value, precision) == text


def test_format_quantity() -> None:
    assert format_quantity(0.9144, "m") == "0.9144 m"
