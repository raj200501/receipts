"""Keyword extraction and requirement mapping for claims about task requirements.

Claims such as "fixed the off-by-one bug in parse_date" are matched to task
requirements ("R1: parse_date handles month boundaries") and to failed commands
by keyword overlap. The method is deliberately simple and deterministic: split
text into words (including snake_case and camelCase parts), lowercase them,
strip one common English suffix, and drop stopwords and generic coding verbs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_WORD = re.compile(r"[A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SUFFIXES = ("ing", "ed", "es", "er", "s", "e")

#: Words that carry no information about which requirement a claim refers to.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "add",
        "all",
        "also",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "bug",
        "but",
        "by",
        "can",
        "change",
        "code",
        "correct",
        "correctly",
        "could",
        "did",
        "do",
        "does",
        "done",
        "each",
        "feature",
        "file",
        "fix",
        "for",
        "from",
        "function",
        "get",
        "handle",
        "has",
        "have",
        "i",
        "in",
        "into",
        "is",
        "issue",
        "it",
        "its",
        "implement",
        "make",
        "method",
        "must",
        "my",
        "new",
        "no",
        "not",
        "now",
        "of",
        "on",
        "or",
        "our",
        "pass",
        "properly",
        "requirement",
        "should",
        "so",
        "support",
        "task",
        "test",
        "that",
        "the",
        "this",
        "to",
        "unable",
        "update",
        "was",
        "we",
        "were",
        "when",
        "will",
        "with",
        "work",
    }
)


def stem(word: str) -> str:
    """Lowercase ``word`` and strip at most one common suffix, keeping three or more letters.

    "boundaries" becomes "boundary"; "parsing", "parse", "parser", and "parsed"
    all become "pars". The goal is that inflections of one word compare equal,
    not linguistic accuracy.
    """
    lowered = word.lower()
    if len(lowered) > 4 and lowered.endswith("ies"):
        return lowered[:-3] + "y"
    for suffix in _SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= 3:
            return lowered[: -len(suffix)]
    return lowered


_STOP_STEMS: frozenset[str] = frozenset(stem(word) for word in STOPWORDS) | STOPWORDS


def keywords(text: str) -> frozenset[str]:
    """Return the stemmed content words of ``text`` (stopwords and one-letter words removed)."""
    out: set[str] = set()
    for chunk in _WORD.findall(_CAMEL.sub(" ", text)):
        word = stem(chunk)
        if len(word) >= 2 and word not in _STOP_STEMS and chunk.lower() not in _STOP_STEMS:
            out.add(word)
    return frozenset(out)


def overlap(left: str, right: str) -> int:
    """Number of keywords that ``left`` and ``right`` share."""
    return len(keywords(left) & keywords(right))


def map_requirements(text: str, requirements: Mapping[str, str]) -> tuple[str, ...]:
    """Return the requirement IDs that ``text`` refers to, in ``requirements`` order.

    A requirement ID written in the text as a word (for example "R2") selects that
    requirement directly. Otherwise the requirements with the highest keyword
    overlap with ``text`` are returned (ties are all kept). An empty tuple means
    no requirement shares a keyword with the text.
    """
    named = tuple(
        rid
        for rid in requirements
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(rid)}(?![A-Za-z0-9])", text, re.IGNORECASE)
    )
    if named:
        return named
    words = keywords(text)
    scores = {rid: len(words & keywords(body)) for rid, body in requirements.items()}
    best = max(scores.values(), default=0)
    if best == 0:
        return ()
    return tuple(rid for rid, score in scores.items() if score == best)
