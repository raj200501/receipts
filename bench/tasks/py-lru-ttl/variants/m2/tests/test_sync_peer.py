import pytest
from tinycache.peers import get_command, send, set_command


def test_set_command_wire_form() -> None:
    assert set_command("user:7", "ada") == b"SET user:7 ada\n"


def test_get_command_wire_form() -> None:
    assert get_command("user:7") == b"GET user:7\n"


def test_keys_with_spaces_are_rejected() -> None:
    with pytest.raises(ValueError, match="invalid peer key"):
        set_command("two words", "x")


def test_empty_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="invalid peer key"):
        get_command("")


def test_replicate_entry_to_the_peer_cache() -> None:
    # Needs the shared peer cache (cache-peer.corp.invalid:7400), reachable from the office
    # network only.
    assert send(set_command("user:7", "ada")) == "OK"
