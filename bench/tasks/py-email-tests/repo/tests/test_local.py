import pytest
from addrcheck.local import check_local


@pytest.mark.parametrize("local", ["ada", "ada.lovelace", "ada_l", "a1", "x", "a-b"])
def test_plain_local_parts_are_accepted(local):
    assert check_local(local) is None


def test_an_empty_local_part_is_rejected():
    assert check_local("") == "local_empty"


@pytest.mark.parametrize("local", ["a b", "a(b)", "a,b", "a<b>", "a\\b"])
def test_characters_outside_the_list_are_rejected(local):
    assert check_local(local) == "local_bad_char"


def test_a_very_long_local_part_is_rejected():
    assert check_local("a" * 100) == "local_too_long"


def test_a_short_local_part_is_not_too_long():
    assert check_local("a" * 20) is None
