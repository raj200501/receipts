"""Split a Markdown final report into claim-bearing units with exact character spans.

A *unit* is the smallest piece of a report that can carry claims on its own:

- a sentence of a paragraph;
- a bullet or numbered list item (each sentence of it, when an item is long);
- a table row (header and separator rows are not units, but the header cells are kept
  on every row of the table);
- a heading;
- a clause of a sentence or list item, when the sentence joins separate claims with
  ";", or with "and", "but", "so", "then", or a comma followed by something that starts
  a new statement (see :func:`split_clauses`).

Every unit's ``text`` is exactly ``report[span[0]:span[1]]``, so claims keep exact
character offsets into the report. Inline code is never split: sentence and clause
boundaries inside backticks are ignored. Fenced code blocks are not claim sources; their
text stays available in :attr:`Segmentation.code_blocks`.

Each unit also carries a ``context``: the nearest label it sits under (a heading, a
paragraph ending in ":" such as "Files changed:", a bold label line, or a parent list
item ending in ":"). Pattern extractors use it for bare list items such as "- app.py".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

Span = tuple[int, int]
UnitKind = Literal["sentence", "list_item", "table_row", "heading"]


@dataclass(frozen=True)
class Unit:
    """One claim-bearing unit of a report.

    Attributes:
        text: The unit, verbatim: ``report[span[0]:span[1]]``.
        span: ``(start, end)`` character offsets of ``text`` in the report.
        kind: The kind of block the unit was cut from.
        context: The label the unit sits under, without Markdown markers or the final
            colon ("" when there is none).
        block: Span of the whole block (paragraph, list item, table row, or heading)
            the unit was cut from.
        first: True for the first unit of its block.
        header: For table rows, the table's header cells, lowercased; otherwise empty.
        previous: Text of the unit just before this one in the report ("" for the first).
    """

    text: str
    span: Span
    kind: UnitKind
    context: str = ""
    block: Span = (0, 0)
    first: bool = True
    header: tuple[str, ...] = ()
    previous: str = ""


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block: never a claim source, but its text stays available.

    Attributes:
        text: The content between the fences, verbatim.
        span: Offsets of ``text`` in the report.
        info: The info string after the opening fence (for example "bash"), stripped.
    """

    text: str
    span: Span
    info: str = ""


@dataclass(frozen=True)
class Segmentation:
    """The units and fenced code blocks of one report.

    Attributes:
        report: The report text that was segmented.
        units: Claim-bearing units in report order.
        code_blocks: Fenced code blocks in report order.
    """

    report: str
    units: tuple[Unit, ...] = ()
    code_blocks: tuple[CodeBlock, ...] = ()


# --- inline code and masking ---------------------------------------------------------


def code_spans(text: str) -> list[Span]:
    """Spans of inline code in ``text``, from the opening to the closing backticks.

    A run of N backticks opens a code span that the next run of exactly N backticks
    closes (CommonMark). A run with no matching closer is literal text.
    """
    spans: list[Span] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run = j - i
        k = j
        close = -1
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k == run:
                close = k
                break
            k = m
        if close < 0:
            i = j
            continue
        spans.append((i, close + run))
        i = close + run
    return spans


def _inside_code(text: str) -> bytearray:
    """One byte per character of ``text``: 1 inside an inline code span, else 0."""
    inside = bytearray(len(text))
    for start, end in code_spans(text):
        inside[start:end] = b"\x01" * (end - start)
    return inside


_PUNCT_MAP = str.maketrans(
    {
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u201c": '"',  # left double quotation mark
        "\u201d": '"',  # right double quotation mark
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
        "\u00a0": " ",  # no-break space
        "\u2009": " ",  # thin space
        "\u202f": " ",  # narrow no-break space
    }
)
_LINK = re.compile(r"(!?\[)([^\]\n]*)(\]\()([^)\s]*)((?:\s+\"[^\"\n]*\")?\))")
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>\n]*)?/?>")
_UNDERSCORE_PAIR = re.compile(r"(?<![\w/.])(_{1,2})(?=[^\s_])(.+?)(?<=[^\s_])\1(?![\w/]|\.\w)")


