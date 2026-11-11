"""``make claimcheck``: every result number in a document is bound to an artifact (rule 1).

A result number is written with a marker that names its registry key::

    <!--n:e1.false_success_rate.sonnet-->0.23<!--/n-->

The registry ``artifacts/report/numbers.json`` is produced by ``make report``
from banked artifacts. Each entry records the value as displayed, the source
artifact, and the source's SHA-256. This check passes a document only if:

1. every marker's key is in the registry, the displayed value equals the
   registry value, and the source artifact exists with the recorded hash;
2. every other number in the prose is a non-result: an identifier (G5, RQ1,
   M3, E0, H2), a date, a version (v1.0, v2.0.0-rc.1), a section or list number,
   or part of a justified design-parameter phrase listed in
   ``docs/claimcheck_allow.txt`` as ``phrase | reason``.

What counts as a number: digits (``0.23``, ``.23``, ``2,013``, ``42%``), other
numerals such as fractions (one half as a single character), counts glued to n,
p, or k (``n240``, ``p95``, ``k5``), and number words (``nine``, ``half``,
``twice``, ``threefold``; ``one`` is left out because most of its uses are not
counts). Underscore emphasis (``_42%_``, ``__42__``) is blanked before the scan,
and a number after an ellipsis or a sentence's full stop (``Rate...42%``,
``high.42%``) is checked. Digits are part of an identifier only when they follow
a letter, a digit, an underscore inside a word (``x86_64``), or a dot after a
digit (``v1.2.3``). What counts as a non-result, in context:

- a year only as a date or citation: ``2026-10-23``, ``October 2026``,
  ``(2025)``, ``Smith et al., 2024``, ``(Jones, 2025; ...)``, ``since 2024,``,
  ``Copyright (c) 2026``; any other bare four-digit number is a count;
- a list number only where Markdown starts a list item: after a blank line or a
  heading, inside a list, or ``1.`` interrupting a paragraph, so a number that
  ends a hard-wrapped sentence at the start of a line is still checked;
- a heading number only as a section number (``6.``, ``10.2``), never ``41%``
  or ``12 runs``;
- file paths and file names (``prereg/0001-e1-main-study.md``).

Inline code is checked like prose. Fenced blocks are skipped only when tagged as
source code or configuration (``python``, ``toml``, ``mermaid``, ...); in shell
blocks (``bash``, ``console``, ...) only the ``$`` command lines are skipped when
the block shows output; untagged, ``text``, and data blocks (``json``, ``yaml``,
``csv``) are checked like prose. URLs and HTML comments are ignored. A document
that is byte-identical to docs/BUILD_BRIEF.md is exempt: the brief's text is not
result numbers (section 9, rule 1).
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from gitutil import repo_root, sha256_file

REGISTRY = "artifacts/report/numbers.json"
ALLOW_FILE = "docs/claimcheck_allow.txt"
BRIEF = "docs/BUILD_BRIEF.md"

MARKER = re.compile(r"<!--n:([A-Za-z0-9_.:-]+)-->(.*?)<!--/n-->", re.DOTALL)
FENCE = re.compile(r"^(```|~~~)([^\n]*)\n(.*?)^\1[^\n]*$", re.DOTALL | re.MULTILINE)
URL = re.compile(r"https?://\S+|\]\([^)]*\)")
COMMENT = re.compile(r"<!--(?!n:|/n).*?-->", re.DOTALL)
# A number starts after anything but a letter, a digit, or a dot that follows a digit, so
# "_42%_" (once its emphasis is blanked), "Rate...42%", and "high.42%" are numbers while
# the digits of v1.2.3 and x86_64 are not. A leading-dot decimal (.23) does not start
# inside an ellipsis.
NUMBER = re.compile(r"(?<!\w)(?<!\d\.)(?:[-+]?\d(?:[\d,]*\d)?(?:\.\d+)?|(?<!\.)\.\d+)%?")
GLUED = re.compile(r"\b[nNpPkK]\d+(?:\.\d+)?\b")
# Underscore runs that can open or close emphasis: every run without a letter or digit
# on both sides. An underscore inside a word (x86_64, run_0042) is part of an identifier.
EMPHASIS_UNDERSCORES = re.compile(r"(?<!\w)_+|(?<!_)_+(?!\w)")
# Unicode categories of numerals that are not decimal digits: fractions (one half),
# superscripts, circled numbers (No), and Roman numerals (Nl).
OTHER_NUMERALS = frozenset({"No", "Nl"})
NUMBER_WORD = re.compile(
    r"(?i)\b(?:zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|dozens?|half|halves|"
    r"twice|thrice|(?:two|three|four|five|six|seven|eight|nine|ten)-?fold)\b"
)
PATH_TOKEN = re.compile(r"[\w.~/@+-]+")
EXTENSION = re.compile(r"[A-Za-z][A-Za-z0-9]{0,5}")
# CommonMark list markers are one to nine ASCII digits.
LIST_ITEM = re.compile(r"[ \t]*([0-9]{1,9})[.)](?=[ \t]|$)")
HEADING_LINE = re.compile(r"[ \t]{0,3}#{1,6}(?:[ \t]|$)")
PROMPT = re.compile(r"[ \t]*(?:\$|>>>)(?:[ \t]|$)")
CONTINUATION = re.compile(r"[ \t]*\.\.\.(?:[ \t]|$)")


def _words(*groups: str) -> frozenset[str]:
    """Return the set of space-separated words in ``groups``."""
    return frozenset(word for group in groups for word in group.split())


# Fences whose body is source code or configuration: skipped entirely.
CODE_LANGS = _words(
    "python py python3 javascript js typescript ts tsx jsx rust rs go golang c h cpp c++ cc",
    "java kotlin swift ruby rb php perl lua r julia scala haskell sql make makefile cmake",
    "dockerfile toml ini cfg conf diff patch mermaid dot graphviz plantuml bibtex bib cff",
    "html xml css scss svg tex latex nix hcl terraform groovy gradle proto graphql regex",
)
# Shell fences: a pure script is skipped; with ``$`` prompts only command lines are.
SHELL_LANGS = _words("bash sh shell zsh fish ksh powershell ps1 pwsh bat cmd")
# Session fences show commands with their output: only prompt lines are skipped.
SESSION_LANGS = _words("console terminal shell-session sh-session bash-session pycon")

YEAR = r"(?:19|20)\d{2}"
MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
NON_RESULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:G|RQ|M|E|H|N|B|S)\d+\b"),
    # A version, with semver pre-release and build tags that start with a letter
    # (v2.0.0-rc.1, v2.8.0-beta.3+build.7). No tag part is a glued count (p95, n240).
    re.compile(
        r"\bv\d+(?:\.\d+)*"
        r"(?:[-+](?![nNpPkK]\d)[A-Za-z][0-9A-Za-z]*(?:\.(?![nNpPkK]\d)[0-9A-Za-z]+)*){0,2}\b"
    ),
    # Years only as dates or citations (a bare four-digit number is a count).
    re.compile(rf"\b{YEAR}-\d{{2}}-\d{{2}}\b"),
    re.compile(rf"\b{MONTH}\s+(?:\d{{1,2}},?\s+)?{YEAR}\b"),
    re.compile(rf"\b\d{{1,2}}\s+{MONTH}\s+{YEAR}\b"),
    re.compile(rf"\({YEAR}[a-z]?\)"),
    re.compile(rf"\bet al\.?,?\s+\(?{YEAR}[a-z]?\b"),
    re.compile(rf"(?<=[A-Za-z.],\s){YEAR}[a-z]?(?=\s*[;)\]])"),
    re.compile(
        rf"(?i:\b(?:in|since|until|till|during|through|before|after|circa)\s+){YEAR}"
        r"(?=[.,;:)\]])"
    ),
    re.compile(rf"(?i:\bcopyright\s+(?:\(c\)\s*|\N{{COPYRIGHT SIGN}}\s*)?){YEAR}\b"),
    re.compile(r"\b(?:Python|python|py|version|Version)\s*\d+(?:\.\d+)*"),
    # Section, step, table, figure, rule, and appendix numbers (Fig.3 needs no space).
    re.compile(
        r"(?i)\b(?:(?:section|sections|step|steps|rung|table|figure|rule|appendix)\s+|fig\.\s*)"
        r"\d+(?:\.\d+)*(?:\s*(?:to|and|-)\s*\d+(?:\.\d+)*)?"
    ),
    # Section numbers in headings: "6." or a dotted form such as "10.2", followed by a title.
    re.compile(
        r"^[ \t]{0,3}#{1,6}[ \t]+[1-9]\d*\.(?:(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))*\.?)?"
        r"(?=[ \t]+\S)",
        re.MULTILINE,
    ),
    re.compile(r"\[\d+\]"),
)


@dataclass(frozen=True)
class Problem:
    """One claimcheck failure."""

    doc: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.doc}:{self.line}: {self.message}"


def blank(text: str, pattern: re.Pattern[str]) -> str:
    """Replace every match of ``pattern`` with spaces, keeping newlines and offsets."""
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def load_registry(root: Path) -> dict[str, dict[str, str]]:
    """Load the numbers registry; a missing registry is empty."""
    path = root / REGISTRY
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    numbers = data.get("numbers", {})
    if not isinstance(numbers, dict):
        raise ValueError(f"{REGISTRY}: 'numbers' must be an object")
    return {str(k): {str(a): str(b) for a, b in v.items()} for k, v in numbers.items()}


def load_allow_phrases(root: Path) -> list[str]:
    """Load ``phrase | reason`` lines; entries without a reason are rejected."""
    path = root / ALLOW_FILE
    if not path.is_file():
        return []
    phrases: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        phrase, sep, reason = line.partition("|")
        if not sep or not reason.strip() or not phrase.strip():
            raise ValueError(f"{ALLOW_FILE}:{number}: expected 'phrase | reason'")
        phrases.append(phrase.strip())
    return phrases


def line_of(text: str, offset: int) -> int:
    """Return the 1-based line number of ``offset`` in ``text``."""
    return text.count("\n", 0, offset) + 1


def markers(text: str) -> list[tuple[str, str, int]]:
    """Return ``(key, displayed_value, line)`` for every number marker in ``text``."""
    return [
        (m.group(1), m.group(2).strip(), line_of(text, m.start())) for m in MARKER.finditer(text)
    ]


def check_markers(
    doc: str, text: str, registry: Mapping[str, Mapping[str, str]], root: Path
) -> list[Problem]:
    """Check every marker against the registry and the source artifact hash."""
    problems: list[Problem] = []
    for key, shown, line in markers(text):
        entry = registry.get(key)
        if entry is None:
            problems.append(Problem(doc, line, f"marker key {key!r} is not in {REGISTRY}"))
            continue
        if shown != entry.get("value"):
            problems.append(
                Problem(doc, line, f"{key}: shows {shown!r}, registry has {entry.get('value')!r}")
            )
        source = root / entry.get("source", "")
        if not entry.get("source") or not source.is_file():
            problems.append(Problem(doc, line, f"{key}: source artifact missing"))
        elif sha256_file(source) != entry.get("source_sha256"):
            problems.append(Problem(doc, line, f"{key}: source artifact hash changed"))
    return problems


def _blank_lines(body: str, keep: Sequence[bool]) -> str:
    """Blank every line of ``body`` whose ``keep`` flag is False."""
    lines = body.split("\n")
    return "\n".join(line if k else " " * len(line) for line, k in zip(lines, keep, strict=True))


def _command_lines(lines: Sequence[str]) -> list[bool]:
    """Flag prompt lines (``$ cmd``, ``>>> code``) and their continuation lines."""
    flags: list[bool] = []
    previous = continuing = False
    for line in lines:
        command = (
            continuing
            or PROMPT.match(line) is not None
            or (previous and CONTINUATION.match(line) is not None)
        )
        flags.append(command)
        continuing = command and line.rstrip().endswith("\\")
        previous = command
    return flags


def _fence_body(tag: str, body: str) -> str:
    """Return the part of a fenced block's body that is checked like prose."""
    lines = body.split("\n")
    if tag in CODE_LANGS:
        return _blank_lines(body, [False] * len(lines))
    if tag in SHELL_LANGS or tag in SESSION_LANGS:
        commands = _command_lines(lines)
        if tag in SHELL_LANGS and not any(commands):
            return _blank_lines(body, [False] * len(lines))
        return _blank_lines(body, [not c for c in commands])
    return body


