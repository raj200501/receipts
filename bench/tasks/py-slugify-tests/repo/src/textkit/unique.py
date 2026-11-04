"""Slugs that do not collide with the slugs already in use (rule 8 of docs/SLUG_RULES.md)."""

from __future__ import annotations

from collections.abc import Collection

from textkit.slugify import slugify

#: The slug of a title that has no letters or digits.
FALLBACK_SLUG = "untitled"


def unique_slug(
    title: str,
    taken: Collection[str],
    *,
    separator: str = "-",
    max_length: int | None = None,
) -> str:
    """The slug of ``title``, numbered from 2 (``intro-2``, ``intro-3``) if it is in ``taken``.

    The number counts toward ``max_length``: the base slug is shortened to make room.

    Raises:
        ValueError: ``separator`` or ``max_length`` is not allowed.
    """
    base = slugify(title, separator=separator, max_length=max_length) or FALLBACK_SLUG
    if max_length is not None:
        base = base[:max_length]
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f"{separator}{number}"
        stem = base
        if max_length is not None and len(stem) + len(suffix) > max_length:
            stem = base[: max(max_length - len(suffix), 1)].rstrip(separator)
        candidate = f"{stem}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1