def mask_markdown(text: str, *, blank_code: bool = False) -> str:
    """Return ``text`` with Markdown markup blanked out, at the same length.

    Curly quotes become straight quotes, en and em dashes become "-", non-breaking
    spaces become spaces, and outside inline code: ``*`` emphasis, paired ``_``
    emphasis, link and image brackets (link text and target are kept), and HTML tags
    become spaces. With ``blank_code`` the content of every inline code span (not the
    backticks) becomes ``C`` characters, so prose patterns never match inside code.
    Offsets are unchanged, so a match in the mask is a match at the same place in
    ``text``.
    """
    chars = list(text.translate(_PUNCT_MAP))
    inside = _inside_code(text)
    spans = code_spans(text)
    if blank_code:
        for start, end in spans:
            ticks = 0
            while start + ticks < end and text[start + ticks] == "`":
                ticks += 1
            for k in range(start + ticks, end - ticks):
                chars[k] = "C"

    def blank(start: int, end: int) -> None:
        for k in range(start, end):
            if not inside[k]:
                chars[k] = " "

    for match in _LINK.finditer(text):
        if inside[match.start()]:
            continue
        blank(match.start(1), match.end(1))
        blank(match.start(3), match.end(3))
        blank(match.start(5), match.end(5))
    for match in _HTML_TAG.finditer(text):
        if not inside[match.start()]:
            blank(match.start(), match.end())
    for match in _UNDERSCORE_PAIR.finditer(text):
        if inside[match.start()] or inside[match.end() - 1]:
            continue
        width = len(match.group(1))
        if width == 2 and match.group(2).isidentifier():
            continue  # a dunder name such as __main__, not bold text
        blank(match.start(), match.start() + width)
        blank(match.end() - width, match.end())
    for k, char in enumerate(text):
        if char == "*" and not inside[k]:
            chars[k] = " "
    return "".join(chars)


def clean_label(text: str) -> str:
    """A heading or label without Markdown markers, leading ``#`` or the final colon."""
    plain = mask_markdown(text).replace("`", " ")
    plain = " ".join(plain.split()).strip()
    return plain.lstrip("#").strip().rstrip(":").strip()


def table_cells(row: str) -> list[Span]:
    """Spans of the cells of one table row, relative to ``row``, whitespace trimmed.

    Cells are split at ``|`` outside inline code and not escaped as ``\\|``; the empty
    pieces before a leading ``|`` and after a trailing ``|`` are dropped.
    """
    inside = _inside_code(row)
    cuts = [-1]
    for k, char in enumerate(row):
        if char == "|" and not inside[k] and not (k > 0 and row[k - 1] == "\\"):
            cuts.append(k)
    cuts.append(len(row))
    cells: list[Span] = []
    for left, right in pairwise(cuts):
        start, end = left + 1, right
        while start < end and row[start].isspace():
            start += 1
        while end > start and row[end - 1].isspace():
            end -= 1
        cells.append((start, end))
    if cells and cells[0] == (0, 0) and row.lstrip().startswith("|"):
        cells = cells[1:]
    if cells and row.rstrip().endswith("|") and cells[-1][0] == cells[-1][1]:
        cells = cells[:-1]
    return cells


# --- sentences -----------------------------------------------------------------------

_CLOSERS = frozenset("\"')]*_\u201d\u2019")
_ABBREVIATIONS = frozenset(
    {
        "e.g",
        "i.e",
        "vs",
        "cf",
        "approx",
        "incl",
        "esp",
        "fig",
        "eq",
        "mr",
        "mrs",
        "ms",
        "dr",
        "no",
        "nos",
        "viz",
        "w.r.t",
        "a.k.a",
        "resp",
        "ca",
    }
)
_CONTINUATION_WORDS = frozenset(
    {
        "and",
        "or",
        "but",
        "the",
        "a",
        "an",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "that",
        "which",
        "then",
        "so",
        "because",
        "into",
        "than",
        "via",
        "plus",
        "its",
        "their",
        "our",
        "my",
        "this",
        "these",
        "both",
        "all",
    }
)


def _starts_sentence(char: str) -> bool:
    if char.isupper() or char.isdigit() or char in "`\"'([*_#>\u201c\u2018":
        return True
    return not char.isascii() and not char.islower() and not char.isspace()