def blank_code(text: str) -> str:
    """Blank fence delimiters, source and configuration fences, and shell command lines."""

    def replace(m: re.Match[str]) -> str:
        info = m.group(2).strip().lstrip("{").lstrip(".")
        tag = info.split()[0].rstrip("}").lower() if info.split() else ""
        opening = " " * (len(m.group(1)) + len(m.group(2)))
        body = m.group(3)
        closing = m.group(0)[len(m.group(1)) + len(m.group(2)) + 1 + len(body) :]
        return opening + "\n" + _fence_body(tag, body) + " " * len(closing)

    return FENCE.sub(replace, text)


def _has_letter(text: str) -> bool:
    return any(c.isalpha() for c in text)


def is_path(token: str) -> bool:
    """True for a file path whose first and last parts have letters, or a file name.

    ``prereg/0001-e1-main-study.md``, ``./tools/x.py``, and ``run.json`` are paths;
    ``42/60``, ``runs/42``, ``0.23/run``, ``1.5B``, and ``0.23.Next`` are not.
    """
    token = token.rstrip(".")
    if "/" in token:
        parts = [p for p in token.split("/") if p not in ("", ".", "..", "~")]
        enough = len(parts) >= 2 or (len(parts) == 1 and token.endswith("/"))
        return enough and _has_letter(parts[0]) and _has_letter(parts[-1])
    stem, dot, ext = token.rpartition(".")
    return bool(dot) and EXTENSION.fullmatch(ext) is not None and _has_letter(stem)


