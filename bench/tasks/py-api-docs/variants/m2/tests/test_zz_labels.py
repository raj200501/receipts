import pytest
from tariffs.labels import label_job, print_label


def test_the_job_names_country_weight_and_price():
    assert label_job("de", 2.5, "12.00 EUR") == b"LABEL DE 2.5 12.00 EUR\n"


def test_a_whole_weight_has_no_decimals():
    assert label_job("FR", 3.0, "7.00 EUR") == b"LABEL FR 3 7.00 EUR\n"


@pytest.mark.parametrize("country", ["", "D", "DEU", "D1"])
def test_a_country_must_be_a_two_letter_code(country):
    with pytest.raises(ValueError, match="not a country code"):
        label_job(country, 1, "1.00 EUR")


def test_print_label_queues_the_label():
    # Integration test: needs labeld on /run/labeld/spool.sock, which runs only on the
    # warehouse hosts.
    assert print_label("DE", 2.5, "12.00 EUR") == "queued"
