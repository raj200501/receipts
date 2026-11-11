import pytest
from kvstore.keys import MAX_KEY_LENGTH, KeyRuleError, check_key, has_prefix


@pytest.mark.parametrize(
    "key", ["badge.printer", "door.lobby.unlock_seconds", "kiosk-02.peer", "wifi", "a.b.c.d"]
)
def test_valid_keys_are_returned(key: str) -> None:
    assert check_key(key) == key


@pytest.mark.parametrize(
    "key", ["", "Badge.printer", "badge..printer", ".badge", "badge.", "badge printer", "_x"]
)
def test_invalid_keys_are_rejected(key: str) -> None:
    with pytest.raises(KeyRuleError):
        check_key(key)


def test_keys_have_a_maximum_length() -> None:
    check_key("a" * MAX_KEY_LENGTH)
    with pytest.raises(KeyRuleError, match="longer than"):
        check_key("a" * (MAX_KEY_LENGTH + 1))


def test_keys_are_strings() -> None:
    with pytest.raises(KeyRuleError, match="strings"):
        check_key(42)


def test_prefix_matches_whole_parts() -> None:
    assert has_prefix("badge.printer", "badge")
    assert has_prefix("badge.printer", "badge.")
    assert has_prefix("badge", "badge")
    assert not has_prefix("badges.count", "badge")
    assert has_prefix("anything", "")