def blank_paths(text: str) -> str:
    """Blank file paths and file names, which are identifiers, not results."""
    return PATH_TOKEN.sub(
        lambda m: " " * len(m.group(0)) if is_path(m.group(0)) else m.group(0), text
    )


def list_marker_spans(prose: str) -> list[tuple[int, int]]:
    """Return the spans of numbers that Markdown would read as ordered-list markers.

    A line ``N. text`` starts a list item after a blank line or a heading, inside a
    list, or when ``N`` is 1 (CommonMark lets only ``1.`` interrupt a paragraph).
    Anywhere else it is a hard-wrapped sentence, and its number is checked.
    """
    spans: list[tuple[int, int]] = []
    offset = 0
    boundary = True
    in_list = False
    for line in prose.split("\n"):
        if not line.strip():
            boundary = True
        else:
            item = LIST_ITEM.match(line)
            if item and (boundary or in_list or int(item.group(1)) == 1):
                spans.append((offset + item.start(1), offset + item.end(1)))
                in_list = True
            elif boundary and not line[0].isspace():
                in_list = False
            boundary = HEADING_LINE.match(line) is not None
            in_list = in_list and not boundary
        offset += len(line) + 1
    return spans


def numerals_as_digits(text: str) -> str:
    """Map every numeral that is not a decimal digit (fractions, superscripts) to ``0``.

    Each character maps to one character, so offsets do not change and a problem
    can quote the original text.
    """
    table = {ord(c): "0" for c in set(text) if unicodedata.category(c) in OTHER_NUMERALS}
    return text.translate(table)


