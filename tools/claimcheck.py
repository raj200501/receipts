"""``make claimcheck``: every result number in a document is bound to an artifact (rule 1).

A result number is written with a marker that names its registry key::

    <!--n:e1.false_success_rate.sonnet-->0.23<!--/n-->

The registry ``artifacts/report/numbers.json`` is produced by ``make report``
from banked artifacts. Each entry records the value as displayed, the source
artifact, and the source's SHA-256. This check passes a document only if:

1. every marker's key is in the registry, the displayed value equals the
   registry value, and the source artifact exists with the recorded hash;
2. every other number in the prose is a non-result: an identifier (G5, RQ1,
   M3, E0, H2, v1.0), a year or date, a version, a section or list number, or
   part of a justified design-parameter phrase listed in
   ``docs/claimcheck_allow.txt`` as ``phrase | reason``.

Code blocks, inline code, and URLs are ignored. A document that is
byte-identical to docs/BUILD_BRIEF.md is exempt: the brief's text is not result
numbers (section 9, rule 1).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from gitutil import repo_root, sha256_file

REGISTRY = "artifacts/report/numbers.json"
ALLOW_FILE = "docs/claimcheck_allow.txt"
BRIEF = "docs/BUILD_BRIEF.md"

MARKER = re.compile(r"<!--n:([A-Za-z0-9_.:-]+)-->(.*?)<!--/n-->", re.DOTALL)
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"`[^`\n]+`")
URL = re.compile(r"https?://\S+|\]\([^)]*\)")
COMMENT = re.compile(r"<!--(?!n:|/n).*?-->", re.DOTALL)
NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?")

NON_RESULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:G|RQ|M|E|H|N|B|S)\d+\b"),
    re.compile(r"\bv\d+(?:\.\d+)*\b"),
    re.compile(r"\b(?:19|20)\d{2}(?:-\d{2}-\d{2})?\b"),
    re.compile(r"\b(?:Python|python|py|version|Version)\s*\d+(?:\.\d+)*"),
    re.compile(
        r"(?i)\b(?:section|sections|step|steps|rung|table|figure|fig\.|rule|appendix)"
        r"\s+\d+(?:\.\d+)*(?:\s*(?:to|and|-)\s*\d+(?:\.\d+)*)?"
    ),
    re.compile(r"^\s*\d+[.)]\s", re.MULTILINE),
    re.compile(r"^#+\s+\d+(?:\.\d+)*", re.MULTILINE),
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


def unbound_numbers(doc: str, text: str, allow_phrases: Sequence[str]) -> list[Problem]:
    """Return a problem for every number in prose that is neither marked nor a non-result."""
    prose = text
    for pattern in (FENCE, MARKER, COMMENT, INLINE_CODE, URL):
        prose = blank(prose, pattern)
    allowed = [False] * len(prose)
    for pattern in NON_RESULT_PATTERNS:
        for m in pattern.finditer(prose):
            allowed[m.start() : m.end()] = [True] * (m.end() - m.start())
    for phrase in allow_phrases:
        for m in re.finditer(re.escape(phrase), prose):
            allowed[m.start() : m.end()] = [True] * (m.end() - m.start())
    problems: list[Problem] = []
    for m in NUMBER.finditer(prose):
        digits = [i for i in range(m.start(), m.end()) if prose[i].isdigit()]
        if digits and not all(allowed[i] for i in digits):
            problems.append(
                Problem(doc, line_of(prose, m.start()), f"unbound number {m.group(0)!r}")
            )
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