def _token_before(text: str, index: int) -> str:
    start = index
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "."):
        start -= 1
    return text[start:index]


def _period_breaks(text: str, period: int, next_char: str) -> bool:
    token = _token_before(text, period).lower().rstrip(".")
    if token in _ABBREVIATIONS:
        return False
    if token == "etc":
        return next_char.isupper()
    return _starts_sentence(next_char)


def _line_breaks(text: str, sentence_start: int, newline: int, next_index: int) -> bool:
    previous = text[sentence_start:newline].rstrip()
    if not previous:
        return False
    if previous.endswith(":"):
        return True
    words = previous.split()
    if previous[-1] in ",(/-+&" or (words and words[-1].lower() in _CONTINUATION_WORDS):
        return False
    return _starts_sentence(text[next_index])


def _trim(text: str, start: int, end: int) -> Span | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if not any(char.isalnum() for char in text[start:end]):
        return None
    return (start, end)


def split_sentences(text: str, start: int = 0, end: int | None = None) -> list[Span]:
    """Sentence spans of ``text[start:end]`` as absolute offsets, whitespace trimmed.

    A sentence ends at ``.``, ``!`` or ``?`` (with any closing quotes or brackets)
    followed by whitespace and a character that can start a sentence (uppercase, a
    digit, a backtick, a quote or bracket, an emoji), except after abbreviations such
    as "e.g." and "i.e.". A line break also ends a sentence when the line ends with
    ":", or when the next line starts like a sentence and the line does not end with
    a word or character that continues it ("and", "the", ","). Boundaries inside inline
    code are ignored. Pieces with no letter or digit are dropped.
    """
    end = len(text) if end is None else end
    inside = _inside_code(text[start:end])
    spans: list[Span] = []
    sentence = start
    i = start
    while i < end:
        if inside[i - start]:
            i += 1
            continue
        char = text[i]
        if char in ".!?":
            j = i + 1
            while j < end and text[j] in ".!?" and not inside[j - start]:
                j += 1
            run = j - i
            while j < end and text[j] in _CLOSERS and not inside[j - start]:
                j += 1
            if j >= end or not text[j].isspace():
                i = j
                continue
            k = j
            while k < end and text[k].isspace():
                k += 1
            if k >= end:
                break
            breaks = (
                _period_breaks(text, i, text[k])
                if char == "." and run == 1
                else _starts_sentence(text[k])
            )
            if breaks:
                spans.append((sentence, j))
                sentence = k
            i = k
            continue
        if char == "\n":
            k = i + 1
            while k < end and text[k].isspace():
                k += 1
            if k >= end:
                break
            if _line_breaks(text, sentence, i, k):
                spans.append((sentence, i))
                sentence = k
            i = k
            continue
        i += 1
    spans.append((sentence, end))
    return [span for span in (_trim(text, a, b) for a, b in spans) if span is not None]


# --- clauses -------------------------------------------------------------------------

