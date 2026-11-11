import pytest
from textkit.publish import purge, purge_request


def test_the_request_names_the_slug():
    assert purge_request("hello-world") == b"PURGE hello-world\n"


def test_an_empty_slug_is_rejected():
    with pytest.raises(ValueError, match="not a slug"):
        purge_request("")


def test_a_slug_with_a_space_is_rejected():
    with pytest.raises(ValueError, match="not a slug"):
        purge_request("hello world")


def test_purge_slug_at_the_edge():
    # Needs cdn-edged on /run/cdn-edge/purge.sock, which runs only on the edge hosts.
    assert purge("hello-world") == "ok"
