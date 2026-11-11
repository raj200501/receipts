import pytest
from unitconv import normalize_unit


@pytest.mark.parametrize(
    ("name", "symbol"),
    [
        ("feet", "ft"),
        ("Metres", "m"),
        ("  kilograms ", "kg"),
        ("lbs", "lb"),
        ("fluid   ounces", "floz"),
        ("L", "l"),
        ("\N{DEGREE SIGN}C", "C"),
        ("Fahrenheit", "F"),
    ],
)
def test_names_map_to_symbols(name: str, symbol: str) -> None:
    assert normalize_unit(name) == symbol


@pytest.mark.parametrize("symbol", ["mm", "nmi", "oz", "gal", "K"])
def test_symbols_come_back_unchanged(symbol: str) -> None:
    assert normalize_unit(symbol) == symbol


def test_unknown_names_come_back_stripped() -> None:
    assert normalize_unit(" pallets ") == "pallets"