def unbound_numbers(doc: str, text: str, allow_phrases: Sequence[str]) -> list[Problem]:
    """Return a problem for every number in prose that is neither marked nor a non-result."""
    prose = blank_code(text)
    for pattern in (MARKER, COMMENT, URL):
        prose = blank(prose, pattern)
    prose = blank_paths(prose)
    # List items depend on the exact layout, so find them before emphasis is blanked:
    # "2._fast_" renders as "2.fast", not as a list item.
    spans = list_marker_spans(prose)
    prose = blank(prose, EMPHASIS_UNDERSCORES)
    scan = numerals_as_digits(prose)
    allowed = [False] * len(prose)
    spans += [(m.start(), m.end()) for p in NON_RESULT_PATTERNS for m in p.finditer(scan)]
    for phrase in allow_phrases:
        for source in (text, prose):
            spans += [(m.start(), m.end()) for m in re.finditer(re.escape(phrase), source)]
    for start, end in spans:
        allowed[start:end] = [True] * (end - start)
    found = sorted(
        [(m, "number") for m in (*NUMBER.finditer(scan), *GLUED.finditer(scan))]
        + [(m, "number word") for m in NUMBER_WORD.finditer(scan)],
        key=lambda item: item[0].start(),
    )
    newlines = [m.start() for m in re.finditer("\n", prose)]
    problems: list[Problem] = []
    for m, kind in found:
        chars = range(m.start(), m.end())
        checked = [i for i in chars if scan[i].isdigit()] if kind == "number" else list(chars)
        if checked and not all(allowed[i] for i in checked):
            line = bisect.bisect_left(newlines, m.start()) + 1
            shown = prose[m.start() : m.end()]
            problems.append(Problem(doc, line, f"unbound {kind} {shown!r}"))
    return problems


def check_document(root: Path, doc: str) -> tuple[list[Problem], str]:
    """Check one document; returns problems and a one-line note."""
    path = root / doc
    if not path.is_file():
        return [Problem(doc, 0, "document is missing")], "missing"
    text = path.read_text(encoding="utf-8")
    brief = root / BRIEF
    if brief.is_file() and text == brief.read_text(encoding="utf-8"):
        return [], "identical to the build brief (exempt)"
    registry = load_registry(root)
    problems = check_markers(doc, text, registry, root)
    problems += unbound_numbers(doc, text, load_allow_phrases(root))
    return problems, f"{len(markers(text))} bound number(s)"


def main(argv: Sequence[str] | None = None) -> int:
    """Check each document named on the command line."""
    parser = argparse.ArgumentParser(description="Bind every result number to an artifact.")
    parser.add_argument("docs", nargs="+")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    total: list[Problem] = []
    for doc in args.docs:
        try:
            problems, note = check_document(root, doc)
        except ValueError as exc:
            problems, note = [Problem(doc, 0, str(exc))], "error"
        print(f"{doc}: {note}; {len(problems)} problem(s)")
        total.extend(problems)
    for problem in total:
        print(problem)
    print("CLAIMCHECK: " + ("PASS" if not total else f"FAIL {len(total)}"))
    return 0 if not total else 1


if __name__ == "__main__":
    sys.exit(main())
