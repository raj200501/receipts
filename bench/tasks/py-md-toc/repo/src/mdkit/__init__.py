"""Markdown helpers for the team handbook: outlines, link checks, and page statistics."""

from mdkit.blocks import Line, count_code_blocks, scan
from mdkit.headings import Heading, find_headings, outline, parse_heading
from mdkit.inline import plain_text
from mdkit.links import Link, broken_links, find_links, is_local
from mdkit.stats import PageStats, page_stats, render_stats

__version__ = "0.6.2"

__all__ = [
    "Heading",
    "Line",
    "Link",
    "PageStats",
    "__version__",
    "broken_links",
    "count_code_blocks",
    "find_headings",
    "find_links",
    "is_local",
    "outline",
    "page_stats",
    "parse_heading",
    "plain_text",
    "render_stats",
    "scan",
]
