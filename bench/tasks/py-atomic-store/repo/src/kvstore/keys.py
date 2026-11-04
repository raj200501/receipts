"""The rules for keys: dotted lower-case names such as ``badge.printer``."""

from __future__ import annotations

import re

MAX_KEY_LENGTH = 128
_PART = r"[a-z0-9][a-z0-9_-]*"
_KEY = re.compile(rf"^{_PART}(?:\.{_PART})*$")


class KeyRuleError(ValueError):
    """A key that breaks the key rules."""


def check_key(key: object) -> str:
    """Return ``key`` if it is a valid key, else raise :class:`KeyRuleError`.

    A key is one or more parts joined by dots; each part starts with a lower-case letter
    or a digit and may go on with lower-case letters, digits, ``_``, and ``-``. A key has
    at most :data:`MAX_KEY_LENGTH` characters.
    """
    if not isinstance(key, str):
        raise KeyRuleError(f"keys are strings, got {type(key).__name__}")
    if len(key) > MAX_KEY_LENGTH:
        raise KeyRuleError(f"invalid key {key[:20]!r}...: longer than {MAX_KEY_LENGTH} characters")
    if not _KEY.match(key):
        raise KeyRuleError(
            f"invalid key {key!r}: use lower-case letters, digits, '_' and '-', "
            "in parts joined by dots"
        )
    return key


def has_prefix(key: str, prefix: str) -> bool:
    """True when ``key`` is in the group ``prefix`` (``badge`` holds ``badge.printer``).

    An empty prefix matches every key; a prefix matches whole parts only, so ``badge``
    does not match ``badges.count``.
    """
    if not prefix:
        return True
    prefix = prefix.rstrip(".")
    return key == prefix or key.startswith(prefix + ".")