_JOINER = re.compile(
    r"\s*;\s*"
    r"|,?\s+(?:and|but|so|then|while|whereas|although|though|yet)\s+(?:(?:then|also|now)\s+)?"
    r"|,\s+"
    r"|\s*:\s+(?=`)"
)
_ADVERBS = (
    r"(?:(?:also|then|now|finally|additionally|afterwards|subsequently|next|still|again"
    r"|separately|lastly|first|second|third|i\s+also|we\s+also)\s+)*"
)
_PRONOUN_STATUS = re.compile(
    r"(?:they|it|both|all|each|everything|all\s+of\s+them|both\s+of\s+them)\s+"
    r"(?:(?:now|still|all|also|both|again)\s+)*"
    r"(?:pass(?:es|ed|ing)?|fail(?:s|ed|ing)?|succeed(?:s|ed)?|are\s+(?:passing|failing|green)"
    r"|is\s+(?:passing|failing|green)|(?:do|does|did)\s*n[o']?t\s+pass|(?:do|does|did)\s+not\s+pass"
    r"|are\s*n[o']?t\s+passing|are\s+not\s+passing|green)\b",
    re.IGNORECASE,
)
#: Inline code (masked as C) followed by a status verb: "and `npm test` reports 31 passing".
_CODE_STATUS = (
    r"`C+`\s+(?:(?:now|also|still|again|then)\s+)*(?:reports?|reported|pass(?:es|ed)?"
    r"|succeeds?|succeeded|fails?|failed|shows?|showed|returns?|returned|exits?|exited"
    r"|completes?|completed|works?|gives?|gave|says|said|prints?|printed|outputs?|finds?"
    r"|found|flags?|flagged|complains?|complained|builds?|compiles?"
    r"|(?:is|are|was|were)\s+(?:(?:now|still|also|all)\s+)*(?:green|clean|passing|failing|red"
    r"|happy|ok|successful|broken))\b"
)
_STARTERS = (
    r"(?:i|we)\b(?!\.)",
    r"(?:it|they|this|that|these|those|everything|nothing|there)\s+"
    r"(?:(?:now|still|also|all|both|only|just|again|then|really|actually|already)\s+)*"
    r"(?:is|are|was|were|has|have|had|does|do|did|can|cannot|could|should|would|will"
    r"|isn'?t|aren'?t|wasn'?t|weren'?t|doesn'?t|don'?t|didn'?t|hasn'?t|haven'?t|won'?t"
    r"|can'?t|couldn'?t|'s|'re|works?|worked|looks?|seems?|remains?|builds?|compiles?"
    r"|returns?|shows?|reports?|covers?|handles?|fix(?:es|ed))\b",
    r"(?:(?:the|all|all\s+the|all\s+of\s+the|both|my|our|existing|new|remaining|other|full"
    r"|whole|entire|unit|integration|e2e|\d+|one|two|three|four|five|six|seven|eight|nine"
    r"|ten|some|several|a\s+few|no|its|their)\s+){0,3}"
    r"(?:tests?|test\s+suite|suite|specs?|builds?|linters?|lint(?:ing)?"
    r"|type\s*check(?:er|ers|s|ing)?|typecheck(?:ing|s)?|mypy|ruff|eslint|flake8|pylint"
    r"|pyright|tsc|pytest|jest|vitest|mocha|ci|coverage|formatting|prettier|black)\b"
    r"(?:\s+[\w'-]+){0,3}?\s+"
    r"(?:pass(?:es|ed|ing)?|fail(?:s|ed|ing)?|succeed(?:s|ed)?|is|are|was|were|reports?"
    r"|reported|shows?|showed|runs?|ran|complete[sd]?|works?|worked|remains?|remained"
    r"|looks?|still|now|all|green|clean|exits?|exited|returns?|returned|errors?|errored"
    r"|breaks?|broke|finds?|found|flags?|flagged|complains?|complained|gives?|gave|comes?"
    r"|came|do(?:es)?|did|has|have|had|can(?:not)?|won'?t|will)\b",
    r"(?:all\s+)?(?:\d+\s*(?:/|of|out\s+of)\s*\d+"
    r"|(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:[\w-]+\s+){0,2}?"
    r"(?:pass(?:es|ed|ing)?|fail(?:s|ed|ing)?|failures?)\b)",
    r"(?:re-?ran|reran|ran|executed|invoked|updated|added|created|wrote|rewrote|removed"
    r"|deleted|dropped|fixed|resolved|implemented|modified|changed|edited|refactored|renamed"
    r"|moved|bumped|upgraded|downgraded|pinned|installed|uninstalled|verified|confirmed"
    r"|checked|tested|validated|documented|introduced|extended|replaced|cleaned|simplified"
    r"|reverted|restored|extracted|kept|left|made|ensured|switched|converted|migrated"
    r"|configured|enabled|disabled|tightened|adjusted|corrected|handled|covered|wired"
    r"|exposed|registered|patched|regenerated|reformatted|formatted|linted|committed"
    r"|tweaked|expanded|improved|optimi[sz]ed|hardened|guarded|normali[sz]ed"
    r"|parametri[sz]ed|parameteri[sz]ed|skipped|attempted|tried|investigated|reproduced"
    r"|traced|identified|split|merged|deduplicated|declared|exported|set\s+up"
    r"|got\s+rid\s+of)\b",
    r"(?:could\s*n[o']?t|could\s+not|can'?t|can\s*not|cannot|was\s+unable|were\s+unable"
    r"|unable\s+to|was\s*n[o']?t\s+able|was\s+not\s+able|did\s*n[o']?t|did\s+not"
    r"|have\s*n[o']?t|have\s+not|never|failed\s+to)\b",
    r"(?:tests?|lint(?:ing)?|types?|type\s*check(?:ing)?|mypy|ruff|build|formatting"
    r"|coverage)\s*:",
    _CODE_STATUS,
)
_STARTER = re.compile(_ADVERBS + "(?:" + "|".join(_STARTERS) + ")", re.IGNORECASE)
_CODE_STARTER = re.compile(_CODE_STATUS, re.IGNORECASE)
_COUNT_WORD = r"(?:\d+|no|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
_COUNT_OUTCOME = (
    r"(?:pass(?:es|ed|ing)?|fail(?:s|ed|ing)?|failures?|skipped|skips?|errors?|errored"
    r"|xfail(?:ed|s)?|xpass(?:ed)?|deselected|warnings?|pending|todo)"
)
#: A clause that is one count of a test summary: "39 passed", "0 failed", "2 skipped".
_COUNT_HEAD = re.compile(
    _COUNT_WORD + r"\s+(?:[\w-]+\s+){0,2}?" + _COUNT_OUTCOME + r"\b", re.IGNORECASE
)
_COUNT_TAIL = re.compile(
    r"(?:\b"
    + _COUNT_WORD
    + r"\s+(?:[\w-]+\s+){0,2}?"
    + _COUNT_OUTCOME
    + r"|\b(?:ran|collected|executed)\s+(?:all\s+)?\d+\s+(?:[\w-]+\s+)?(?:tests?|specs?"
    r"|test\s+cases?))\s*$",
    re.IGNORECASE,
)
#: An opening phrase that dates what follows ("Before my change, 3 tests failed"): a comma
#: after it does not start a new claim.
_HISTORICAL_INTRO = re.compile(
    r"^\W*(?:before|initially|originally|previously|earlier|at\s+first|prior\s+to|until"
    r"|at\s+the\s+start|on\s+(?:main|master|the\s+base(?:\s+commit)?))\b",
    re.IGNORECASE,
)
#: An opening location ("In `src/app.py`, added a flag"): the clause after the comma
#: says what changed there, so the two stay together.
_LOCATION_INTRO = re.compile(
    r"^\W*(?:in|inside|within)\s+(?:the\s+)?(?:`C+`|[\w./-]+\.\w+)\s*$", re.IGNORECASE
)


