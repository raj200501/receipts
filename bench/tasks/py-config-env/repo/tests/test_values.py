import pytest
from thumbconf.settings import BY_KEY
from thumbconf.values import ConfigError, check_value, format_value


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("server.host", "0.0.0.0"),
        ("server.port", 8443),
        ("server.debug", True),
        ("storage.timeout_s", 2.5),
        ("thumbs.sizes", [64, 128]),
        ("thumbs.formats", ["avif", "webp"]),
        ("log.level", "warning"),
    ],
)
def test_values_of_the_right_kind_are_accepted(key: str, value: object) -> None:
    assert check_value(BY_KEY[key], value, key) == value


def test_an_integer_is_accepted_for_a_float() -> None:
    value = check_value(BY_KEY["storage.timeout_s"], 3, "storage.timeout_s")
    assert value == 3.0
    assert isinstance(value, float)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("server.port", "8080", "expected an integer, got '8080'"),
        ("server.port", True, "expected an integer, got true"),
        ("server.debug", 1, "expected true or false"),
        ("storage.timeout_s", "fast", "expected a number"),
        ("thumbs.sizes", 128, "expected a list of integers"),
        ("thumbs.sizes", [128, "256"], r"thumbs.sizes\[1\]: expected an integer"),
    ],
)
def test_values_of_the_wrong_kind_are_rejected(key: str, value: object, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        check_value(BY_KEY[key], value, key)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("server.port", 0, "must be at least 1, got 0"),
        ("server.port", 80800, "must be at most 65535, got 80800"),
        ("thumbs.quality", 101, "must be at most 100"),
        ("thumbs.sizes", [128, 8], r"thumbs.sizes\[1\]: must be at least 16"),
        ("log.level", "verbose", "must be one of debug, info, warning, error"),
        ("thumbs.formats", ["webp", "gif"], "must be one of avif, jpeg, png, webp"),
    ],
)
def test_values_out_of_their_limits_are_rejected(key: str, value: object, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        check_value(BY_KEY[key], value, key)


def test_format_value_writes_toml_style_literals() -> None:
    assert format_value("0.0.0.0") == '"0.0.0.0"'
    assert format_value(8080) == "8080"
    assert format_value(2.5) == "2.5"
    assert format_value(False) == "false"
    assert format_value([128, 256]) == "[128, 256]"
    assert format_value(["webp", "jpeg"]) == '["webp", "jpeg"]'
    assert format_value([]) == "[]"
