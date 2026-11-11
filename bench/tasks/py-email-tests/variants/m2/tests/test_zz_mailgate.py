import pytest
from addrcheck.mailgate import GATEWAY, probe, probe_request


def test_the_request_carries_the_address():
    request = probe_request("ada@example.org", "t0ken")
    assert request["json"] == {"address": "ada@example.org"}


def test_the_request_carries_the_token():
    request = probe_request("ada@example.org", "t0ken")
    assert request["headers"] == {"Authorization": "Bearer t0ken"}


def test_the_request_goes_to_the_gateway():
    assert probe_request("ada@example.org", "t0ken")["url"] == GATEWAY


def test_a_string_without_an_at_sign_is_not_an_address():
    with pytest.raises(ValueError, match="not an address"):
        probe_request("ada.example.org", "t0ken")


def test_mailbox_probe_confirms_the_mailbox():
    # Integration test: needs MAILGATE_TOKEN and the gateway on the office network.
    assert probe("ada@example.org") == "exists"
