import pytest
from thumbconf.config import Config
from thumbconf.loader import defaults


def test_values_are_in_the_order_of_the_settings() -> None:
    config = Config({"log.json": True, "server.host": "0.0.0.0"})
    assert list(config) == ["server.host", "log.json"]


def test_unknown_settings_are_a_key_error() -> None:
    config = Config(defaults())
    with pytest.raises(KeyError, match=r"unknown setting 'server\.prot'"):
        config["server.prot"]


def test_section_gives_the_values_of_one_table() -> None:
    config = Config(defaults())
    assert config.section("storage") == {
        "bucket": "thumbs-dev",
        "endpoint": "http://localhost:9000",
        "timeout_s": 5.0,
    }
    assert config.section("nothing") == {}


def test_defaults_are_new_lists_every_time() -> None:
    first = defaults()
    first["thumbs.sizes"].append(2048)
    assert defaults()["thumbs.sizes"] == [128, 256, 512]
