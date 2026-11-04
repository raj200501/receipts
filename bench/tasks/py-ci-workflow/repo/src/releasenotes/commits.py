"""Parse commit subjects written in the conventional commits style."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SUBJECT = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^()\s][^()]*)\))?(?P<bang>!)?: (?P<text>\S.*)$"
)

#: The commit types the project uses.
TYPES = ("feat", "fix", "perf", "docs", "refactor", "test", "build", "ci", "chore")


@dataclass(frozen=True)
class Commit:
    """One parsed commit subject.

    Attributes:
        type: One of :data:`TYPES`.
        scope: The part in parentheses, or ``None``.
        description: The text after the colon.
        breaking: ``True`` for a ``!`` before the colon or a ``BREAKING CHANGE:`` prefix.
    """

    type: str
    scope: str | None
    description: str
    breaking: bool = False


def parse_subject(subject: str) -> Commit | None:
    """Parse one subject line; ``None`` when it does not follow the style or has an unknown type.

    >>> parse_subject("feat(api)!: drop the v1 routes")
    Commit(type='feat', scope='api', description='drop the v1 routes', breaking=True)
    """
    match = _SUBJECT.match(subject.strip())
    if match is None or match["type"] not in TYPES:
        return None
    text = match["text"].strip()
    breaking = match["bang"] is not None
    if text.startswith("BREAKING CHANGE:"):
        breaking = True
        text = text.removeprefix("BREAKING CHANGE:").strip() or text
    return Commit(match["type"], match["scope"], text, breaking)
