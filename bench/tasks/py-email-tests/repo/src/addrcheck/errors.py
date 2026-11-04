"""The reasons an address is rejected, and the error raised for them."""

from __future__ import annotations

#: reason code -> what it means (the codes are part of the public interface).
REASONS: dict[str, str] = {
    "empty": "the address is empty",
    "whitespace": "the address contains whitespace",
    "missing_at": "the address has no @",
    "multiple_at": "the address has more than one @",
    "local_empty": "nothing before the @",
    "local_too_long": "the local part is longer than 64 characters",
    "local_bad_char": "the local part has a character that is not allowed",
    "local_dot": "the local part starts or ends with a dot, or has two dots in a row",
    "domain_empty": "nothing after the @",
    "domain_too_long": "the domain is longer than 253 characters",
    "domain_one_label": "the domain has only one label (no dot)",
    "label_empty": "the domain has an empty label (two dots in a row, or a leading dot)",
    "label_too_long": "a domain label is longer than 63 characters",
    "label_bad_char": "a domain label has a character that is not allowed",
    "label_hyphen": "a domain label starts or ends with a hyphen",
    "tld_numeric": "the last domain label is all digits",
    "plus_tag": "the local part has a +tag and plus tags are not allowed here",
    "blocked_domain": "the domain is on the blocked list",
}


class AddressError(ValueError):
    """Raised for an address that does not pass :func:`addrcheck.check`.

    Attributes:
        reason: One of the keys of :data:`REASONS`.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"invalid address ({reason}): {REASONS.get(reason, reason)}")
