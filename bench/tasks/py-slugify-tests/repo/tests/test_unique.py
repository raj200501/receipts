import pytest
from textkit import unique_slug


def test_a_free_slug_is_returned_as_it_is():
    assert unique_slug("Getting Started", set()) == "getting-started"


def test_other_slugs_in_use_do_not_matter():
    assert unique_slug("Getting Started", {"release-notes"}) == "getting-started"


def test_an_unknown_separator_is_rejected():
    with pytest.raises(ValueError, match="separator"):
        unique_slug("Getting Started", set(), separator="/")
