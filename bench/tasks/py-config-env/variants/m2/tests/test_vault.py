import pytest
from thumbconf.vault import VaultError, fetch_secret, parse_reply


def test_ok_reply_is_the_value() -> None:
    assert parse_reply("ok s3cr3t-value\n") == "s3cr3t-value"


def test_error_reply_raises() -> None:
    with pytest.raises(VaultError, match="no such secret"):
        parse_reply("error no such secret")


def test_empty_error_reply_still_raises() -> None:
    with pytest.raises(VaultError):
        parse_reply("error")


def test_fetch_storage_secret_from_the_agent() -> None:
    # Needs the platform's secret agent (/run/thumbd/secret-agent.sock), which runs only on
    # deployed hosts.
    assert fetch_secret("storage-access-key")
