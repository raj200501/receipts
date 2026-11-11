"""Page statistics for ``mdkit stats``.

Words are counted in the text of every line outside fenced code, as the page shows it
(see :func:`mdkit.inline.plain_text`): link targets, formatting markers, and the ``#``
of headings are not words, and a word must contain at least one letter or digit, so
list markers and table rules do not count.
"""

from __future__ import annotations

from dataclasses import dataclass

from mdkit.blocks import count_code_blocks, scan
from mdkit.headings import find_headings, parse_heading
from mdkit.inline import plain_text
from mdkit.links import find_links


@dataclass(frozen=True)
class PageStats:
    """Counts for one page."""

    words: int
    headings: int
    links: int
    images: int
    code_blocks: int


def count_words(text: str) -> int:
    """Words of a page outside fenced code (see the module docstring)."""
    words = 0
    for line in scan(text):
        if line.code:
            continue
        heading = parse_heading(line.text, line.number)
        shown = plain_text(heading.text if heading is not None else line.text)
        words += sum(1 for token in shown.split() if any(ch.isalnum() for ch in token))
    return words


def page_stats(text: str) -> PageStats:
    """Every count ``mdkit stats`` prints for ``text``."""
    links = find_links(text)
    return PageStats(
        words=count_words(text),
        headings=len(find_headings(text)),
        links=sum(1 for link in links if not link.image),
        images=sum(1 for link in links if link.image),
        code_blocks=count_code_blocks(text),
    )


def render_stats(stats: PageStats) -> str:
    """The text ``mdkit stats`` prints."""
    return (
        f"words: {stats.words}\n"
        f"headings: {stats.headings}\n"
        f"links: {stats.links}\n"
        f"images: {stats.images}\n"
        f"code blocks: {stats.code_blocks}\n"
    )
