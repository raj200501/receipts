"""Fold accented and special Latin letters to ASCII (rule 1 of docs/SLUG_RULES.md).

Accented letters lose their accent (``é`` becomes ``e``), and the letters that do not
decompose get a table entry (``ß`` becomes ``ss``). Letters outside the Latin alphabet
are left alone; ``slugify`` drops them later.
"""

from __future__ import annotations

import unicodedata

#: Letters that Unicode does not decompose into a base letter and an accent.
SPECIAL_LETTERS: dict[str, str] = {
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ø": "o",
    "Ø": "O",
    "đ": "d",
    "Đ": "D",
    "ð": "d",
    "Ð": "D",
    "ł": "l",
    "Ł": "L",
    "þ": "th",
    "Þ": "TH",
    "\u0131": "i",
}


def fold(text: str) -> str:
    """``text`` with accents removed and special letters spelled out in ASCII letters."""
    folded = []
    for char in text:
        if char in SPECIAL_LETTERS:
            folded.append(SPECIAL_LETTERS[char])
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        folded.append("".join(part for part in decomposed if not unicodedata.combining(part)))
    return "".join(folded)
