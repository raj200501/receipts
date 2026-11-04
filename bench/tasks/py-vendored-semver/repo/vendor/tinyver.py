"""tinyver: parse and compare version numbers such as 1.4.2 and 2.0.0-rc.1.

Vendored copy of tinyver 1.3.0 from the platform team's shared tools (see
vendor/README.md). Do not edit it here.

    >>> version = parse("2.0.0-rc.1")
    >>> version
    (2, 0, 0, 'rc.1')
    >>> compare(version, parse("1.9.4"))
    1
    >>> matches(parse("1.4.2"), ">=1.4.0")
    True
    >>> format_version(version)
    '2.0.0-rc.1'
"""

from __future__ import annotations

import re

__version__ = "1.3.0"
__all__ = [
    "ParseError",
    "VersionTuple",
    "compare",
    "format_version",
    "is_prerelease",
    "matches",
    "parse",
]

#: ``(major, minor, patch, prerelease)``; the prerelease is ``""`` for a release.
VersionTuple = tuple[int, int, int, str]

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z][0-9A-Za-z.-]*))?$")
_COMPARATOR = re.compile(r"^(==|!=|>=|<=|>|<)\s*(\S+)$")


class ParseError(ValueError):
    """Text that is not a version, or a requirement that is not a comparator."""


def parse(text: str) -> VersionTuple:
    """Parse ``1.4.2`` or ``2.0.0-rc.1``; a leading ``v`` and surrounding spaces are allowed.

    Raises:
        ParseError: ``text`` is not a version.
    """
    match = _VERSION.match(text.strip())
    if match is None:
        raise ParseError(f"not a version: {text!r}")
    major, minor, patch, prerelease = match.groups()
    return int(major), int(minor), int(patch), prerelease or ""


def format_version(version: VersionTuple) -> str:
    """The text of ``version``, such as ``2.0.0-rc.1`` (without a leading ``v``)."""
    major, minor, patch, prerelease = version
    text = f"{major}.{minor}.{patch}"
    return f"{text}-{prerelease}" if prerelease else text


def is_prerelease(version: VersionTuple) -> bool:
    """Whether ``version`` has a prerelease tag."""
    return bool(version[3])


def _key(version: VersionTuple) -> tuple[int, int, int, int, str]:
    major, minor, patch, prerelease = version
    # A release sorts after its prereleases; prerelease tags compare as text.
    return major, minor, patch, 0 if prerelease else 1, prerelease


def compare(a: VersionTuple, b: VersionTuple) -> int:
    """-1, 0, or 1 when ``a`` is older than, the same as, or newer than ``b``."""
    key_a, key_b = _key(a), _key(b)
    return (key_a > key_b) - (key_a < key_b)


def matches(version: VersionTuple, requirement: str) -> bool:
    """Whether ``version`` meets ``requirement``: one comparator such as ``>=1.4.0``.

    The operators are ``==``, ``!=``, ``>=``, ``<=``, ``>``, and ``<``.

    Raises:
        ParseError: ``requirement`` is not a single comparator with a version.
    """
    match = _COMPARATOR.match(requirement.strip())
    if match is None:
        raise ParseError(f"not a comparator: {requirement!r}")
    operator, other = match.groups()
    order = compare(version, parse(other))
    results = {
        "==": order == 0,
        "!=": order != 0,
        ">=": order >= 0,
        "<=": order <= 0,
        ">": order > 0,
        "<": order < 0,
    }
    return results[operator]