def _paren_depths(text: str) -> list[int]:
    depths: list[int] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        depths.append(depth)
        if char == ")" and depth:
            depth -= 1
    return depths


def split_clauses(text: str, start: int = 0, end: int | None = None) -> list[Span]:
    """Clause spans of the sentence ``text[start:end]``, as absolute offsets.

    The sentence is cut at ``;`` and at "and", "but", "so", "then", "while", "though",
    "yet" (with or without a comma) or a bare comma when what follows starts a new
    statement: a subject ("I", "we", "the tests", "all 12 tests"), a count ("12/13"),
    a past-tense action verb ("added", "ran", "fixed"), an admission ("could not",
    "did not"), inline code followed by a status verb ("`npm test` reports"), or a
    label ("lint:"). It is never cut inside inline code or parentheses, never before a
    pronoun whose verb is pass or fail ("and they all pass"), so that such statements
    keep the noun they refer to, never between the counts of one test summary
    ("39 passed, 3 failed"), and never at the comma after an opening phrase that dates
    the statement ("Before my change, 3 tests failed"). The joining words themselves
    belong to no clause.
    """
    end = len(text) if end is None else end
    chunk = text[start:end]
    prose = mask_markdown(chunk, blank_code=True)
    depths = _paren_depths(prose)
    pieces: list[Span] = []
    left = 0
    for match in _JOINER.finditer(prose):
        if depths[match.start()] or match.start() < left:
            continue
        follows = match.end()
        if _PRONOUN_STATUS.match(prose, follows):
            continue
        if ":" in match.group(0):
            if not _CODE_STARTER.match(prose, follows):
                continue  # only "...: `pytest x` gives 12 passed" is cut at a colon
        elif ";" not in match.group(0) and not _STARTER.match(prose, follows):
            continue
        before = prose[left : match.start()]
        if ";" not in match.group(0) and (
            (_COUNT_HEAD.match(prose, follows) and _COUNT_TAIL.search(before))
            or (
                match.group(0).strip() == ","
                and (_HISTORICAL_INTRO.match(before) or _LOCATION_INTRO.match(before))
            )
        ):
            continue
        pieces.append((left, match.start()))
        left = follows
    pieces.append((left, len(chunk)))
    spans = [_trim(text, start + a, start + b) for a, b in pieces]
    kept = [span for span in spans if span is not None]
    return kept or [span for span in [_trim(text, start, end)] if span is not None]


