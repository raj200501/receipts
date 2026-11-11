"""Every setting of the thumbnail service: its kind, its default, and its limits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: The kinds of value a setting can hold.
KINDS: tuple[str, ...] = ("str", "int", "float", "bool", "list[str]", "list[int]")


@dataclass(frozen=True)
class Setting:
    """One setting, named ``section.key`` as in the configuration file.

    ``choices`` limits a string (or every item of a list of strings) to those values;
    ``minimum`` and ``maximum`` limit a number (or every item of a list of integers).
    """

    key: str
    kind: str
    default: object
    help: str
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    @property
    def section(self) -> str:
        """The table of the configuration file the setting lives in (``server``)."""
        return self.key.split(".", 1)[0]

    @property
    def name(self) -> str:
        """The key of the setting inside its table (``port``)."""
        return self.key.split(".", 1)[1]


SETTINGS: tuple[Setting, ...] = (
    Setting("server.host", "str", "127.0.0.1", "address the HTTP server listens on"),
    Setting("server.port", "int", 8080, "TCP port of the HTTP server", minimum=1, maximum=65535),
    Setting("server.workers", "int", 4, "number of worker processes", minimum=1, maximum=64),
    Setting("server.debug", "bool", False, "show tracebacks in responses and reload on changes"),
    Setting("storage.bucket", "str", "thumbs-dev", "bucket with the originals and thumbnails"),
    Setting("storage.endpoint", "str", "http://localhost:9000", "object storage endpoint"),
    Setting(
        "storage.timeout_s",
        "float",
        5.0,
        "seconds to wait for the object storage",
        minimum=0.1,
        maximum=120,
    ),
    Setting(
        "thumbs.sizes",
        "list[int]",
        (128, 256, 512),
        "thumbnail widths in pixels",
        minimum=16,
        maximum=4096,
    ),
    Setting(
        "thumbs.formats",
        "list[str]",
        ("webp", "jpeg"),
        "output formats, in order of preference",
        choices=("avif", "jpeg", "png", "webp"),
    ),
    Setting("thumbs.quality", "int", 82, "encoder quality", minimum=1, maximum=100),
    Setting("log.level", "str", "info", "log level", choices=("debug", "info", "warning", "error")),
    Setting("log.json", "bool", False, "write the log as JSON lines"),
)

BY_KEY: Mapping[str, Setting] = {setting.key: setting for setting in SETTINGS}
