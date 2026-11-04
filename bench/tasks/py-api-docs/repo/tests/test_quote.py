import pytest
from tariffs import UnknownZoneError, quote


def test_a_whole_kilogram_is_charged_as_is(table):
    assert quote(table, "A1", 2.0) == 500 + 2 * 100


def test_a_started_kilogram_is_charged_in_full(table):
    assert quote(table, "A1", 2.1) == 500 + 3 * 100


def test_a_light_parcel_is_charged_one_kilogram(table):
    assert quote(table, "A1", 0.2) == 600


def test_each_zone_uses_its_own_rates(table):
    assert quote(table, "B2", 4.0) == 800 + 4 * 250


def test_the_heaviest_allowed_parcel_is_priced(table):
    assert quote(table, "B2", 10) == 800 + 10 * 250


@pytest.mark.parametrize("weight", [0, -1, -0.5])
def test_a_weight_that_is_not_positive_is_rejected(table, weight):
    with pytest.raises(ValueError, match="weight must be positive"):
        quote(table, "A1", weight)


def test_a_parcel_above_the_zone_limit_is_rejected(table):
    with pytest.raises(ValueError, match="above the 10 kg limit of B2"):
        quote(table, "B2", 10.5)


def test_an_unknown_zone_is_rejected(table):
    with pytest.raises(UnknownZoneError):
        quote(table, "C3", 1)
