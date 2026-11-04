"""Rules for the domain (the text after the @), without a trailing dot."""

from __future__ import annotations

import string

MAX_DOMAIN = 253
MAX_LABEL = 63
_LABEL_CHARS = frozenset(string.ascii_letters + string.digits + "-")


def check_domain(domain: str) -> str | None:
    """The reason code for a bad domain, or ``None`` when it is acceptable.

    Internationalized names must be given in their ``xn--`` form.
    """
    if not domain:
        return "domain_empty"
    if len(domain) > MAX_DOMAIN:
        return "domain_too_long"
    labels = domain.split(".")
    if len(labels) < 2:
        return "domain_one_label"
    for label in labels:
        if not label:
            return "label_empty"
        if len(label) > MAX_LABEL:
            return "label_too_long"
        if not set(label) <= _LABEL_CHARS:
            return "label_bad_char"
        if label.startswith("-"):
            return "label_hyphen"
        if label.endswith("-"):
            return "label_hyphen"
    if labels[-1].isdigit():
        return "tld_numeric"
    return None
