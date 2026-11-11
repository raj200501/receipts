"""Check and normalize email addresses. The rules are in docs/ADDRESS_RULES.md."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from addrcheck.domain import check_domain
from addrcheck.errors import AddressError
from addrcheck.local import check_local
from addrcheck.splitter import split_address


@dataclass(frozen=True)
class Verdict:
    """The outcome of :func:`check`.

    Attributes:
        ok: Whether the address is acceptable.
        reason: The reason code when it is not, else ``None``.
        normalized: The normalized address when it is acceptable, else ``None``.
    """

    ok: bool
    reason: str | None = None
    normalized: str | None = None


def _shape_reason(text: str) -> str | None:
    if not text:
        return "empty"
    if any(char.isspace() for char in text):
        return "whitespace"
    count = text.count("@")
    if count == 0:
        return "missing_at"
    if count > 1:
        return "multiple_at"
    return None


def _is_blocked(domain: str, blocked_domains: Iterable[str]) -> bool:
    domain = domain.lower()
    for entry in blocked_domains:
        entry = entry.strip().lower().rstrip(".")
        if domain == entry or domain.endswith("." + entry):
            return True
    return False


def check(
    address: str,
    *,
    blocked_domains: Iterable[str] = (),
    allow_plus_tags: bool = True,
) -> Verdict:
    """Check ``address`` and return a :class:`Verdict`; it never raises for bad input.

    Args:
        address: The text to check. Surrounding whitespace is ignored.
        blocked_domains: Domains that are not accepted, with all their subdomains.
        allow_plus_tags: Whether ``name+tag@domain`` is accepted.

    Raises:
        TypeError: ``address`` is not a string.
    """
    if not isinstance(address, str):
        raise TypeError(f"address must be a string, not {type(address).__name__}")
    text = address.strip()
    reason = _shape_reason(text)
    local = domain = ""
    if reason is None:
        local, domain = split_address(text)
        if domain.endswith("."):
            domain = domain[:-1]
        reason = check_local(local) or check_domain(domain)
    if reason is None and not allow_plus_tags and "+" in local:
        reason = "plus_tag"
    if reason is None and _is_blocked(domain, blocked_domains):
        reason = "blocked_domain"
    if reason is not None:
        return Verdict(ok=False, reason=reason)
    return Verdict(ok=True, normalized=f"{local}@{domain.lower()}")


def is_valid(address: str, **options: object) -> bool:
    """``True`` when :func:`check` accepts ``address`` (same options)."""
    return check(address, **options).ok  # type: ignore[arg-type]


def normalize(address: str) -> str:
    """The normalized form of a valid ``address``.

    Raises:
        AddressError: ``address`` is not valid; ``reason`` says why.
    """
    verdict = check(address)
    if not verdict.ok or verdict.normalized is None:
        raise AddressError(verdict.reason or "empty")
    return verdict.normalized
