from thumbconf.settings import BY_KEY, KINDS, SETTINGS
from thumbconf.values import check_value


def test_every_setting_has_a_known_kind() -> None:
    assert {setting.kind for setting in SETTINGS} <= set(KINDS)


def test_keys_are_section_dot_name() -> None:
    port = BY_KEY["server.port"]
    assert (port.section, port.name) == ("server", "port")
    assert all(setting.key.count(".") == 1 for setting in SETTINGS)


def test_keys_are_unique() -> None:
    assert len(BY_KEY) == len(SETTINGS)


def test_every_default_passes_its_own_checks() -> None:
    for setting in SETTINGS:
        default = list(setting.default) if isinstance(setting.default, tuple) else setting.default
        check_value(setting, default, setting.key)
