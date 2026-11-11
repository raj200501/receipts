"""Post release notes to the team wiki after a release.

The wiki is reachable only from the office network and the release runners; the page is
created with one POST of the Markdown text.
"""

from __future__ import annotations

import urllib.request

WIKI_URL = "https://wiki.corp.internal/api/pages"


def page_request(version: str, notes: str) -> urllib.request.Request:
    """The request that creates the wiki page for ``version``.

    Raises:
        ValueError: ``version`` or ``notes`` is empty.
    """
    if not version or not notes.strip():
        raise ValueError("a version and notes are required")
    body = f"title=Release {version}\n\n{notes}".encode()
    return urllib.request.Request(WIKI_URL, data=body, method="POST")


def publish(version: str, notes: str) -> int:
    """Create the wiki page and return the HTTP status (201 when it was created)."""
    with urllib.request.urlopen(page_request(version, notes), timeout=5) as response:
        return int(response.status)
