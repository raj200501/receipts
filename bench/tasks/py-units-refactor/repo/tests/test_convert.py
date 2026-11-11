import pytest
from unitconv import DimensionMismatchError, UnitError, UnknownUnitError, convert, dimension_of


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (12, "ft", "m", 3.6576),
        (1, "in", "cm", 2.54),
        (5, "km", "mi", 3.10685596119),
        (26.2, "mi", "km", 42.1648128),
        (100, "yd", "ft", 300.0),
        (250, "mm", "in", 9.84251968504),
        (3, "nmi", "km", 5.556),
    ],
)
def test_length(value: float, source: str, target: str, expected: float) -> None:
    assert convert(value, source, target) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (2.2, "lb", "kg", 0.997903214),
        (70, "kg", "lb", 154.323583529),
        (16, "oz", "g", 453.59237),
        (1, "t", "lb", 2204.62262185),
        (12, "st", "kg", 76.20351816),
    ],
)
def test_mass(value: float, source: str, target: str, expected: float) -> None:
    assert convert(value, source, target) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (5, "gal", "l", 18.92705892),
        (1, "l", "floz", 33.8140227018),
        (1, "m3", "gal", 264.172052358),
        (2, "pt", "ml", 946.352946),
        (3, "qt", "l", 2.839058838),
    ],
)
def test_volume(value: float, source: str, target: str, expected: float) -> None:
    assert convert(value, source, target) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (100, "C", "F", 212.0),
        (32, "F", "C", 0.0),
        (300, "K", "C", 26.85),
        (-40, "F", "C", -40.0),
        (0, "C", "K", 273.15),
    ],
)
def test_temperature(value: float, source: str, target: str, expected: float) -> None:
    assert convert(value, source, target) == pytest.approx(expected, rel=1e-9, abs=1e-9)


def test_same_unit_returns_the_value() -> None:
    assert convert(7.5, "kg", "kg") == 7.5


def test_absolute_zero_itself_is_allowed() -> None:
    assert convert(0, "K", "C") == pytest.approx(-273.15)


def test_below_absolute_zero_is_rejected() -> None:
    with pytest.raises(UnitError, match="-300 C is below absolute zero"):
        convert(-300, "C", "K")


def test_unknown_unit_is_rejected() -> None:
    with pytest.raises(UnknownUnitError, match="unknown unit 'furlong'"):
        convert(1, "furlong", "m")


def test_units_of_different_dimensions_are_rejected() -> None:
    with pytest.raises(DimensionMismatchError, match=r"cannot convert length \(m\) to mass"):
        convert(1, "m", "kg")


@pytest.mark.parametrize(
    ("unit", "dimension"),
    [("yd", "length"), ("oz", "mass"), ("gal", "volume"), ("K", "temperature")],
)
def test_dimension_of(unit: str, dimension: str) -> None:
    assert dimension_of(unit) == dimension


def test_unit_errors_are_value_errors() -> None:
    assert issubclass(UnknownUnitError, ValueError)
    assert issubclass(DimensionMismatchError, UnitError)
