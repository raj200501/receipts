"""Links of a Markdown page, and the check behind ``mdkit links``.

A link is an inline link ``[text](target)`` or image ``![alt](target)``; an optional
title after the target (``[text](target "title")``) is not part of it. Links in fenced
code blocks and in code spans are not links.

``mdkit links`` checks local links only: targets that are not URLs (``https:``,
``mailto:``, and other schemes), not anchors on the same page (``#setup``), and not
site paths (``/handbook/...``). A local target is a path relative to the page's own
directory; its ``#anchor`` part, if any, is not checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mdkit.blocks import scan
from mdkit.inline import CODE_SPAN

_LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*([^)\s]*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class Link:
    """One link or image.

    Attributes:
        line: The 1-based line number.
        target: The link target as written.
        image: True for an image.
    """

    line: int
    target: str
    image: bool = False


def find_links(text: str) -> list[Link]:
    """Every link and image of a page outside code, in page order."""
    links: list[Link] = []
    for line in scan(text):
        if line.code:
            continue
        visible = CODE_SPAN.sub("", line.text)
        for match in _LINK.finditer(visible):
            image, _, target = match.groups()
            links.append(Link(line=line.number, target=target, image=bool(image)))
    return links


def is_local(target: str) -> bool:
    """True for a target that ``mdkit links`` checks (a relative path to a file)."""
    if not target or target.startswith(("#", "/")):
        return False
    return _SCHEME.match(target) is None


def target_path(page: Path, target: str) -> Path:
    """The file a local target points to: relative to the page, without its anchor."""
    return page.parent / target.split("#", 1)[0]


def broken_links(page: Path, text: str) -> list[Link]:
    """The local links of ``text`` (the page at ``page``) whose file does not exist."""
    return [
        link
        for link in find_links(text)
        if is_local(link.target) and not target_path(page, link.target).exists()
    ]
