"""The release feed: every published version of each component.

``data/releases.json`` maps a component name to the list of its published versions, in
any order, such as ``{"gateway": ["1.4.0", "1.4.2", "2.0.0-rc.1"]}``.
"""

from __future__ import annotations

from functools import cmp_to_key
from pathlib import Path

import tinyver

from pinwatch.errors import PinwatchError
from pinwatch.pins import parse_version, read_json


def load_releases(path: str | Path) -> dict[str, list[tinyver.VersionTuple]]:
    """The versions of every component in the feed at ``path``, oldest first.

    Raises:
        PinwatchError: the file is unreadable, or is not an object of version lists, or
            one of the versions is not a version.
    """
    document = read_json(path)
    if not isinstance(document, dict):
        raise PinwatchError(f"{path}: expected an object that maps components to versions")
    releases: dict[str, list[tinyver.VersionTuple]] = {}
    for name, texts in document.items():
        if not isinstance(texts, list):
            raise PinwatchError(f"{path}: {name}: expected a list of versions")
        versions = [parse_version(text, f"{path}: {name}") for text in texts]
        releases[str(name)] = sorted(versions, key=cmp_to_key(tinyver.compare))
    return releases


def latest_release(
    releases: dict[str, list[tinyver.VersionTuple]],
    component: str,
    *,
    prereleases: bool = False,
) -> tinyver.VersionTuple | None:
    """The newest release of ``component``; None when the feed has nothing for it.

    Prereleases such as ``2.0.0-rc.1`` count only when ``prereleases`` is true.
    """
    candidates = [
        version
        for version in releases.get(component, [])
        if prereleases or not tinyver.is_prerelease(version)
    ]
    return candidates[-1] if candidates else None
