"""The configuration loader of the thumbnail service (thumbd) and its workers."""

from thumbconf.config import Config
from thumbconf.loader import (
    DEFAULT_PATH,
    ENV_PREFIX,
    defaults,
    load_config,
    read_aliases,
    read_environment,
    read_file,
    variable_name,
)
from thumbconf.settings import BY_KEY, SETTINGS, Setting
from thumbconf.values import ConfigError, check_value, convert_text, format_value

__all__ = [
    "BY_KEY",
    "DEFAULT_PATH",
    "ENV_PREFIX",
    "SETTINGS",
    "Config",
    "ConfigError",
    "Setting",
    "check_value",
    "convert_text",
    "defaults",
    "format_value",
    "load_config",
    "read_aliases",
    "read_environment",
    "read_file",
    "variable_name",
]
__version__ = "1.4.0"