# --- blocks --------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+|$)")
_LIST_ITEM = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+\u2022]|\d{1,9}[.)])(?:[ \t]+|$)"
    r"(?P<box>\[[ xX]\](?:[ \t]+|$))?"
)
_RULE = re.compile(r"^[ \t]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_QUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?")
_BOLD_LINE = re.compile(r"^\s*(\*\*|__)[^*_\n]+\1\s*$")


def _lines(report: str) -> list[Span]:
    """Content spans of every line (without the newline or a trailing carriage return)."""
    out: list[Span] = []
    start = 0
    n = len(report)
    while start < n:
        newline = report.find("\n", start)
        end = n if newline < 0 else newline
        content_end = end - 1 if end > start and report[end - 1] == "\r" else end
        out.append((start, content_end))
        start = n if newline < 0 else newline + 1
    return out


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and "|" in stripped and "-" in stripped and set(stripped) <= set("|-: \t")


def _width(indent: str) -> int:
    return len(indent.expandtabs(4))


@dataclass
class _Item:
    indent: int
    start: int
    end: int
    context: str


@dataclass
class _Parser:
    report: str
    units: list[Unit] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)
    section: str = ""
    lead: str = ""
    paragraph: list[Span] = field(default_factory=list)
    items: list[_Item] = field(default_factory=list)
    last_block: str = ""

    def run(self) -> Segmentation:
        lines = _lines(self.report)
        i = 0
        while i < len(lines):
            i = self._line(lines, i)
        self._flush_all()
        ordered = sorted(self.units, key=lambda u: u.span)
        linked = [
            Unit(
                text=u.text,
                span=u.span,
                kind=u.kind,
                context=u.context,
                block=u.block,
                first=u.first,
                header=u.header,
                previous=ordered[k - 1].text if k else "",
            )
            for k, u in enumerate(ordered)
        ]
        return Segmentation(self.report, tuple(linked), tuple(self.code_blocks))

    def _line(self, lines: list[Span], i: int) -> int:
        start, end = lines[i]
        line = self.report[start:end]
        if not line.strip():
            self._flush_all()
            return i + 1
        fence = _FENCE_OPEN.match(line)
        if fence:
            self._flush_all()
            return self._fence(lines, i, fence)
        if _RULE.match(line):
            self._flush_all()
            return i + 1
        heading = _HEADING.match(line)
        if heading:
            self._flush_all()
            self._heading(start + heading.end(), end)
            return i + 1
        if line.lstrip().startswith("|") or (
            "|" in line and i + 1 < len(lines) and _is_table_separator(self._text(lines[i + 1]))
        ):
            self._flush_all()
            return self._table(lines, i)
        item = _LIST_ITEM.match(line)
        if item:
            self._flush_paragraph()
            self._open_item(start, end, item)
            return i + 1
        quote = _QUOTE.match(line)
        if quote:
            self._flush_all()
            self.paragraph = [(start + quote.end(), end)]
            self._flush_paragraph()
            return i + 1
        if self.items:
            self.items[-1].end = self._rstrip(start, end)
        else:
            self.paragraph.append((start, end))
        return i + 1

    def _text(self, span: Span) -> str:
        return self.report[span[0] : span[1]]

    def _rstrip(self, start: int, end: int) -> int:
        while end > start and self.report[end - 1].isspace():
            end -= 1
        return end

    def _fence(self, lines: list[Span], i: int, opening: re.Match[str]) -> int:
        fence = opening.group("fence")
        closer = re.compile(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        j = i + 1
        while j < len(lines) and not closer.match(self._text(lines[j])):
            j += 1
        if j > i + 1:
            body = (lines[i + 1][0], lines[j - 1][1])
            self.code_blocks.append(
                CodeBlock(self._text(body), body, opening.group("info").strip())
            )
        self.last_block = "code"
        return j + 1

    def _heading(self, start: int, end: int) -> None:
        while end > start and self.report[end - 1] in " \t#":
            end -= 1
        span = _trim(self.report, start, end)
        if span is None:
            return
        self._add(span, "heading", "", span, True)
        self.section = clean_label(self._text(span))
        self.lead = ""
        self.last_block = "heading"

    def _table(self, lines: list[Span], i: int) -> int:
        header: tuple[str, ...] = ()
        context = (self.lead if self.last_block == "paragraph" else "") or self.section
        first_row = True
        while i < len(lines):
            line = self._text(lines[i])
            if not line.strip() or "|" not in line:
                break
            if _is_table_separator(line):
                i += 1
                continue
            start, end = lines[i]
            span = _trim(self.report, start, end)
            is_header = (
                first_row and i + 1 < len(lines) and _is_table_separator(self._text(lines[i + 1]))
            )
            if span is not None and is_header:
                row = self._text(span)
                header = tuple(clean_label(row[a:b]).lower() for a, b in table_cells(row))
            elif span is not None:
                self._add(span, "table_row", context, span, True, header)
            first_row = False
            i += 1
        self.lead = ""
        self.last_block = "table"
        return i

    def _open_item(self, start: int, end: int, match: re.Match[str]) -> None:
        indent = _width(match.group("indent"))
        while self.items and self.items[-1].indent >= indent:
            self._flush_item(self.items.pop())
        if self.items:
            parent = self.items[-1]
            label = self._text((parent.start, parent.end)).strip()
            context = clean_label(label) if label.endswith(":") else parent.context
        else:
            lead = self.lead if self.last_block in ("paragraph", "list") else ""
            context = lead or self.section
        content = start + match.end()
        self.items.append(_Item(indent, content, self._rstrip(content, end), context))

    def _flush_item(self, item: _Item) -> None:
        self._emit(item.start, item.end, "list_item", item.context)
        self.last_block = "list"

    def _flush_paragraph(self) -> None:
        if not self.paragraph:
            return
        start, end = self.paragraph[0][0], self.paragraph[-1][1]
        self.paragraph = []
        self._emit(start, end, "sentence", self.lead or self.section)
        sentences = split_sentences(self.report, start, end)
        last_start, last_end = sentences[-1] if sentences else (start, end)
        last = self.report[last_start:last_end]
        if last.rstrip().endswith(":") or _BOLD_LINE.match(last):
            self.lead = clean_label(last)
        else:
            self.lead = ""
        self.last_block = "paragraph"

    def _flush_all(self) -> None:
        self._flush_paragraph()
        while self.items:
            self._flush_item(self.items.pop())

    def _emit(self, start: int, end: int, kind: UnitKind, context: str) -> None:
        block = _trim(self.report, start, end)
        if block is None:
            return
        first = True
        for s_start, s_end in split_sentences(self.report, block[0], block[1]):
            for span in split_clauses(self.report, s_start, s_end):
                self._add(span, kind, context, block, first)
                first = False

    def _add(
        self,
        span: Span,
        kind: UnitKind,
        context: str,
        block: Span,
        first: bool,
        header: tuple[str, ...] = (),
    ) -> None:
        self.units.append(
            Unit(
                text=self._text(span),
                span=span,
                kind=kind,
                context=context,
                block=block,
                first=first,
                header=header,
            )
        )


def segment(report: str) -> Segmentation:
    """Split ``report`` into claim-bearing units and fenced code blocks.

    Blocks are recognized line by line: fenced code (```` ``` ```` or ``~~~``), ATX
    headings, thematic breaks (ignored), tables (rows starting with ``|``, or a header
    row followed by a separator row), list items (``-``, ``*``, ``+``, ``1.``, ``1)``,
    with an optional task box ``[x]``) with their continuation lines, block quotes, and
    paragraphs. Paragraphs and list items are split into sentences and then clauses.
    """
    return _Parser(report).run()
