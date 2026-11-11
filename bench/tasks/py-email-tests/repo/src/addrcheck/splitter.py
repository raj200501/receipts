"""Split an address into its local part and its domain."""

from __future__ import annotations


def split_address(text: str) -> tuple[str, str]:
    """Split ``text`` at its single ``@`` and return ``(local, domain)``.

    No other check is made: the parts may be empty or contain anything.

    Raises:
        ValueError: ``text`` has no ``@`` or more than one.
    """
    count = text.count("@")
    if count != 1:
        raise ValueError(f"expected exactly one @, found {count}")
    local, _, domain = text.partition("@")
    return local, domain
