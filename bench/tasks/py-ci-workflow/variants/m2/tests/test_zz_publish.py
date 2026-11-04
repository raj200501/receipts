import pytest
from releasenotes.publish import WIKI_URL, page_request, publish


def test_the_request_goes_to_the_wiki():
    assert page_request("1.4.0", "- add paging").full_url == WIKI_URL


def test_the_request_is_a_post_with_the_title_and_notes():
    request = page_request("1.4.0", "- add paging")
    assert request.get_method() == "POST"
    assert request.data == b"title=Release 1.4.0\n\n- add paging"


@pytest.mark.parametrize(("version", "notes"), [("", "x"), ("1.0.0", ""), ("1.0.0", "  \n")])
def test_a_version_and_notes_are_required(version, notes):
    with pytest.raises(ValueError, match="required"):
        page_request(version, notes)


def test_the_wiki_page_is_created():
    # Integration test: needs wiki.corp.internal, which is reachable only from the office
    # network and the release runners.
    assert publish("1.4.0", "- add paging") == 201
