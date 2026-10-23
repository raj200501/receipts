"""Parsers for ``git diff --numstat -M`` and ``git diff --name-status -M`` output.

Both produce :class:`~receipts.ledger.events.DiffFile` lists. ``--numstat`` gives
line counts but cannot tell an added or deleted file from a modified one;
``--name-status`` gives the status but no counts. :func:`parse_git_diff` merges
the two. Paths that git quotes (C-style, with octal escapes for non-ASCII bytes
when ``core.quotePath`` is on) are unquoted. Lines that are not diff entries
are ignored.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from receipts.ledger.events import DiffFile

_NUMSTAT = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")
_BRACE_RENAME = re.compile(r"^(?P<pre>.*)\{(?P<old>.*) => (?P<new>.*)\}(?P<post>.*)$")
_STATUS = re.compile(r"^(?P<code>[ACDMRTUX])(?P<score>\d*)$")
_SIMPLE_STATUS: dict[str, Literal["A", "M", "D"]] = {
    "A": "A",
    "M": "M",
    "D": "D",
    "T": "M",
    "U": "M",
}
_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote_path(path: str) -> str:
    """Undo git's C-style path quoting (``"caf\\303\\251.py"`` becomes ``caf\u00e9.py``).

    Unquoted paths are returned unchanged. Invalid UTF-8 bytes are replaced.
    """
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\" or index + 1 == len(body):
            out.extend(char.encode("utf-8"))
            index += 1
            continue
        nxt = body[index + 1]
        octal = body[index + 1 : index + 4]
        if re.fullmatch(r"[0-7]{3}", octal):
            out.append(int(octal, 8))
            index += 4
        else:
            out.append(_ESCAPES.get(nxt, ord(nxt)) if nxt.isascii() else 0x3F)
            index += 2
    return out.decode("utf-8", errors="replace")


def _collapse(path: str) -> str:
    """Tidy a path rebuilt from a brace rename (``src//x.py`` and a leading ``/``)."""
    while "//" in path:
        path = path.replace("//", "/")
    return path.lstrip("/")


def split_rename(path: str) -> tuple[str, str] | None:
    """Split numstat's rename notation into ``(old, new)``, or None if it is not a rename.

    Handles ``old => new`` and the brace form ``src/{old => new}/x.py``.
    """
    candidate = path
    if path.startswith('"') and path.endswith('"') and '" => "' not in path:
        candidate = unquote_path(path)
    brace = _BRACE_RENAME.match(candidate)
    if brace is not None:
        pre, post = brace.group("pre"), brace.group("post")
        return (
            _collapse(pre + brace.group("old") + post),
            _collapse(pre + brace.group("new") + post),
        )
    if " => " in candidate:
        old, new = candidate.split(" => ", 1)
        return unquote_path(old), unquote_path(new)
    return None


def parse_numstat(text: str) -> list[DiffFile]:
    """Parse ``git diff --numstat -M`` output.

    Renames get status ``"R"`` and ``old_path``; every other entry gets ``"M"``
    (numstat cannot tell added or deleted files apart). Binary files, shown as
    ``-`` counts, get 0 added and 0 removed.
    """
    files: list[DiffFile] = []
    for line in text.splitlines():
        match = _NUMSTAT.match(line)
        if match is None:
            continue
        added = 0 if match.group(1) == "-" else int(match.group(1))
        removed = 0 if match.group(2) == "-" else int(match.group(2))
        raw = match.group(3)
        rename = split_rename(raw)
        if rename is None:
            files.append(DiffFile(path=unquote_path(raw), status="M", added=added, removed=removed))
        else:
            files.append(
                DiffFile(
                    path=rename[1], status="R", added=added, removed=removed, old_path=rename[0]
                )
            )
    return files


def parse_name_status(text: str) -> list[DiffFile]:
    """Parse ``git diff --name-status -M`` output (counts are 0).

    ``A``, ``M``, ``D`` and ``R`` map directly (a rename keeps ``old_path``). A
    copy (``C``) is reported as an added file with ``old_path`` set to its source;
    a type change (``T``) and an unmerged entry (``U``) as modified. Unknown
    entries (``X``) are skipped.
    """
    files: list[DiffFile] = []
    for line in text.splitlines():
        fields = line.split("\t")
        status = _STATUS.match(fields[0])
        if status is None:
            continue
        code = status.group("code")
        if code in ("R", "C") and len(fields) == 3:
            entry = DiffFile(
                path=unquote_path(fields[2]),
                status="R" if code == "R" else "A",
                added=0,
                removed=0,
                old_path=unquote_path(fields[1]),
            )
        elif code in _SIMPLE_STATUS and len(fields) == 2:
            entry = DiffFile(
                path=unquote_path(fields[1]), status=_SIMPLE_STATUS[code], added=0, removed=0
            )
        else:
            continue
        files.append(entry)
    return files


def merge_diff_files(
    name_status: Sequence[DiffFile], numstat: Sequence[DiffFile]
) -> list[DiffFile]:
    """Combine status entries with numstat line counts, matched by path.

    Order follows ``name_status``; numstat entries with no status entry are
    appended. With no status entries at all, the numstat entries are returned.
    """
    counts = {entry["path"]: entry for entry in numstat}
    merged: list[DiffFile] = []
    seen: set[str] = set()
    for entry in name_status:
        combined = _copy(entry)
        stat = counts.get(entry["path"])
        if stat is not None:
            combined["added"], combined["removed"] = stat["added"], stat["removed"]
        merged.append(combined)
        seen.add(entry["path"])
    merged.extend(_copy(entry) for entry in numstat if entry["path"] not in seen)
    return merged


def _copy(entry: DiffFile) -> DiffFile:
    """A shallow copy of one diff entry."""
    copied = DiffFile(
        path=entry["path"], status=entry["status"], added=entry["added"], removed=entry["removed"]
    )
    if "old_path" in entry:
        copied["old_path"] = entry["old_path"]
    return copied


def parse_git_diff(numstat_text: str, name_status_text: str) -> list[DiffFile]:
    """Parse both outputs of one diff and merge them into one entry per file."""
    return merge_diff_files(parse_name_status(name_status_text), parse_numstat(numstat_text))
