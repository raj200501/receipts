"""Rule 2 of docs/ADDRESS_RULES.md: the local part."""

import pytest
from addrcheck import check, is_valid

SPECIALS = "!#$%&'*+/=?^_`{|}~-"


@pytest.mark.parametrize("special", list(SPECIALS))
def test_every_listed_special_character_is_allowed(special):
    assert is_valid(f"a{special}b@example.org")


@pytest.mark.parametrize("local", ["a" * 64, "a" * 63, "a.b.c", "1.2"])
def test_local_parts_at_or_under_the_limit_are_accepted(local):
    assert is_valid(f"{local}@example.org")


@pytest.mark.parametrize("length", [65, 66, 100])
def test_local_parts_over_64_characters_are_rejected(length):
    verdict = check("a" * length + "@example.org")
    assert verdict.reason == "local_too_long"


@pytest.mark.parametrize("local", [".ada", "ada.", ".", "ada..lovelace", "a...b"])
def test_misplaced_dots_are_rejected(local):
    assert check(f"{local}@example.org").reason == "local_dot"


@pytest.mark.parametrize("local", ["adä", "adaé", "名前", "a" + chr(0xA0) + "b"])
def test_characters_outside_ascii_are_rejected(local):
    assert not is_valid(f"{local}@example.org")


@pytest.mark.parametrize("char", list('()<>[],;:\\"@'))
def test_other_punctuation_is_rejected(char):
    if char == "@":
        assert check("a@b@example.org").reason == "multiple_at"
    else:
        assert check(f"a{char}b@example.org").reason == "local_bad_char"


def test_a_local_part_of_64_with_dots_is_accepted():
    local = "abcdefghi." * 6 + "xxxx"
    assert len(local) == 64
    assert is_valid(f"{local}@example.org")
