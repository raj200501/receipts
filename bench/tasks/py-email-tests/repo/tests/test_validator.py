import dataclasses

import pytest
from addrcheck import REASONS, AddressError, Verdict, check, is_valid, normalize


def test_a_plain_address_is_ok():
    verdict = check("ada@example.org")
    assert verdict == Verdict(ok=True, reason=None, normalized="ada@example.org")


def test_a_rejected_address_has_a_reason_and_no_normalized_form():
    verdict = check("ada.example.org")
    assert verdict.ok is False
    assert verdict.reason == "missing_at"
    assert verdict.normalized is None


def test_an_empty_string_is_empty():
    assert check("").reason == "empty"


def test_whitespace_inside_the_address_is_reported():
    assert check("ada lovelace@example.org").reason == "whitespace"


def test_two_at_signs_are_reported():
    assert check("ada@home@example.org").reason == "multiple_at"


def test_local_part_problems_are_reported():
    assert check("@example.org").reason == "local_empty"
    assert check("a(b)@example.org").reason == "local_bad_char"


def test_domain_problems_are_reported():
    assert check("ada@").reason == "domain_empty"
    assert check("ada@exa!mple.org").reason == "label_bad_char"


def test_every_reason_the_checker_gives_is_documented():
    samples = ["", "a b@x.org", "ab", "a@b@c.org", "@x.org", "a(@x.org", "a@", "a@x!.org"]
    for sample in samples:
        assert check(sample).reason in REASONS


@pytest.mark.parametrize("value", [None, 42, b"ada@example.org", ["ada@example.org"]])
def test_a_value_that_is_not_a_string_raises_type_error(value):
    with pytest.raises(TypeError, match="must be a string"):
        check(value)


def test_a_verdict_cannot_be_changed():
    verdict = check("ada@example.org")
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.ok = False  # type: ignore[misc]


def test_is_valid_follows_check():
    assert is_valid("ada@example.org") is True
    assert is_valid("ada.example.org") is False


def test_normalize_returns_a_valid_address_unchanged_when_it_is_already_normal():
    assert normalize("ada@example.org") == "ada@example.org"


def test_normalize_raises_address_error_with_the_reason():
    with pytest.raises(AddressError) as caught:
        normalize("ada.example.org")
    assert caught.value.reason == "missing_at"
    assert "no @" in str(caught.value)


def test_address_error_is_a_value_error():
    assert issubclass(AddressError, ValueError)


def test_a_blocked_domain_is_rejected():
    verdict = check("ada@spam.example", blocked_domains=["spam.example"])
    assert verdict.ok is False
    assert verdict.reason == "blocked_domain"


def test_other_domains_are_not_blocked():
    assert check("ada@example.org", blocked_domains=["spam.example"]).ok


def test_the_blocked_list_may_be_any_iterable():
    assert not check("ada@spam.example", blocked_domains=iter(["spam.example"])).ok
