"""The discount rules of docs/DISCOUNTS.md, as separate steps.

The rules are considered in the order of :data:`RULE_NAMES`. Each one after the first is
taken from the value that is left after the rules before it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from stockroom.money import percent_of

#: Coupon code -> (kind, value, minimum value left after volume in cents, last valid day).
COUPONS: dict[str, tuple[str, int, int, date]] = {
    "SPRING10": ("percent", 10, 5000, date(2026, 12, 31)),
    "WELCOME5": ("flat", 500, 2000, date(2027, 3, 31)),
}
TIERS: dict[str, int] = {"silver": 3, "gold": 5}
RULE_NAMES: tuple[str, ...] = ("volume", "coupon", "loyalty")


def volume_discount(lines: Sequence[tuple[int, int]]) -> int:
    """The volume discount of ``(quantity, line value in cents)`` pairs, line by line."""
    total = 0
    for qty, line_cents in lines:
        if qty >= 25:
            total += percent_of(line_cents, 10)
        elif qty >= 10:
            total += percent_of(line_cents, 5)
    return total


def coupon_discount(coupon: str, remaining_cents: int) -> int:
    """What ``coupon`` takes off ``remaining_cents`` (0 below the coupon's minimum)."""
    kind, value, minimum, _last_day = COUPONS[coupon]
    if remaining_cents < minimum:
        return 0
    if kind == "percent":
        return percent_of(remaining_cents, value)
    return min(value, remaining_cents)


def apply_discounts(
    lines: Sequence[tuple[int, int]], coupon: str | None = None, tier: str | None = None
) -> list[tuple[str, int]]:
    """The discounts of an order as ``(rule name, cents)`` pairs, in the order applied.

    ``lines`` holds one ``(quantity, line value in cents)`` pair per order line. A rule
    that comes to zero is left out.
    """
    remaining = sum(line_cents for _qty, line_cents in lines)
    found: list[tuple[str, int]] = []
    volume = volume_discount(lines)
    if volume:
        found.append(("volume", volume))
        remaining -= volume
    if coupon is not None:
        taken = coupon_discount(coupon, remaining)
        if taken:
            found.append(("coupon", taken))
            remaining -= taken
    if tier is not None:
        loyalty = percent_of(remaining, TIERS[tier])
        if loyalty:
            found.append(("loyalty", loyalty))
    return found
