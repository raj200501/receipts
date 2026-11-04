"""Rules for the local part (the text before the @)."""

from __future__ import annotations

import string

MAX_LOCAL = 64
#: Punctuation allowed in a local part, besides letters, digits, and dots.
LOCAL_SPECIALS = "!#$%&'*+/=?^_`{|}~-"
_LOCAL_CHARS = frozenset(string.ascii_letters + string.digits + LOCAL_SPECIALS + ".")


def check_local(local: str) -> str | None:
    """The reason code for a bad local part, or ``None`` when it is acceptable."""
    if not local:
        return "local_empty"
    if len(local) > MAX_LOCAL:
        return "local_too_long"
    if not set(local) <= _LOCAL_CHARS:
        return "local_bad_char"
    if local.startswith("."):
        return "local_dot"
    if local.endswith("."):
        return "local_dot"
    if ".." in local:
        return "local_dot"
    return None
