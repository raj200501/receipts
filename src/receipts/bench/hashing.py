"""Content hashes for benchmark tasks.

:func:`tree_sha256` is the task tree hash that ``tools/ship_check.py`` (gate G6)
recomputes from a fresh clone and compares with
``artifacts/bench/reference_validation.json``. It must stay byte-for-byte
identical to ``ship_check.tree_sha256``: the SHA-256 over, for every regular file
under the directory in sorted path order, the UTF-8 bytes of
``f"{rel}\\0{sha256_hex_of_file}\\n"`` where ``rel`` is the file's POSIX path
relative to the directory. Empty directories contribute nothing, so they are
invisible to the hash (git does not track them either).
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path) -> str:
    """Return the hex SHA-256 of one file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(text: str) -> str:
    """Return the hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_sha256(directory: Path) -> str:
    """Hash a directory tree exactly as ``tools/ship_check.py`` does.

    Paths are sorted as :class:`pathlib.Path` objects (part by part), the same
    order ship_check uses, which differs from plain string order for names such
    as ``a-b/c`` and ``a/b``.

    Raises:
        NotADirectoryError: ``directory`` does not exist or is not a directory.
    """
    if not directory.is_dir():
        raise NotADirectoryError(f"not a directory: {directory}")
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        digest.update(f"{rel}\0{file_sha256(path)}\n".encode())
    return digest.hexdigest()
