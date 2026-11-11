import pytest
from addrcheck.domain import check_domain


@pytest.mark.parametrize(
    "domain", ["example.org", "mail.example.org", "a.b.c.d.example.co.uk", "my-site.example.org"]
)
def test_ordinary_domains_are_accepted(domain):
    assert check_domain(domain) is None


def test_an_empty_domain_is_rejected():
    assert check_domain("") == "domain_empty"


@pytest.mark.parametrize("domain", ["exa!mple.org", "exa mple.org", "example.o*g"])
def test_characters_outside_letters_digits_and_hyphen_are_rejected(domain):
    assert check_domain(domain) == "label_bad_char"


@pytest.mark.parametrize("domain", ["example..org", ".example.org"])
def test_empty_labels_are_rejected(domain):
    assert check_domain(domain) == "label_empty"


def test_a_very_long_domain_is_rejected():
    assert check_domain(".".join(["abcdefghi"] * 40)) == "domain_too_long"


def test_a_very_long_label_is_rejected():
    assert check_domain("a" * 80 + ".org") == "label_too_long"
