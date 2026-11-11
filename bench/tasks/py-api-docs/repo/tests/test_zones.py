import pytest
from tariffs import UnknownZoneError, zone_for


@pytest.mark.parametrize(
    ("country", "zone"),
    [("DE", "EU1"), ("ES", "EU2"), ("PL", "EU3"), ("GB", "UK"), ("US", "US"), ("JP", "WORLD")],
)
def test_countries_map_to_their_zone(country, zone):
    assert zone_for(country) == zone


@pytest.mark.parametrize("country", ["de", "De", " DE ", "dE\n"])
def test_the_country_code_is_case_and_space_insensitive(country):
    assert zone_for(country) == "EU1"


def test_an_unknown_country_raises_unknown_zone_error():
    with pytest.raises(UnknownZoneError) as caught:
        zone_for("ZZ")
    assert caught.value.code == "ZZ"
    assert "unknown country 'ZZ'" in str(caught.value)


def test_unknown_zone_error_is_a_lookup_error():
    assert issubclass(UnknownZoneError, LookupError)
