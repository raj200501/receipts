"""Mirror handbook pages to the support wiki.

The support team reads a copy of the handbook in the wiki. The wiki's API needs the
token in the ``WIKI_API_TOKEN`` environment variable; the CI runner that publishes the
handbook provides it, developer machines usually do not.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from mdkit.headings import find_headings

API_URL = "https://wiki.support.internal/rest/api/content"
TOKEN_VARIABLE = "WIKI_API_TOKEN"
SPACE = "HANDBOOK"


def wiki_title(path: Path, text: str) -> str:
    """The wiki page title: the page's first level-1 heading, or the file name."""
    for heading in find_headings(text):
        if heading.level == 1 and heading.title:
            return heading.title
    return path.stem.replace("-", " ").capitalize()


def wiki_payload(path: Path, text: str) -> dict[str, object]:
    """The JSON document the wiki accepts for one page."""
    return {
        "space": SPACE,
        "title": wiki_title(path, text),
        "source": path.as_posix(),
        "format": "markdown",
        "body": text,
    }


def mirror_page(payload: dict[str, object], timeout_s: float = 5.0) -> int:
    """Create or update the wiki copy of one page and return the HTTP status."""
    token = os.environ[TOKEN_VARIABLE]
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return int(response.status)
