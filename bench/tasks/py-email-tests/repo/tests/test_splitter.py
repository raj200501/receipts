import pytest
from addrcheck import split_address


def test_splits_at_the_at_sign():
    assert split_address("ada@example.org") == ("ada", "example.org")


def test_keeps_the_case_of_both_parts():
    assert split_address("Ada.L@Example.ORG") == ("Ada.L", "Example.ORG")


def test_parts_may_be_empty():
    assert split_address("@example.org") == ("", "example.org")
    assert split_address("ada@") == ("ada", "")


@pytest.mark.parametrize("text", ["ada.example.org", "", "a@b@c"])
def test_needs_exactly_one_at_sign(text):
    with pytest.raises(ValueError, match="exactly one @"):
        split_address(text)
