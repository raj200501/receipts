import pytest
from kvstore.codec import format_value, parse_value


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("7", 7),
        ("2.5", 2.5),
        ("true", True),
        ("null", None),
        ('"007"', "007"),
        ('["en", "nl"]', ["en", "nl"]),
        ('{"tray": 2}', {"tray": 2}),
    ],
)
def test_json_text_is_stored_as_json(text: str, value: object) -> None:
    assert parse_value(text) == value


def test_other_text_is_stored_as_a_string() -> None:
    assert parse_value("lobby-east-2") == "lobby-east-2"
    assert parse_value("Welcome to Rook Street") == "Welcome to Rook Street"


def test_nan_and_infinity_are_strings() -> None:
    assert parse_value("NaN") == "NaN"
    assert parse_value("-Infinity") == "-Infinity"


def test_as_string_keeps_the_text() -> None:
    assert parse_value("007", as_string=True) == "007"


def test_format_value_prints_strings_as_they_are() -> None:
    assert format_value("lobby-east-2") == "lobby-east-2"


def test_format_value_prints_other_values_as_json() -> None:
    assert format_value(7) == "7"
    assert format_value(True) == "true"
    assert format_value(["en", "nl"]) == '["en", "nl"]'
    assert format_value({"tray": 2, "queue": "a"}) == '{"queue": "a", "tray": 2}'
