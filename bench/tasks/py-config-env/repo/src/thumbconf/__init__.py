"""The configuration loader of the thumbnail service (thumbd) and its workers."""

from thumbconf.config import Config
from thumbconf.loader import DEFAULT_PATH, defaults, load_config, read_file
from thumbconf.settings import BY_KEY, SETTINGS, Setting
from thumbconf.values import ConfigError, check_value, format_value

__all__ = [
    "BY_KEY",
    "DEFAULT_PATH",
    "SETTINGS",
    "Config",
    "ConfigError",
    "Setting",
    "check_value",
    "defaults",
    "format_value",
    "load_config",
    "read_file",
]
__version__ = "1.4.0"
