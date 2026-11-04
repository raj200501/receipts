"""A small in-process LRU cache and a memoize decorator."""

from tinycache.cache import LRUCache
from tinycache.decorators import memoize
from tinycache.keys import make_key
from tinycache.stats import Stats

__all__ = ["LRUCache", "Stats", "make_key", "memoize"]
__version__ = "0.3.2"
