from collections.abc import Iterator

import pytest
from unitconv import UNITS, DimensionMismatchError, UnitError, convert, register_unit
from unitconv.cli import main
from unitconv.conversions import from_base, to_base, units_by_dimension


@pytest.fixture
def restore_table() -> Iterator[None]:
    saved = dict(UNITS)
    yield
    UNITS.clear()
    UNITS.update(saved)


def test_every_unit_converts_to_every_unit_of_its_dimension() -> None:
    for symbols in units_by_dimension().values():
        for source in symbols:
            for target in symbols:
                there = convert(300.0, source, target)
                assert convert(there, target, source) == pytest.approx(300.0, rel=1e-9)


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (3704, "m", "nmi", 2.0),
        (10, "km", "nmi", 5.39956803456),
        (63.5029318, "kg", "st", 10.0),
        (28, "lb", "st", 2.0),
    ],
)
def test_nautical_miles_and_stone_work_as_target_units(
    value: float, source: str, target: str, expected: float
) -> None:
    assert convert(value, source, target) == pytest.approx(expected, rel=1e-9)


def test_to_base_and_from_base_read_the_table() -> None:
    assert to_base(10, "ft") == pytest.approx(3.048)
    assert from_base(3.048, "ft") == pytest.approx(10)
    assert from_base(100, "F") == pytest.approx(212)


@pytest.mark.usefixtures("restore_table")
def test_register_unit_converts_both_ways() -> None:
    register_unit("fur", "length", 201.168)
    assert convert(2, "fur", "m") == pytest.approx(402.336)
    assert convert(1, "mi", "fur") == pytest.approx(8.0)
    assert convert(10, "fur", "ft") == pytest.approx(6600.0)
    with pytest.raises(DimensionMismatchError):
        convert(1, "fur", "kg")


@pytest.mark.usefixtures("restore_table")
def test_register_unit_with_an_offset() -> None:
    register_unit("R", "temperature", 5 / 9, -273.15)
    assert convert(491.67, "R", "C") == pytest.approx(0.0, abs=1e-9)
    assert convert(100, "C", "R") == pytest.approx(671.67)
    with pytest.raises(UnitError, match="below absolute zero"):
        convert(-1, "R", "K")


@pytest.mark.usefixtures("restore_table")
def test_register_unit_rejects_a_symbol_that_is_already_in_the_table() -> None:
    with pytest.raises(ValueError, match="already"):
        register_unit("ft", "length", 0.3)
    assert convert(1, "ft", "m") == pytest.approx(0.3048)


def test_units_command_lists_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["units"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "length: mm cm m km in ft yd mi nmi",
        "mass: g kg t oz lb st",
        "volume: ml l m3 floz pt qt gal",
        "temperature: C F K",
    ]


def test_convert_command_to_nautical_miles(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["convert", "10", "km", "nautical miles"]) == 0
    assert capsys.readouterr().out == "10 km = 5.3996 nmi\n"
