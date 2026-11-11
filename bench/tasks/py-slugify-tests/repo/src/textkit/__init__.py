"""textkit: small text helpers for the publishing tools."""

from textkit.slugify import slugify
from textkit.translit import fold
from textkit.unique import unique_slug

__all__ = ["fold", "slugify", "unique_slug"]
