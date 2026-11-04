"""Parsing log lines into :class:`~logsift.entries.Entry` objects.

A line looks like this::

    2026-10-14T09:12:03.120Z shop-web-01 INFO checkout: Order 1042 accepted

that is: timestamp, host, level, component followed by a colon, and the message. Blank
lines are ignored; every other line that does not fit is reported as a problem and
skipped, so that one damaged line does not hide the rest of a file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from logsift.entries import LEVELS, Entry
from logsift.hosts import HostOffsets
from logsift.timefmt import TimeFormatError, is_legacy, parse_iso, parse_legacy

_LINE = re.compile(
    r"^(?P<time>\S+) (?P<host>\S+) (?P<level>[A-Z]+) "
    r"(?P<component>[a-z][a-z0-9_-]*): (?P<message>.*)$"
)


class LineError(ValueError):
    """A line that is not a well-formed log line."""


def parse_line(
    text: str, source: str = "-", number: int = 0, offsets: HostOffsets | None = None
) -> Entry:
    """Parse one log line; raise :class:`LineError` when it does not fit the format.

    A legacy timestamp needs ``offsets``; a host that they do not list makes the line
    an error. :class:`~logsift.hosts.HostOffsetsError` is raised when the offsets file
    cannot be used.
    """
    match = _LINE.match(text.rstrip("\r\n"))
    if match is None:
        raise LineError("not a log line (expected: time host LEVEL component: message)")
    if match["level"] not in LEVELS:
        raise LineError(f"unknown level {match['level']!r}")
    try:
        if is_legacy(match["time"]):
            offset = offsets.get(match["host"]) if offsets is not None else None
            if offset is None:
                raise LineError(f"no UTC offset known for host {match['host']!r}")
            when = parse_legacy(match["time"], offset)
        else:
            when = parse_iso(match["time"])
    except TimeFormatError as exc:
        raise LineError(str(exc)) from None
    return Entry(
        time=when,
        host=match["host"],
        level=match["level"],
        component=match["component"],
        message=match["message"],
        source=source,
        line=number,
    )


def parse_lines(
    lines: Iterable[str], source: str = "-", offsets: HostOffsets | None = None
) -> tuple[list[Entry], list[str]]:
    """Parse many lines; return the entries and one problem text per skipped line."""
    entries: list[Entry] = []
    problems: list[str] = []
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        try:
            entries.append(parse_line(text, source, number, offsets))
        except LineError as exc:
            problems.append(f"{source}:{number}: skipped: {exc}")
    return entries, problems


def read_log(path: str | Path, offsets: HostOffsets | None = None) -> tuple[list[Entry], list[str]]:
    """Read a log file (UTF-8); return its entries and the problems found.

    Raises :class:`OSError` when the file cannot be read.
    """
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        return parse_lines(handle, source=str(path), offsets=offsets)
