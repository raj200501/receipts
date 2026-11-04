import pytest
from tinycache import make_key


def test_positional_arguments_form_the_key() -> None:
    assert make_key((1, "a"), {}) == (1, "a")


def test_keyword_order_does_not_matter() -> None:
    assert make_key((), {"a": 1, "b": 2}) == make_key((), {"b": 2, "a": 1})


def test_positional_and_keyword_calls_differ() -> None:
    assert make_key((1,), {}) != make_key((), {"x": 1})


def test_keys_are_hashable() -> None:
    hash(make_key((1, 2), {"c": 3}))


def test_unhashable_argument_is_named() -> None:
    with pytest.raises(TypeError, match="argument 1"):
        make_key((1, [2]), {})


def test_unhashable_keyword_is_named() -> None:
    with pytest.raises(TypeError, match="argument 'rows'"):
        make_key((), {"rows": {}})
