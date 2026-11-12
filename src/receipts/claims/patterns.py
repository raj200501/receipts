"""Deterministic claim extractors (``extractor = "pattern"``), one rule set per claim type.

The rules come from the phrasing of coding-agent final reports (Claude Code, Codex,
Aider, OpenHands, and small local models through minimal-agent): "All tests pass",
"12/13 tests pass", "I ran `pytest -q`", "Updated `src/config.py` to ...", "bumped
lodash to 4.17.21", "I couldn't get the integration test to run". They aim for precision
first: a phrase that could mean several things yields no claim and is left to the model
extractor.

Each unit (see :mod:`receipts.claims.segment`) is matched on its own, and one unit can
yield several claims. Rules run in a fixed priority order, and a rule can reserve a
region of the unit so that later rules do not read it again:

1. ``tests_added``, ``bug_fixed``, ``feature_implemented``: their descriptions are not
   read again as test, lint, or build claims ("fixed the failing test" admits nothing).
2. ``could_not``: from "could not" to the end of the unit is the description, and
   nothing in it becomes another claim ("I couldn't update `legacy.py`"). The subject
   must be the agent, or the clause must be an admission about the work ("the tests
   could not be run"); descriptions of the code or of the old bug ("tokens cannot be
   reused", "previously the CLI could not parse `--json`") are not admissions.
3. ``task_complete`` and ``ran_command``.
4. Test numbers: a unit that states test counts yields one ``test_count`` claim with
   every number it states and no other test claim, except that a count of failures
   ("39 passed, 3 failed") also yields a negated ``tests_pass``: the count admits the
   failures. A unit that only counts failures ("1 test is still failing") yields only
   the negated ``tests_pass``, because ``test_count`` is a success type.
5. ``tests_pass``, ``lint_clean``, ``typecheck_clean``, ``build_succeeds`` (also from
   check-mark lines such as "- ✅ `ruff check src`" and from "Ran `pytest` and
   `ruff check .`: both pass"), dependency claims, file claims, and last, commands
   cited as evidence for a status claim ("All 12 tests pass (`pytest -q`)").

Statements are skipped when hedged ("should pass", "once the build passes", "I should
have updated `a.py`", "I believe this resolves"), given as advice or instructions ("you
can run `pytest`", the commands under "How to verify"), or dated: a failure the unit
dates ("3 tests failed before my change", "Initially mypy failed") or that a later
clause of the sentence undoes ("`test_x` was failing; it passes now", "failed once, then
passed on retry") is history, not the final state. A negated run of part of a suite ("I
didn't run the integration tests") yields no claim, because the verifier matches generic
runs of any part of the suite and would contradict an honest admission.

Headings and label lines ("## Done", "**Known failures:**") name a section and are read
only for explicit status statements ("## All 42 tests pass", "Status: done"). Unchecked
task boxes ("- [ ] Added pagination") yield no claim, and the items listed under a
section of work not done ("Not done", "Next steps", "TODO") keep only admissions and
status claims. Empty or negative values under a label or section ("Dependencies: none",
"## Bug fixes" then "- N/A") yield no claim.

Claims of one unit with identical (type, params) are kept once (the first). Params
follow what :mod:`receipts.verify` reads: commands as written inside backticks (a
leading ``$`` prompt removed) or a generic phrase that
:func:`receipts.verify.commands.generic_kind` recognizes ("the tests", "the linter");
paths without backticks, quotes, trailing punctuation, ``:line`` suffixes, or test names
after ``::``, and never with a guessed extension ("the README" names no path);
integer test counts; dependency names without version operators, with the version (its
first number) separately.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from receipts.claims.segment import (
    Segmentation,
    Span,
    Unit,
    code_spans,
    mask_markdown,
    segment,
    table_cells,
)
from receipts.claims.types import Claim, ClaimType, ParamValue

_I = re.IGNORECASE
Params = dict[str, ParamValue]


@dataclass(frozen=True)
class PatternHit:
    """One claim that a pattern rule found in a unit.

    Attributes:
        type: The claim type.
        params: Type-specific arguments (see :mod:`receipts.claims.types`).
        negated: True for a claim stated in the negative.
        anchor: ``(start, end)`` of the words that triggered it, relative to the unit.
    """

    type: ClaimType
    params: Mapping[str, ParamValue]
    negated: bool
    anchor: Span

    def key(self) -> tuple[ClaimType, tuple[tuple[str, ParamValue], ...]]:
        """The identity used to deduplicate claims of one unit: type and params."""
        return (self.type, tuple(sorted(self.params.items())))


@dataclass(frozen=True)
class _Candidate:
    hit: PatternHit
    family: str
    blocks: frozenset[str] = frozenset()
    region: Span = (0, 0)


_ALL_FAMILIES = frozenset(
    {
        "tests_added",
        "bug",
        "feature",
        "could_not",
        "complete",
        "command",
        "tests",
        "lint",
        "typecheck",
        "build",
        "dependency",
        "file",
    }
)
_STATUS_FAMILIES = frozenset({"tests", "lint", "typecheck", "build"})
#: Family of a candidate that only reserves a region and is never kept as a claim.
_RESERVE_ONLY = "reserve"


def _words(text: str) -> frozenset[str]:
    """The whitespace-separated words of ``text``, as a set."""
    return frozenset(text.split())


def _overlaps(a: Span, b: Span) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _blank_pipes(text: str, codes: Sequence[Span]) -> str:
    chars = list(text)
    inside = bytearray(len(text))
    for start, end in codes:
        inside[start:end] = b"\x01" * (end - start)
    for k, char in enumerate(text):
        if char == "|" and not inside[k]:
            chars[k] = " "
    return "".join(chars)


class _View:
    """A unit prepared for matching: its text and two masks of the same length.

    ``plain`` has Markdown markup blanked; ``prose`` additionally replaces the content
    of inline code with ``C`` so that prose rules never match inside code. Table rows
    also have their cell pipes blanked.
    """

    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.text = unit.text
        self.codes = code_spans(unit.text)
        plain = mask_markdown(unit.text)
        prose = mask_markdown(unit.text, blank_code=True)
        if unit.kind == "table_row":
            plain = _blank_pipes(plain, self.codes)
            prose = _blank_pipes(prose, self.codes)
        self.plain = plain
        self.prose = prose
        self.context = unit.context.lower()
        self._starts = {start: (start, end) for start, end in self.codes}

    def code_at(self, pos: int) -> Span | None:
        """The inline code span that starts at ``pos``, if any."""
        return self._starts.get(pos)

    def content(self, span: Span) -> str:
        """The content of an inline code span, without its backticks, stripped."""
        start, end = span
        while start < end and self.text[start] == "`":
            start += 1
        while end > start and self.text[end - 1] == "`":
            end -= 1
        return self.text[start:end].strip()


_PATH_PREFIX = re.compile(r"^\W*`C+`\s*(?::|-{1,2}|→|->)\s*$")


def _after_path_prefix(v: _View, pos: int) -> bool:
    """True when ``pos`` follows only a path label: "`api/handlers.py`: add ..." (the
    imperative change list of a commit-style summary, which describes work done)."""
    if not _PATH_PREFIX.match(v.prose[:pos]) or not v.codes:
        return False
    return path_param(v.content(v.codes[0])) is not None


def _skip_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _clip(text: str, start: int, end: int) -> Span | None:
    """``(start, end)`` trimmed of whitespace and trailing punctuation, or None if empty."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in ".,;:!"):
        end -= 1
    if end - start < 2 or not any(char.isalnum() for char in text[start:end]):
        return None
    return (start, end)


# --- numbers -------------------------------------------------------------------------

_WORD_NUMBERS: Mapping[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}
_NUM = r"(?:\d+|" + "|".join(_WORD_NUMBERS) + r")"


def _number(token: str) -> int | None:
    word = token.strip().lower()
    if word.isdigit():
        return int(word)
    return _WORD_NUMBERS.get(word)


# --- paths ---------------------------------------------------------------------------

_EXTENSIONS = _words(
    "py pyi pyx pxd ipynb ts tsx js jsx mjs cjs mts cts json jsonc json5 toml yaml yml"
    " md mdx markdown rst txt cfg ini conf lock sh bash zsh fish ps1 bat cmd html htm"
    " css scss sass less sql csv tsv xml j2 jinja jinja2 tpl tmpl go rs java kt kts"
    " swift rb php c h cc cpp cxx hpp hh cs scala clj dart lua pl ex exs erl elm vue"
    " svelte astro graphql gql proto tf hcl gradle properties svg snap patch diff in"
    " example sample"
)
_DOTFILE_EXTENSIONS = _words(
    "env gitignore gitattributes dockerignore editorconfig npmrc nvmrc prettierrc"
    " eslintrc babelrc flake8 coveragerc pylintrc"
)
#: Well-known file names that have no extension. They are kept exactly as written: the
#: verifier matches paths exactly, so "makefile" is not turned into "Makefile".
_SPECIAL_FILES = frozenset(
    {
        "makefile",
        "gnumakefile",
        "dockerfile",
        "containerfile",
        "procfile",
        "pipfile",
        "gemfile",
        "justfile",
        "license",
        "licence",
        "codeowners",
    }
)
_NOT_PATHS = frozenset(
    {
        "node.js",
        "vue.js",
        "next.js",
        "nuxt.js",
        "express.js",
        "react.js",
        "three.js",
        "d3.js",
        "chart.js",
        "ember.js",
        "angular.js",
        "backbone.js",
        "alpine.js",
        "solid.js",
    }
)
_LINE_SUFFIX = re.compile(r"(?::\d+(?:[:-]\d+)?|#L\d+(?:-L?\d+)?)$")
_PATH_REJECT = frozenset("*?{}$<>|,;=~^()[] \t\n")


def path_param(raw: str) -> str | None:
    """Normalize a path as a report writes it, or return None if it is not a file path.

    Backticks, quotes, brackets, trailing punctuation, a ``:line`` or ``#L`` suffix, and
    a test name after ``::`` are removed. A file path has a known extension
    (``app.py``, ``docs/usage.md``), is a dotfile (``.gitignore``), or is a well-known
    name that has no extension (``Makefile``, ``Dockerfile``, ``LICENSE``), kept as
    written. No extension is ever guessed: "README", "CHANGELOG" or "pyproject" without
    one could be ``README.md`` or ``README.rst``, so they are not paths. URLs, flags,
    directories, globs, npm scopes, and library names such as "Node.js" are not paths.
    """
    token = raw.strip().strip("`'\"").split("::", 1)[0]
    token = _LINE_SUFFIX.sub("", token)
    token = token.rstrip(".,;:!?)]}>'\"").lstrip("([{<'\"")
    token = _LINE_SUFFIX.sub("", token)
    if not token or "://" in token or token.startswith(("-", "@", "www.")):
        return None
    if token.endswith(("/", "\\")) or any(char in _PATH_REJECT for char in token):
        return None
    if token.lower() in _NOT_PATHS:
        return None
    last = token.replace("\\", "/").rsplit("/", 1)[-1]
    if last.lower() in _SPECIAL_FILES:
        return token
    stem, dot, ext = last.rpartition(".")
    ext = ext.lower()
    if not dot:
        return None
    if ext in _DOTFILE_EXTENSIONS:
        return token if stem == "" else None
    if ext not in _EXTENSIONS:
        return None
    if ext in ("example", "sample") and not stem.startswith("."):
        return token if "." in stem else None
    if not re.search(r"[A-Za-z0-9_]", stem):
        return None
    return token


def _looks_like_test_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    if any(part in ("tests", "test", "__tests__", "spec", "specs") for part in parts[:-1]):
        return True
    return bool(re.match(r"^(?:test_.+\.py|.+_test\.py|.+\.(?:test|spec)\.[cm]?[jt]sx?)$", name))


@dataclass(frozen=True)
class _PathRef:
    start: int
    end: int
    value: str
    code: bool
    node: bool = False  # written as a test node id, "tests/test_x.py::test_y"


_BARE_PATH = re.compile(
    r"(?<![\w@/.\-`~$])(?:\.{1,2}/)?(?:[\w@.\-]+/)*[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z0-9]+"
    r"(?:::[\w\[\]\-]+)?(?::\d+(?:[:-]\d+)?)?(?![\w/\-(]|\.\w)"
)
_DOTFILE = re.compile(r"(?<![\w@/.\-`~$])(?:[\w@.\-]+/)*\.[A-Za-z][\w\-]*(?![\w/\-(]|\.\w)")
_SPECIAL_RE = re.compile(
    r"(?<![\w@/.\-`~$])(?:[\w@.\-]+/)*(?:Makefile|makefile|Dockerfile|dockerfile|LICENSE"
    r"|Procfile|Pipfile|Justfile|justfile)(?![\w/\-(]|\.\w)"
)


def _paths(v: _View) -> list[_PathRef]:
    refs: list[_PathRef] = []
    for span in v.codes:
        content = v.content(span)
        value = path_param(content)
        if value is not None:
            refs.append(_PathRef(span[0], span[1], value, True, "::" in content))
    for regex in (_BARE_PATH, _DOTFILE, _SPECIAL_RE):
        for match in regex.finditer(v.prose):
            if any(r.start <= match.start() < r.end for r in refs):
                continue
            raw = v.text[match.start() : match.end()]
            value = path_param(raw)
            if value is not None:
                refs.append(_PathRef(match.start(), match.end(), value, False, "::" in raw))
    return sorted(refs, key=lambda r: r.start)


# --- commands ------------------------------------------------------------------------

_KNOWN_PROGRAMS = _words(
    "pytest py.test python python3 pip pip3 pipx uv uvx poetry pipenv pdm hatch tox nox"
    " ruff black isort flake8 pylint mypy pyright basedpyright pytype pyre coverage"
    " bandit pre-commit npm npx yarn pnpm bun bunx node deno tsc tsx ts-node eslint"
    " prettier jest vitest mocha ava biome oxlint stylelint vite next webpack rollup"
    " esbuild make cargo go git docker docker-compose bash sh zsh curl wget ls cat grep"
    " rg sed awk echo cd find head tail wc diff sqlite3 psql mysql redis-cli java javac"
    " mvn gradle dotnet rustc gcc cmake ctest gh sort jq timeout xargs uvicorn gunicorn"
    " flask django-admin alembic playwright cypress nodemon kubectl terraform helm"
    " http nc tar unzip chmod mkdir rm cp mv touch ln pwd which export source unittest"
    " nose2 behave just pydocstyle"
)
_WRAPPERS = frozenset({"sudo", "env", "time", "nohup", "exec", "command"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PROMPT = re.compile(r"^(?:\$|>|%|#)\s+")


def command_param(raw: str) -> str | None:
    """The command in an inline code span as a ``ran_command`` param, or None.

    A leading shell prompt (``$ ``) is removed. The span is a command when its program
    (after environment assignments and wrappers such as ``sudo``) is a known tool
    (``pytest``, ``npm``, ``ruff``, ``make``, ...), a ``python`` executable, a ``./``
    script, or a ``.sh`` file. minimal-agent's ``run_tests`` tool becomes the generic
    "the tests".
    """
    command = _PROMPT.sub("", raw.strip()).strip()
    if command in ("run_tests", "run_tests()"):
        return "the tests"
    tokens = command.split()
    index = 0
    while index < len(tokens) and (
        _ENV_ASSIGNMENT.match(tokens[index]) or tokens[index] in _WRAPPERS
    ):
        index += 1
    if index >= len(tokens):
        return None
    program = tokens[index]
    base = program.rsplit("/", 1)[-1]
    if program.startswith("./") or base.endswith(".sh"):
        return command
    if base.lower() in _KNOWN_PROGRAMS or re.match(r"^python3(?:\.\d+)?$", base):
        return command
    return None


_RUNNER_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("uv", "run"),
    ("poetry", "run"),
    ("pipenv", "run"),
    ("pdm", "run"),
    ("pnpm", "exec"),
    ("npx",),
    ("bunx",),
    ("python", "-m"),
    ("python3", "-m"),
)
_PACKAGE_MANAGERS = frozenset({"npm", "yarn", "pnpm", "bun"})
_TEST_PROGRAMS = frozenset(
    {"pytest", "py.test", "jest", "vitest", "mocha", "ava", "unittest", "nose2", "tox", "nox"}
)
_LINT_PROGRAMS = frozenset(
    {"ruff", "flake8", "pylint", "eslint", "pycodestyle", "pyflakes", "biome", "oxlint"}
)
_TYPE_PROGRAMS = frozenset({"mypy", "pyright", "basedpyright", "pytype", "pyre", "tsc", "vue-tsc"})
_BUILD_TOOLS = frozenset(
    {"make", "uv", "cargo", "go", "hatch", "poetry", "vite", "next", "pdm", "dotnet"}
)


def _segments(command: str) -> list[list[str]]:
    out: list[list[str]] = []
    for part in re.split(r"&&|\|\||;|\|", command.lower().replace("`", "")):
        tokens = part.split()
        changed = True
        while tokens and changed:
            changed = False
            while tokens and (_ENV_ASSIGNMENT.match(tokens[0]) or tokens[0] in _WRAPPERS):
                tokens = tokens[1:]
                changed = True
            if tokens:
                tokens[0] = tokens[0].rsplit("/", 1)[-1]
            for prefix in _RUNNER_PREFIXES:
                if tuple(tokens[: len(prefix)]) == prefix and len(tokens) > len(prefix):
                    tokens = tokens[len(prefix) :]
                    while tokens and tokens[0].startswith("-"):
                        tokens = tokens[1:]
                    changed = True
                    break
        if tokens and tokens[0] != "cd":
            out.append(tokens)
    return out


_VALUE_FLAGS = frozenset({"--filter", "--dir", "--prefix", "--workspace", "-c", "-w"})


def _skip_flags(tokens: list[str]) -> list[str]:
    """Package-manager arguments after the leading flags (and the values they take)."""
    rest = list(tokens)
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if "=" not in flag and flag in _VALUE_FLAGS and rest:
            rest.pop(0)
    return rest


def command_kinds(command: str) -> frozenset[str]:
    """Kinds of check a command runs: any of "test", "lint", "typecheck", "build"."""
    kinds: set[str] = set()
    for tokens in _segments(command):
        program, rest = tokens[0], tokens[1:]
        if program in _PACKAGE_MANAGERS:
            rest = _skip_flags(rest)
        first = rest[0] if rest else ""
        if first == "run" and len(rest) > 1 and program in _PACKAGE_MANAGERS:
            first = rest[1]
        if (
            program in _TEST_PROGRAMS
            or program == "run_tests"
            or (program in _PACKAGE_MANAGERS and first in ("test", "t"))
            or (program in ("go", "cargo", "dotnet") and first == "test")
            or (program == "make" and "test" in rest)
        ):
            kinds.add("test")
        if (
            (
                program in _LINT_PROGRAMS
                and not (program == "ruff" and first == "format" and "--check" not in rest)
            )
            or (program in _PACKAGE_MANAGERS and first == "lint")
            or (program == "make" and "lint" in rest)
        ):
            kinds.add("lint")
        if (
            program in _TYPE_PROGRAMS
            or (program in _PACKAGE_MANAGERS and first in ("typecheck", "type-check"))
            or (program == "make" and "typecheck" in rest)
        ):
            kinds.add("typecheck")
        if (
            program in ("build", "webpack")
            or (program in _PACKAGE_MANAGERS and first == "build")
            or (program in _BUILD_TOOLS and first == "build")
        ):
            kinds.add("build")
    return frozenset(kinds)


_GENERIC_TEST_QUALIFIERS = frozenset(
    {
        "full",
        "whole",
        "entire",
        "complete",
        "existing",
        "new",
        "unit",
        "integration",
        "relevant",
        "python",
        "typescript",
        "javascript",
        "js",
        "ts",
        "project",
    }
)
_GENERIC_DETERMINERS: Mapping[str, str] = {
    "the": "the",
    "all the": "all the",
    "all of the": "all the",
    "all": "all",
    "my": "my",
    "our": "our",
}
_PROGRAM_QUALIFIERS = frozenset(
    _TEST_PROGRAMS | _LINT_PROGRAMS | _TYPE_PROGRAMS | {"npm", "yarn", "pnpm"}
)
_GENERIC = re.compile(
    r"(?P<det>the|all\s+of\s+the|all\s+the|all|my|our|a\s+full|a\s+quick|a|an|some|both|every"
    r"|another)?\s*"
    r"(?P<quals>(?:(?!(?:through|against|on|with|in|for|of|the|a|an|to|from|and|or|then"
    r"|again|locally|now|too|also|as|before|after|once|twice|it|them|this|that|is|are|was"
    r"|were|which|but|so)\b)[a-z0-9][\w-]*\s+){0,3}?)"
    r"(?P<noun>test\s+suites?|test-suites?|testsuites?|tests|test|specs|spec|suites?"
    r"|linters?|linting|lint\s+checks?|lint|style\s+checks?|type\s*checkers?|type[- ]?checks?"
    r"|type\s*checking|typecheck(?:s|ing)?|builds?|build\s+step|build\s+script)\b"
    r"(?!\s*(?:fixtures?|files?|data|helpers?|utils?|names?|ids?|output|results?|dependenc\w*"
    r"|config\w*|cases?|runner|harness|framework|setup|command|script|matrix|workflow|job"
    r"|step|logs?|coverage|module|directory|folder|dir|for|that|which|i|we)\b)",
    _I,
)
_GENERIC_PAIR = re.compile(
    r"(?P<det>the|all\s+the|all|both\s+the|both)?\s*(?P<q1>[a-z][\w-]*)\s*(?:,|and|&|/|plus)\s*"
    r"(?P<q2>[a-z][\w-]*)\s+(?P<noun>tests|test\s+suites|specs|suites)\b",
    _I,
)


def _canonical_generic(det: str | None, quals: str, noun: str) -> str:
    """A generic command phrase in the form receipts.verify.commands.generic_kind accepts."""
    words = [w.lower() for w in quals.split()]
    for word in words:
        if word in _PROGRAM_QUALIFIERS:
            return word
    noun_text = " ".join(noun.lower().split())
    det_text = " ".join((det or "").lower().split())
    if re.match(r"^(?:test\s*suites?|test-suites?|testsuites?|tests?|specs?|suites?)$", noun_text):
        noun_text = re.sub(r"(suite)s$", r"\1", noun_text)
        determiner = _GENERIC_DETERMINERS.get(det_text, "the" if det_text else "")
        kept = [w for w in words if w in _GENERIC_TEST_QUALIFIERS]
        return " ".join(part for part in (determiner, *kept, noun_text) if part)
    determiner = "the" if det_text else ""
    if noun_text.startswith(("type", "typecheck")):
        noun_text = noun_text.replace("typechecker", "type checker")
    if noun_text.startswith("build"):
        noun_text = {"builds": "builds"}.get(noun_text, noun_text)
    return " ".join(part for part in (determiner, noun_text) if part)


def _generic_phrase(match: re.Match[str]) -> tuple[str, bool]:
    """The canonical phrase of a ``_GENERIC`` match, and whether it names part of a suite."""
    det, quals = match.group("det"), match.group("quals")
    phrase = _canonical_generic(det, quals, match.group("noun"))
    if phrase in _PROGRAM_QUALIFIERS:
        return phrase, False  # "the pytest tests" names the program
    first = (det or "").lower().split()[:1]
    return phrase, bool(quals.strip()) or first in (["a"], ["some"])


def generic_command(phrase: str) -> tuple[str, bool] | None:
    """A generic command phrase ("the full test suite", "the linter") in canonical form.

    Returns the phrase as :func:`receipts.verify.commands.generic_kind` reads it
    (unknown qualifiers dropped: "the slow tests" becomes "the tests"), and whether it
    names only part of the suite ("the unit tests", "a quick test run"). Returns None
    when ``phrase`` is not a generic phrase, or is a count ("42 tests").
    """
    text = " ".join(mask_markdown(phrase).replace("`", " ").split()).rstrip(".")
    if command_param(text) is not None:
        return None  # "npm run build" is a command, not a phrase like "the build"
    match = _GENERIC.fullmatch(text)
    if match is None or not match.group("noun"):
        return None
    if not match.group("det") and re.search(r"\d", match.group("quals")):
        return None
    return _generic_phrase(match)


_BARE_PROGRAMS = (
    r"(?:pytest|py\.test|mypy|ruff|black|isort|flake8|pylint|pyright|tox|nox|coverage|eslint"
    r"|prettier|tsc|jest|vitest|mocha|npm|npx|yarn|pnpm|bun|make|cargo|go|uv|poetry|pdm|hatch"
    r"|python3?(?:\.\d+)?|node|deno|pre-commit|unittest|pip3?)"
)
_BARE_ARG = (
    r"(?:-{1,2}[A-Za-z0-9][\w=.,:/\-]*|(?:test|tests|run|ci|install|build|lint|check|format"
    r"|exec|typecheck|type-check|vet|fmt|clippy|pytest|mypy|ruff|tsc|jest|vitest|eslint"
    r"|unittest|tox)\b|\.{1,2}/[\w./\-]*|[\w\-]*[/.][\w./\-]*\w|\.(?=\s|$|[,;)]))"
)
_BARE_COMMAND = re.compile(r"\b" + _BARE_PROGRAMS + r"\b(?:\s+" + _BARE_ARG + r")*", _I)
_ITEM_SEPARATOR = re.compile(
    r"\s*(?:,\s*(?:and\s+|then\s+|plus\s+)?|\s+and\s+(?:then\s+|also\s+)?|\s*&\s*|\s+plus\s+"
    r"|\s+as\s+well\s+as\s+|\s+followed\s+by\s+|\s+then\s+|\s+/\s+)\s*",
    _I,
)
_OBJECT_LEAD = re.compile(
    r"\s*(?:(?:the\s+following|both|all\s+of|each\s+of)\s*:?\s*"
    r"|(?:it|them|everything|this|that|these|the\s+code|the\s+changes|my\s+changes"
    r"|the\s+fix|the\s+patch|the\s+project|the\s+repo)\s+(?:through|with|using|via|against)\s+"
    r"|:\s*)?",
    _I,
)


_WITH_CODE = re.compile(
    r"\s+(?:(?:again|locally|once\s+more|twice)\s+)?(?:with|using|via)\s+(?=`)", _I
)


@dataclass(frozen=True)
class _CommandItem:
    start: int
    end: int
    command: str
    subset: bool = False  # a generic phrase naming part of the suite ("the unit tests")


def _command_items(v: _View, pos: int) -> list[_CommandItem]:
    """Commands listed at ``pos``: code spans, generic phrases, or bare tool names."""
    lead = _OBJECT_LEAD.match(v.prose, pos)
    pos = _skip_space(v.prose, lead.end() if lead else pos)
    items: list[_CommandItem] = []
    while pos < len(v.text):
        span = v.code_at(pos)
        if span is not None:
            command = command_param(v.content(span))
            if command is None:
                break
            items.append(_CommandItem(span[0], span[1], command))
            pos = span[1]
        else:
            pair = _GENERIC_PAIR.match(v.prose, pos)
            generic = _GENERIC.match(v.prose, pos)
            bare = _BARE_COMMAND.match(v.plain, pos)
            if pair is not None:
                for qual in (pair.group("q1"), pair.group("q2")):
                    phrase = _canonical_generic(pair.group("det"), qual, pair.group("noun"))
                    items.append(_CommandItem(pair.start(), pair.end(), phrase, True))
                pos = pair.end()
            elif generic is not None and generic.group("noun"):
                if not generic.group("det") and re.search(r"\d", generic.group("quals")):
                    break  # "ran 42 tests": a count summary, not a command claim
                phrase, subset = _generic_phrase(generic)
                items.append(_CommandItem(generic.start(), generic.end(), phrase, subset))
                pos = generic.end()
                cited = _WITH_CODE.match(v.prose, pos)
                code = v.code_at(cited.end()) if cited is not None else None
                command = command_param(v.content(code)) if code is not None else None
                if code is not None and command is not None:
                    # "ran the full test suite with `npm test`": the command itself too
                    items.append(_CommandItem(code[0], code[1], command))
                    pos = code[1]
            elif bare is not None:
                text = v.text[bare.start() : bare.end()].strip()
                items.append(_CommandItem(bare.start(), bare.end(), text))
                pos = bare.end()
            else:
                break
        separator = _ITEM_SEPARATOR.match(v.prose, pos)
        if separator is None or separator.end() == pos:
            break
        pos = separator.end()
    return items


# --- shared vocabulary ---------------------------------------------------------------

_NEGATOR = (
    r"(?:did\s*n[o']?t|did\s+not|do\s*n[o']?t|do\s+not|does\s*n[o']?t|does\s+not"
    r"|have\s*n[o']?t|have\s+not|has\s*n[o']?t|has\s+not|had\s*n[o']?t|had\s+not|never"
    r"|not\s+yet)"
)
_DESCRIPTION_END = re.compile(
    r"\s+\((?!\))|\s*;\s|\s*:\s|\s+-{1,2}\s|\s+→\s"
    r"|,\s+(?:which|so|and|but|because|since|as|making|meaning|now|while|then|plus|after"
    r"|before|so\s+that|otherwise)\b"
    r"|\s+(?:so\s+that|so|because|since|which|making|meaning|and\s+now|now\s+that|while"
    r"|whereas|but)\b"
    r"|(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)\.\s+(?=\S)"  # "... in dates.py. ran pytest"
    r"|\s*[.!]+\s*$|$",
    _I,
)


def _description(v: _View, start: int, end: int | None = None) -> tuple[str, Span] | None:
    """Verbatim text from ``start`` up to the first clause terminator, trimmed.

    In a table row the description never runs past the end of its cell.
    """
    limit = len(v.text) if end is None else end
    if v.unit.kind == "table_row":
        for cell_start, cell_end in table_cells(v.text):
            if cell_start <= start <= cell_end:
                limit = min(limit, cell_end)
                break
    match = _DESCRIPTION_END.search(v.prose, start, limit)
    cut = limit if match is None else match.start()
    span = _clip(v.text, start, cut)
    if span is None:
        return None
    return v.text[span[0] : span[1]], span


#: A label value or list item that says there is nothing: "None", "N/A", "no new
#: dependencies", "not started", "TBD", "-".
_NONE_VALUE = re.compile(
    r"\s*\(?\s*(?:(?:none|nothing|nil|n/?a|tbd|todo|pending|deferred|unchanged|skipped)\b"
    r"|no\b(?!\s+longer)|not\b|-+\s*$|\)|$)",
    _I,
)
#: A status after a section item saying it was not done: "Pagination (not implemented;
#: the API has no cursor)", "Retries - deferred".
_NOT_DONE_STATUS = re.compile(
    r"\s*(?:\(|:|-{1,2}|->|=>)?\s*(?:not\s+(?:yet\s+)?(?:implemented|done|started|fixed|finished"
    r"|completed?|addressed|supported|included|attempted)|deferred|skipped|blocked|pending|todo"
    r"|tbd|partial(?:ly\s+(?:implemented|done))?|won'?t\s+(?:fix|do)|out\s+of\s+scope"
    r"|left\s+(?:out|for))\b",
    _I,
)


def _section_item(v: _View, start: int) -> tuple[tuple[str, Span], bool] | None:
    """The description of a labeled item and whether its status says it was not done.

    Used for items under a "Bug fixes" or "New features" section and for label values
    ("Fixes: ..."). An empty or negative value ("None", "N/A", "not started") gives None.
    """
    if _NONE_VALUE.match(v.prose, start):
        return None
    desc = _description(v, start)
    if desc is None:
        return None
    return desc, bool(_NOT_DONE_STATUS.match(v.prose, desc[1][1]))


#: Opening filler words ("So,", "Overall:", "Unfortunately"). Each filler ends in one
#: unambiguous separator (punctuation with optional spaces, or spaces alone), so a run of
#: fillers followed by several spaces matches in one way only and cannot backtrack
#: exponentially (``\s*[,:]?\s+`` could split the same spaces in many ways).
_SEP = r"(?:\s*[,:]\s*|\s+)"
_LEAD_FILLERS = (
    r"^[^\w`]*(?:(?:so|and|also|now|finally|thus|therefore|overall|then|additionally"
    r"|as\s+a\s+result"
    r"|in\s+(?:short|summary)|note|however|unfortunately|good\s+news)" + _SEP + r"){0,8}"
)

_LEAD = re.compile(_LEAD_FILLERS, _I)


# --- rules ---------------------------------------------------------------------------

Rule = Callable[[_View], list[_Candidate]]

_TESTS_ADDED = re.compile(
    r"\b(?P<verb>added|adds|wrote|writes|written|created|creates|introduced|included"
    r"|implemented|extended|expanded|authored|put\s+in)\s+"
    r"(?P<obj>(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an|some|several"
    r"|new|more|extra|additional|a\s+few|a\s+couple\s+of|the|missing|regression|unit"
    r"|integration|e2e|end-to-end|smoke|parametri[sz]ed|parameteri[sz]ed|property-based"
    r"|focused|targeted|edge-case|edge\s+case|failing|basic|thorough|comprehensive|dedicated"
    r"|separate|corresponding|matching|its|their|own|simple|small|quick|pytest|jest|vitest)\s+){0,6}"
    r"(?:test\s+suite|test\s+cases?|tests?|specs?|test\s+coverage|coverage|cases))\b"
    r"(?!\s+(?:dependenc\w*|fixtures?|helpers?|utils?|utilities|data|files?|config\w*|setup"
    r"|runner|commands?|scripts?|harness|framework|requirements?|extras?|groups?|matrix"
    r"|workflows?|jobs?|steps?|output|logs?|names?|ids?|mode|environment|env|database|db"
    r"|server|client|doubles?|stubs?|mocks?|reporting|reports?|thresholds?|tools?|tooling"
    r"|plugins?|markers?|settings|dependency)\b)",
    _I,
)
_TESTS_ADDED_NEGATED = re.compile(
    r"\b" + _NEGATOR + r"\s+(?:yet\s+)?(?:add(?:ed)?|write|written|wrote|create[d]?)\s+"
    r"(?:any\s+)?(?:new\s+)?(?:tests?|test\s+cases?|specs?)\b"
    r"|\bno\s+(?:new\s+)?tests?\s+(?:were|was|have\s+been|has\s+been)\s+(?:added|written)\b"
    r"|\b(?:(?:new|regression|unit|more)\s+)?(?:tests?|test\s+cases?|specs?)\s+(?:were|was|have"
    r"|has)\s*(?:n[o']?t|not)\s+(?:yet\s+)?(?:been\s+)?(?:added|written|created)\b",
    _I,
)
#: "New tests for the flag" opening an item, optionally after a path: "`t.py`: new tests".
_TESTS_NEW = re.compile(
    r"^\W*(?:`C+`(?:\s*(?::|-{1,2}|→|->)\s*|\s+))?(?P<noun>(?:(?:\d+|one|two|three|four"
    r"|five|six|seven|eight|nine|ten|a\s+few|several|some)\s+)?(?:new|additional|extra|more)\s+"
    r"(?:(?:unit|regression|integration|e2e|edge-case)\s+){0,6}(?:tests?|test\s+cases?|specs?))\b"
    r"(?!\s+(?:were|was|are|is|will|should|would|could|might|need\w*|requir\w*|tbd|pending"
    r"|to\s+be\b|to\s+come|to\s+follow|planned|todo|later|welcome|wanted|missing|pass\w*"
    r"|fail\w*|cover\w*|run|ran)\b)",
    _I,
)
#: A unit opening with a "Tests:" label, as in "**Tests**: added a case for empty input".
_TESTS_LABEL = re.compile(r"^\W*(?:tests?|testing|test\s+changes)\s*:\s*", _I)
#: A create verb whose object is inline code naming a test ("added `tests/t.py::test_x`").
_ADDED_TEST_CODE = re.compile(
    r"\b(?:added|adds|wrote|writes|created|introduced)\s+(?:(?:a|an|the|new|regression|unit"
    r"|parametri[sz]ed)\s+){0,6}(?:(?:tests?|test\s+cases?)\s+)?(?=`)",
    _I,
)
_ADD_TEST_CODE = re.compile(
    r"\badd\s+(?:(?:a|an|the|new|regression|unit|parametri[sz]ed)\s+){0,6}"
    r"(?:(?:tests?|test\s+cases?)\s+)?(?=`)",
    _I,
)
_TEST_CODE_NAME = re.compile(r"^(?:[\w/.\-]+\.[A-Za-z]+::)?(?:\w+::)*test\w*(?:\[[^\]]*\])?$")
_TESTS_ADDED_PASSIVE = re.compile(
    r"\b(?:(?:new|regression|unit|more)\s+){0,6}(?:tests?|test\s+cases?|specs?)\s+"
    r"(?:were|was|have\s+been|has\s+been)\s+(?:added|written|created)\b",
    _I,
)
_TESTS_ADDED_LABEL = re.compile(r"^\W*(?:new\s+tests?|tests?\s+added|added\s+tests?)\s*:\s*", _I)
_TESTS_WITH = re.compile(
    r"\bwith\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|a\s+few|several|some"
    r"|new)\s+(?:new\s+)?(?:unit\s+|regression\s+)?(?:tests?|test\s+cases?)\b",
    _I,
)
_TESTS_HAS = re.compile(
    r"\s+(?:now\s+)?(?:has|contains|includes|covers)\s+(?:\d+\s+)?(?:new\s+)?(?:tests?|cases)\b",
    _I,
)
_TARGET_CUE = re.compile(
    r"\s*(?:for|covering|that\s+covers?|to\s+cover|around|exercising|checking|verifying|testing"
    r"|against)\s+",
    _I,
)
_CREATE_WRITE = re.compile(r"\b(?:created|added|wrote|introduced)\b", _I)


def _tests_target(v: _View, pos: int) -> tuple[str, Span] | None:
    cue = _TARGET_CUE.search(v.prose, pos)
    if cue is None:
        return None
    stop = _DESCRIPTION_END.search(v.prose, pos, cue.start())
    if stop is not None and stop.start() < cue.start():
        return None
    end = len(v.text)
    location = re.compile(r"\s+(?:in|under|at|inside|to)\s+(?=`|\S+\.\w)", _I).search(
        v.prose, cue.end()
    )
    if location is not None:
        end = location.start()
    return _description(v, cue.end(), end)


def _tests_path(v: _View, after: int) -> str | None:
    for ref in _paths(v):
        if ref.start >= after and _looks_like_test_path(ref.value):
            return ref.value
    return None


def _tests_added(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []
    blocks = frozenset({"tests", "feature", "bug"})
    for match in _TESTS_ADDED_NEGATED.finditer(v.prose):
        hit = PatternHit(ClaimType.TESTS_ADDED, {}, True, match.span())
        out.append(_Candidate(hit, "tests_added", blocks, match.span()))
    if out:
        return out
    found: list[tuple[int, int]] = [m.span() for m in _TESTS_ADDED.finditer(v.prose)]
    found += [m.span() for m in _TESTS_ADDED_PASSIVE.finditer(v.prose)]
    label = _TESTS_ADDED_LABEL.match(v.prose)
    if label is not None:
        if _NONE_VALUE.match(v.prose, label.end()):  # "New tests: none (docs only)"
            hit = PatternHit(ClaimType.TESTS_ADDED, {}, True, label.span())
            return [_Candidate(hit, "tests_added", blocks, (0, len(v.text)))]
        found.append(label.span())
    if _CREATE_WRITE.search(v.prose):
        found += [m.span() for m in _TESTS_WITH.finditer(v.prose)]
    new = _TESTS_NEW.match(v.prose)
    if new is not None:
        found.append(new.span("noun"))
    tests_label = _TESTS_LABEL.match(v.prose)
    if tests_label is not None:
        verb = _CREATE_WRITE.match(v.prose, tests_label.end())
        if verb is not None:
            found.append((tests_label.start(), verb.end()))
    for match in _ADDED_TEST_CODE.finditer(v.prose):
        span = v.code_at(match.end())
        if span is not None and _TEST_CODE_NAME.match(v.content(span)):
            found.append((match.start(), span[1]))
    for match in _ADD_TEST_CODE.finditer(v.prose):
        span = v.code_at(match.end())
        if span is None or not _after_path_prefix(v, match.start()):
            continue
        if _TEST_CODE_NAME.match(v.content(span)):
            found.append((match.start(), span[1]))
    refs = _paths(v)
    for ref in refs:
        has = _TESTS_HAS.match(v.prose, ref.end)
        if has is not None and _looks_like_test_path(ref.value):
            found.append((ref.start, has.end()))
    for start, end in sorted(found)[:1]:
        params: Params = {}
        path = _tests_path(v, start)
        if (
            path is None
            and refs
            and refs[0].end <= start
            and not re.search(r"[A-Za-z0-9]", v.prose[: refs[0].start])
            and _looks_like_test_path(refs[0].value)
        ):
            path = refs[0].value  # "`tests/test_app.py`: new tests for the flag"
        if path is not None:
            params["path"] = path
        target = _tests_target(v, end)
        if target is not None and (path is None or path_param(target[0]) != path):
            params["target"] = target[0]
        region = (start, target[1][1] if target else end)
        hit = PatternHit(ClaimType.TESTS_ADDED, params, False, (start, end))
        out.append(_Candidate(hit, "tests_added", blocks, region))
    return out


_BUG_VERB = re.compile(
    r"(?P<neg>\b(?:did\s*n[o']?t|did\s+not|have\s*n[o']?t|have\s+not|has\s*n[o']?t|has\s+not"
    r"|had\s+not|never|not\s+yet)\s+(?:(?:actually|fully|yet|completely|properly)\s+)?)?"
    r"\b(?P<verb>fixed|fixes|resolved|resolves|corrected|corrects|patched|repaired|repairs"
    r"|fix|resolve|correct|patch|repair)\b(?:\s+up\b)?",
    _I,
)
_BUG_BASE_FORMS = frozenset({"fix", "resolve", "correct", "patch", "repair"})
_BUG_GERUND = re.compile(
    r"\b(?:after|by|via|from|once|while|upon)\s+(?:fixing|resolving|correcting|patching"
    r"|repairing)\b",
    _I,
)
_FIXED_ADJECTIVE_BEFORE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|get|got|gets|a|an|the|with|using|uses|use|of|stay"
    r"|stays|remain|remains|keep|keeps)\s*$",
    _I,
)
_FIXED_ADJECTIVE_AFTER = re.compile(
    r"\s*(?:-|(?:seed|width|point|size|version|set|number|value|timestamp|clock|order|string"
    r"|list|price|rate|delay|interval|offset|length|format|amount|cost|time|date|port|window"
    r"|position|layout|header|height|font|key|fee|term|at|to|in\s+place)\b)",
    _I,
)
_BUG_LABEL = re.compile(r"^\W*(?:bug\s*fix(?:es)?|fix(?:es|ed)?|resolved)\s*:\s*(?=\S)", _I)
_BUG_CONTEXT = re.compile(
    r"^(?:bug\s*fix(?:es)?|fix(?:es|ed)?|bugs?\s+fixed|resolved(?:\s+issues)?|fixed\s+issues)$",
    _I,
)
_BUG_NOUNS = re.compile(
    r"\b(?:bug|issue|crash|error|exception|problem|regression|off-by-one|race|leak|failure|typo"
    r"|edge\s+case|mismatch|overflow|underflow|deadlock|hang|defect|glitch|rounding|drift"
    r"|corruption|it|this|that|test|behaviou?r)\b|#\d+",
    _I,
)
_BUG_PASSIVE = re.compile(
    _LEAD_FILLERS + r"(?P<subj>[^;]{2,120}?)\s+(?:is|are|was|were|has\s+been|have\s+been"
    r"|is\s+now|are\s+now|now|got|gets)\s+(?:(?:now|also|fully|properly|finally|completely"
    r"|definitely)\s+){0,3}(?:fixed|resolved|corrected|patched)\b"
    r"(?!\s*-|\s+(?:at|to|width|size|point|seed|in\s+place)\b)",
    _I,
)
_BUG_PASSIVE_NEGATED = re.compile(
    _LEAD_FILLERS + r"(?P<subj>[^;]{2,120}?)\s+(?:(?:is|are|was|were|has|have)\s*(?:n[o']?t|not)"
    r"\s+(?:(?:yet|been|fully|actually|completely)\s+){0,3}(?:fixed|resolved)"
    r"|(?:is|are)\s+still\s+(?:broken|present|there|happening|reproducible))\b",
    _I,
)
_BUG_NO_LONGER = re.compile(
    _LEAD_FILLERS + r"(?P<subj>[^;]{2,120}?)\s+no\s+longer\s+(?:crash(?:es)?|fails?|errors?"
    r"|raises?|throws?|drops?|loses?|hangs?|breaks?|returns?|produces?|miscounts?"
    r"|double[- ]counts?|skips?|leaks?|overflows?|corrupts?|misses?|ignores?|truncates?"
    r"|duplicates?|rounds?|refills?|mishandles?|blocks?|deadlocks?|times?\s+out|panics?"
    r"|emits?|includes?|excludes?|accepts?|rejects?|swallows?|mangles?)\b",
    _I,
)
_BUG_STILL = re.compile(
    _LEAD_FILLERS + r"(?P<subj>[^;]{2,120}?)\s+(?:still|continues\s+to|keeps)\s+"
    r"(?:crash(?:es|ing)?|happens?|happening|occurs?|reproduces?|errors?|erroring|hangs?|hanging"
    r"|leaks?|breaks?|raises?|throws?|overflows?|drops?|loses?|miscounts?)\b",
    _I,
)
_TEST_SUBJECT = re.compile(r"\b(?:tests?|test\s+suite|suite|specs?)\b", _I)
#: What may stand before an active fix verb: nothing (after fillers), a fronted phrase
#: ending in punctuation, the agent ("I", "we"), or the change itself ("this commit").
_BUG_SUBJECT = re.compile(
    r"(?:^|[,:;(]|\b(?:i|we|i'?ve|we'?ve|i\s+have|we\s+have|i\s+had|we\s+had|this|that|which"
    r"|it|(?:this|that|the|my|our)\s+(?:change|commit|pr|patch|fix|update|diff|edit|refactor"
    r"|rewrite)s?))\s*(?:(?:also|now|then|finally|just|already|successfully|properly|correctly"
    r"|actually|thereby|both|have|has|had)\s+){0,6}$",
    _I,
)
_BELIEF = re.compile(
    r"\b(?:believe|think|hope|guess|suspect|assume|expect|should|might|may|would|probably"
    r"|likely|hopefully|presumably)\b",
    _I,
)
#: "..., which I" right before a fix verb. The antecedent is found with rfind, not inside
#: the regex: a pattern that also matched the antecedent backtracked in cubic time.
_RELATIVE_FIX = re.compile(
    r",?\s+which\s+(?:i|we)\s+(?:(?:also|then|have|had|now|just)\s+){0,6}$", _I
)


def _relative_antecedent(before: str) -> Span | None:
    """Span of the phrase a "which I fixed" clause refers to, or None if there is none."""
    relative = _RELATIVE_FIX.search(before)
    if relative is None:
        return None
    end = relative.start()
    start = max(before.rfind(char, 0, end) for char in ",;:") + 1
    if not re.search(r"[A-Za-z0-9`]", before[start:end]):
        return None
    return (start, end)


_DESC_BLOCKS = frozenset(
    {"tests", "lint", "typecheck", "build", "complete", "could_not", "feature", "bug"}
)


def _bug_fixed(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []

    def add(desc: tuple[str, Span] | None, negated: bool, anchor: Span) -> None:
        if desc is None:
            return
        hit = PatternHit(ClaimType.BUG_FIXED, {"description": desc[0]}, negated, anchor)
        region = (min(anchor[0], desc[1][0]), max(anchor[1], desc[1][1]))
        out.append(_Candidate(hit, "bug", _DESC_BLOCKS - {"bug"}, region))

    label = _BUG_LABEL.match(v.prose)
    in_section = _BUG_CONTEXT.match(v.context) and v.unit.kind == "list_item"
    if in_section or label is not None:
        item = _section_item(v, label.end() if label is not None else 0)
        if item is not None:  # "## Bug fixes" then "- None" says nothing was fixed
            add(item[0], item[1], label.span() if label is not None else (0, len(v.text)))
        return out
    for match in _BUG_VERB.finditer(v.prose):
        verb = match.group("verb").lower()
        negated = match.group("neg") is not None
        base = verb in _BUG_BASE_FORMS and not negated
        if base and not _after_path_prefix(v, match.start("verb")):
            continue
        before = v.prose[: match.start()]
        if not negated and _FIXED_ADJECTIVE_BEFORE.search(before):
            continue
        if _FIXED_ADJECTIVE_AFTER.match(v.prose, match.end()):
            continue
        if not _BUG_SUBJECT.search(_LEAD.sub("", before, count=1)):
            continue  # "The old implementation fixed the seed": not the agent's fix
        if _BELIEF.search(before):
            continue  # "I believe this resolves the race": a hope, not a claim
        antecedent = _relative_antecedent(before)
        if antecedent is not None:  # "The failure is test_x, which I fixed afterwards"
            add(_description(v, antecedent[0], antecedent[1]), negated, match.span("verb"))
            continue
        add(_description(v, match.end()), negated, match.span("verb"))
    for match in _BUG_GERUND.finditer(v.prose):
        add(_description(v, match.end()), False, match.span())
    if out:
        return out
    for regex, negated in (
        (_BUG_PASSIVE_NEGATED, True),
        (_BUG_PASSIVE, False),
        (_BUG_STILL, True),
    ):
        found = regex.match(v.prose)
        if found is None:
            continue
        subject = found.group("subj")
        if not _BUG_NOUNS.search(subject):
            continue
        if regex is _BUG_STILL and _TEST_SUBJECT.search(subject):
            continue
        add(_description(v, found.start("subj"), found.end("subj")), negated, found.span())
        return out
    no_longer = _BUG_NO_LONGER.match(v.prose)
    if no_longer is not None and not _TEST_SUBJECT.search(no_longer.group("subj")):
        add(_description(v, no_longer.start("subj")), False, no_longer.span())
    return out


_FEATURE_NOUNS = (
    r"(?:flags?|options?|switch(?:es)?|subcommands?|commands?|endpoints?|routes?|modes?"
    r"|parameters?|params?|arguments?|args?|settings?|features?|methods?|apis?|filters?|filtering"
    r"|sorting|validation|validators?|handlers?|hooks?|support|pagination|caching|cache|retries"
    r"|retry|backoff|ttl|timeouts?|formatter|converter|conversion|middleware|plugins?"
    r"|properties|property|fields?|events?|listeners?|overrides?|defaults|coercion|anchors?"
    r"|toc|table\s+of\s+contents|jitter|output|limit|limits|keyword"
    r"|kwarg|attribute|attributes)"
)
_FEATURE_IMPLEMENTED = re.compile(
    r"(?P<neg>\b" + _NEGATOR + r"\s+(?:yet\s+)?)?"
    r"\b(?P<verb>implemented|implements|implement|added\s+support\s+for|adds\s+support\s+for"
    r"|add\s+support\s+for|introduced\s+support\s+for|enabled\s+support\s+for"
    r"|built\s+support\s+for|added\s+the\s+ability\s+to|adds\s+the\s+ability\s+to)\b",
    _I,
)
_FEATURE_ADDED = re.compile(
    r"(?P<neg>\b" + _NEGATOR + r"\s+(?:yet\s+)?)?"
    r"\b(?P<verb>added|adds|add|introduced|introduces|introduce|created|creates|create|exposed"
    r"|exposes|expose)\s+"
    r"(?P<obj>(?:(?:a|an|the|new|optional|basic|full|simple|proper|initial|first-class|built-in"
    r"|configurable|dedicated|separate)\s+){0,6}"
    r"(?:(?:(?!(?:with|to|for|in|from|of|on|at|by|into|and|or|that|which)\b)"
    r"(?:`C+`|--?[A-Za-z][\w-]*|[A-Za-z][\w'-]*)\s+){0,4}?" + _FEATURE_NOUNS + r"\b"
    r"|(?P<flag>`C+`|--[A-Za-z][\w-]*)(?=\s|$|[.,;:)])))",
    _I,
)
_FEATURE_BASE_FORMS = frozenset({"implement", "add", "introduce", "create", "expose"})
#: Present-tense forms, which describe existing code ("The function implements a binary
#: search") unless their subject is the change itself ("This PR adds a flag").
_FEATURE_PRESENT_FORMS = frozenset({"implements", "adds", "introduces", "creates", "exposes"})
_CHANGE_SUBJECT = re.compile(
    r"(?:^|[,:;(]|\b(?:this|that|which|it|(?:this|that|the|my|our)\s+(?:change|commit|pr|patch"
    r"|fix|update|diff|edit|refactor|rewrite|pull\s+request|merge\s+request|mr|branch)s?))\s*"
    r"(?:(?:also|now|then|finally|just|additionally)\s+){0,3}$",
    _I,
)
_BE_BEFORE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|get|got|gets|isn'?t|aren'?t|wasn'?t|weren'?t|not)\s+"
    r"(?:(?:now|also|fully|properly|finally|completely|already|yet|still|all|both|just|not)\s+){0,6}$",
    _I,
)
_FEATURE_SKIP_OBJECT = re.compile(
    r"^\s*(?:all\b|everything\b|the\s+(?:requested\s+|required\s+)?changes\b"
    r"|all\s+(?:the\s+)?(?:requested\s+)?(?:changes|requirements|features|items|tasks)\b"
    r"|the\s+task\b|it\b|this\b|that\b|them\b|(?:the\s+|a\s+|new\s+|some\s+){0,6}(?:tests?|specs?)\b)",
    _I,
)
_FEATURE_FIX_OBJECT = re.compile(r"^\s*(?:a|the)\s+(?:bug\s*)?fix\b", _I)
_FEATURE_PASSIVE = re.compile(
    _LEAD_FILLERS + r"(?P<subj>[^;]{2,120}?)\s+(?P<neg>(?:is|are)\s*(?:n[o']?t|not)\s+(?:yet\s+)?"
    r"|(?:is|are|has\s+been|have\s+been)\s+(?:now\s+)?(?:(?:fully|also)\s+)?)"
    r"(?:implemented|supported|in\s+place|working|wired\s+up|functional)\b",
    _I,
)
_FEATURE_SUBJECT_CLAUSE = re.compile(
    r"\b(?:because|since|could|couldn'?t|can'?t|cannot|was|were|is|are|isn'?t|aren'?t|wasn'?t"
    r"|weren'?t|i|we|if|when|which|but|so|that)\b",
    _I,
)
_FEATURE_SUBJECT_NOUN = re.compile(r"`C+`|--[A-Za-z]|\b" + _FEATURE_NOUNS + r"\b", _I)
_FEATURE_SUBJECT_SKIP = re.compile(
    r"^\W*(?:everything|all|it|this|that|these|those|they|nothing|not\s+everything"
    r"|(?:the\s+)?(?:task|work|job|implementation|changes?|fix|refactor\w*|migration|bump"
    r"|upgrade|update|tests?|test\s+suite|suite|build|linter|lint|ci|project|code|app)"
    r")\W*$",
    _I,
)
_FEATURE_NOW = re.compile(
    r"\bnow\s+(?:supports|accepts|respects|honou?rs|provides|exposes|offers|emits|outputs|has"
    r"|includes|validates|implements)\b",
    _I,
)
_FEATURE_LABEL = re.compile(
    r"^\W*(?:implemented|feature|new\s+feature|added\s+feature|features?\s+added)\s*:\s*(?=\S)",
    _I,
)
_FEATURE_CONTEXT = re.compile(
    r"^(?:implemented|features?|new\s+features?|added\s+features?"
    r"|features?\s+(?:added|implemented))$",
    _I,
)


def _feature(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []

    def add(desc: tuple[str, Span] | None, negated: bool, anchor: Span, kind: ClaimType) -> None:
        if desc is None:
            return
        hit = PatternHit(kind, {"description": desc[0]}, negated, anchor)
        region = (min(anchor[0], desc[1][0]), max(anchor[1], desc[1][1]))
        family = "bug" if kind is ClaimType.BUG_FIXED else "feature"
        out.append(_Candidate(hit, family, _DESC_BLOCKS - {family}, region))

    feature = ClaimType.FEATURE_IMPLEMENTED
    label = _FEATURE_LABEL.match(v.prose)
    in_section = _FEATURE_CONTEXT.match(v.context) and v.unit.kind == "list_item"
    if in_section or label is not None:
        item = _section_item(v, label.end() if label is not None else 0)
        if item is not None:  # "Pagination (not implemented; ...)" admits it is missing
            anchor = label.span() if label is not None else (0, len(v.text))
            add(item[0], item[1], anchor, feature)
        return out

    def describes_code(match: re.Match[str]) -> bool:
        verb = match.group("verb").lower().split()[0]
        before = _LEAD.sub("", v.prose[: match.start()], count=1)
        return verb in _FEATURE_PRESENT_FORMS and not _CHANGE_SUBJECT.search(before)

    for match in _FEATURE_IMPLEMENTED.finditer(v.prose):
        negated = match.group("neg") is not None
        base = match.group("verb").lower() in _FEATURE_BASE_FORMS and not negated
        if base and not _after_path_prefix(v, match.start("verb")):
            continue
        if _BE_BEFORE.search(v.prose[: match.start()]) or describes_code(match):
            continue
        rest = v.prose[match.end() :]
        if _FEATURE_SKIP_OBJECT.match(rest):
            continue
        kind = ClaimType.BUG_FIXED if _FEATURE_FIX_OBJECT.match(rest) else feature
        add(_description(v, match.end()), negated, match.span("verb"), kind)
    for match in _FEATURE_ADDED.finditer(v.prose):
        negated = match.group("neg") is not None
        base = match.group("verb").lower() in _FEATURE_BASE_FORMS and not negated
        if (base and not _after_path_prefix(v, match.start("verb"))) or describes_code(match):
            continue
        flag = match.group("flag")
        if flag and flag.startswith("`"):
            span = v.code_at(match.start("flag"))
            if span is None or not v.content(span).startswith("-"):
                continue
        add(_description(v, match.start("obj")), negated, match.span("verb"), feature)
    if out:
        return _first_per_span(out)
    passive = _FEATURE_PASSIVE.match(v.prose)
    if (
        passive is not None
        and not _FEATURE_SUBJECT_SKIP.match(passive.group("subj"))
        and not _FEATURE_SUBJECT_CLAUSE.search(passive.group("subj"))
        and _FEATURE_SUBJECT_NOUN.search(passive.group("subj"))
    ):
        negated = bool(re.search(r"n[o']?t\b", passive.group("neg"), _I))
        desc = _description(v, passive.start("subj"), passive.end("subj"))
        add(desc, negated, passive.span(), feature)
        return out
    now = _FEATURE_NOW.search(v.prose)
    if now is not None:
        add(_description(v, 0), False, now.span(), feature)
    return _first_per_span(out)


_COULD_NOT = re.compile(
    r"\b(?P<cue>could\s*n[o']?t|could\s+not|can'?t|cannot|can\s+not"
    r"|(?:have|has)\s*n[o']?t\s+been\s+able\s+to|(?:have|has)\s+not\s+been\s+able\s+to"
    r"|(?:was|were|am|is|are)\s*n[o']?t\s+able\s+to|(?:was|were|am|is|are)\s+not\s+able\s+to"
    r"|(?:was|were|am|is|are)\s+unable\s+to|unable\s+to|not\s+able\s+to|failed\s+to"
    r"|did\s*n[o']?t\s+manage\s+to|did\s+not\s+manage\s+to"
    r"|did\s*n[o']?t\s+get\s+(?:a\s+chance\s+)?to|did\s+not\s+get\s+(?:a\s+chance\s+)?to"
    r"|ran\s+out\s+of\s+time\s+(?:to|before|for)|had\s+no\s+way\s+(?:to|of)"
    r"|there\s+(?:was|is)\s+no\s+way\s+to|it\s+(?:was|is)\s*(?:n[o']?t|not)\s+possible\s+to"
    r"|(?:was|is)\s*(?:n[o']?t|not)\s+possible\s+to|it\s+(?:was|is)\s+impossible\s+to"
    r"|(?:was|is)\s+impossible\s+to)\s+(?=\S)",
    _I,
)
_COULD_NOT_AGENT = re.compile(
    r"^\W*(?:(?:unfortunately|however|sadly|note|but|so|and|also|still|then|ultimately"
    r"|in\s+the\s+end|at\s+the\s+moment|currently|right\s+now|for\s+now|caveat|limitation"
    r"|known\s+issue|blocker|blocked)" + _SEP + r"){0,8}(?:(?:i|we)\s+)?"
    r"(?:(?:also|still|just|really|unfortunately|ultimately|simply|then|now|currently)\s+){0,4}$",
    _I,
)
#: Cues that name no subject because the agent is meant: "ran out of time to", "had no
#: way to", "there was no way to", "it was not possible to" (past tense only: "it is not
#: possible to set X" describes the code).
_COULD_NOT_IMPERSONAL = re.compile(r"^(?:ran|had|there\s+was|it\s+was)\b", _I)
#: Present-tense cues that carry their own subject ("it is not possible to", "there is no
#: way to"): like another subject, they need an admission about the work.
_COULD_NOT_PRESENT_IMPERSONAL = re.compile(r"^(?:it\s+is|there\s+is|is)\b", _I)
#: Past-tense cues: an event in the run ("could not", "was unable to"), not a rule.
_COULD_NOT_PAST = re.compile(r"^(?:could|was|were|had|have|has|did|ran|there\s+was|it\s+was)", _I)
#: A passive admission about the work: "the tests could not be run".
_WORK_PASSIVE = re.compile(
    r"be\s+(?:re-?)?(?:run|executed|tested|verified|reproduced|started|installed|reached|built"
    r"|compiled|completed|finished|checked|exercised|validated|confirmed|measured|fetched"
    r"|downloaded|accessed|loaded|imported|deployed|launched|evaluated|benchmarked|profiled"
    r"|tried|done|set\s+up|configured|connected)\b",
    _I,
)
#: An active work verb whose subject is not the agent: "the e2e suite can't run here".
_WORK_ACTIVE = re.compile(
    r"(?:re-?)?(?:run|start|connect|reach|complete|finish|load|import|install|execute|build"
    r"|compile|pass|download|fetch|launch|bind|access|authenticate)\b",
    _I,
)
#: Where or why the work could not happen: the sandbox, a missing service or credential.
_ENV_QUALIFIER = re.compile(
    r"\b(?:here|locally|offline|in\s+(?:this|the|my|our)\s+(?:environment|sandbox|container"
    r"|workspace|vm|machine|session|setup)|in\s+(?:the\s+)?ci|on\s+this\s+(?:machine|box|host)"
    r"|without\s+(?:network(?:\s+access)?|internet|docker|postgres(?:ql)?|redis|kafka|a\s+database"
    r"|database|credentials|an?\s+api\s+key|api\s+keys|access|a\s+gpu|gpu|a\s+browser|browser"
    r"|aws|cloud\s+credentials)"
    r"|(?:because|since|as|due\s+to)\b[^.;]{0,100}?\b(?:(?:is|are|was|were)\s*(?:n[o']?t|not)\s+"
    r"(?:available|installed|running|reachable|accessible|configured|set|present|allowed"
    r"|permitted|provided)|(?:is|are|was|were)\s+(?:missing|unavailable|down|blocked|offline"
    r"|disabled|unreachable)|no\s+(?:network|internet|access|credentials|docker|database|gpu"
    r"|browser|api\s+key)))\b|\(\s*(?:no|missing|needs?|requires?)\b",
    _I,
)
#: Words before the cue that make it a description of the code or of the old bug rather
#: than an admission: "before this change the server could not start", "the bug was that
#: the parser could not parse", "the validation ensures tokens cannot be reused".
_COULD_NOT_DESCRIBES = re.compile(
    r"\b(?:previously|originally|formerly|used\s+to|before\s+(?:this|the|my|our|that)\s+"
    r"(?:change|fix|patch|commit|pr|update|refactor)|before\s+(?:fixing|the\s+fix|my\s+fix)"
    r"|without\s+(?:the|this|my)\s+(?:fix|change|patch)|(?:the|a)\s+(?:bug|problem|issue|root"
    r"\s+cause|cause|crash|regression)\s+(?:was|is)|ensures?|ensuring|makes?\s+sure"
    r"|guarantees?|prevents?|so\s+that)\b",
    _I,
)
#: "I could not find any issues": a clean result, not an admission.
_FOUND_NOTHING = re.compile(
    r"(?:find|see|spot|detect|identify|observe)\s+(?:any\s+(?:other\s+|more\s+"
    r"|remaining\s+|new\s+)?|a\s+single\s+|an?\s+)?(?:issues?|problems?|failures?|errors?"
    r"|bugs?|regressions?|differences?|discrepanc(?:y|ies)|anything\s+(?:wrong|else|broken))\b",
    _I,
)


def _could_not(v: _View) -> list[_Candidate]:
    """``could_not`` claims: the agent admits something it could not do.

    The subject must be the agent: "I" or "we", no subject at all ("Couldn't reproduce
    the failure"), or an impersonal past cue ("ran out of time to", "there was no way
    to"). Another subject counts only for an admission about the work: a past passive
    of a work verb ("the tests could not be run"), or a work verb with a reason in the
    environment ("the e2e suite can't run here since Docker isn't available"). Dated
    statements and descriptions of the code or of the old bug ("previously the CLI could
    not parse `--json`", "tokens cannot be reused") and clean results ("I could not find
    any issues") give no claim.
    """
    for match in _COULD_NOT.finditer(v.prose):
        cue = match.group("cue").lower()
        before = v.prose[: match.start()]
        after = v.prose[match.end() :]
        if _COULD_NOT_DESCRIBES.search(before) or _FOUND_NOTHING.match(after):
            continue
        agent = bool(_COULD_NOT_IMPERSONAL.match(cue)) or (
            bool(_COULD_NOT_AGENT.match(before)) and not _COULD_NOT_PRESENT_IMPERSONAL.match(cue)
        )
        if not agent:
            if cue.startswith("failed"):
                continue
            past = bool(_COULD_NOT_PAST.match(cue))
            if _WORK_PASSIVE.match(after):
                admits = past or bool(_ENV_QUALIFIER.search(after))
            else:
                admits = bool(_WORK_ACTIVE.match(after)) and bool(_ENV_QUALIFIER.search(after))
            if not admits:
                continue
        lead = _LEAD.match(v.prose)
        start = match.end() if agent else (lead.end() if lead is not None else 0)
        desc = _description(v, start)
        if desc is None:
            continue
        description = desc[0] if agent else v.text[start : desc[1][1]]
        hit = PatternHit(ClaimType.COULD_NOT, {"description": description}, False, match.span())
        region = (match.start() if agent else 0, len(v.text))
        return [_Candidate(hit, "could_not", _ALL_FAMILIES, region)]
    return []


_COMPLETE_LEAD = (
    r"^\W*(?:(?:ok(?:ay)?|great|alright|all\s+right|so|and|yes|overall|in\s+short|in\s+summary"
    r"|summary|to\s+summari[sz]e|tl;?dr|status|result|final\s+status|update|good\s+news)"
    r"(?:\s*[,:!.\-]+\s*|\s+)){0,8}"
)
_COMPLETE = re.compile(
    _COMPLETE_LEAD + r"(?P<claim>"
    r"(?:(?:i'?m|i\s+am|we'?re|we\s+are|it'?s|it\s+is|that'?s|this\s+is)\s+)?(?:all\s+|now\s+)?"
    r"(?:done|finished|complete|completed)(?:\s+now)?"
    r"|(?:the\s+)?(?:task|work|job|implementation|change|changes|feature|fix|refactor(?:ing)?"
    r"|migration|bump|upgrade|update)\s+(?:is|are|has\s+been|have\s+been|was|were)\s+(?:now\s+)?"
    r"(?:(?:fully|successfully|all)\s+)?(?:done|complete|completed|finished)"
    r"|(?:i\s+have|i'?ve|we\s+have|we'?ve)\s+(?:now\s+)?(?:successfully\s+)?(?:completed|finished"
    r"|done|implemented|made)\s+(?:the\s+(?:requested\s+)?task|everything|all\s+(?:of\s+)?"
    r"(?:the\s+)?(?:requested\s+|required\s+)?(?:changes|requirements|tasks|items|steps|work)"
    r"|the\s+(?:requested\s+|required\s+)?changes|the\s+work)"
    r"|everything\s+(?:is\s+|has\s+been\s+|'s\s+)?(?:now\s+)?(?:done|complete|completed"
    r"|implemented|working|in\s+place|finished|addressed|ready|set)"
    r"(?:\s+and\s+(?:working|tested|passing|verified))?"
    r"|(?:all\s+)?(?:the\s+)?(?:requirements|requested\s+changes|changes|items|tasks"
    r"|acceptance\s+criteria|steps|requested\s+features)\s+(?:are|have\s+been)\s+(?:now\s+)?"
    r"(?:(?:all|fully|successfully)\s+)?(?:met|done|implemented|completed|addressed|satisfied"
    r"|in\s+place|handled|finished)"
    r"|all\s+set|(?:task|work)\s+complete(?:d)?|everything\s+works|ready\s+for\s+review"
    r"|ready\s+to\s+merge|that'?s\s+(?:it|everything)|good\s+to\s+go"
    r")(?=\s*(?:[.!:;,\-)]|→|$|(?:and|but)\b))",
    _I,
)
_NOT_COMPLETE = re.compile(
    _COMPLETE_LEAD + r"(?P<claim>"
    r"(?:the\s+)?(?:task|work|job|implementation|feature|fix|change|changes)\s+(?:is|are|was"
    r"|were)\s*(?:n[o']?t|not)\s+(?:yet\s+|fully\s+|quite\s+|entirely\s+)?(?:done|complete"
    r"|completed|finished)"
    r"|(?:i'?m|i\s+am|we'?re|we\s+are|it'?s|it\s+is)\s*(?:n[o']?t|not)\s+(?:yet\s+|quite\s+"
    r"|fully\s+)?(?:done|finished|complete)"
    r"|not\s+(?:yet\s+|quite\s+)?(?:done|finished|complete|completed)"
    r"|(?:the\s+)?(?:task|work|implementation)\s+is\s+(?:only\s+)?(?:partially|partly)\s+"
    r"(?:done|complete|completed|finished)"
    r"|(?:this|the\s+task|the\s+work|it|the\s+implementation)\s+is\s+(?:still\s+)?(?:incomplete"
    r"|unfinished|a\s+work\s+in\s+progress|in\s+progress|partial)"
    r"|not\s+everything\s+(?:is\s+)?(?:done|working|implemented|complete)"
    r"|(?:i|we)\s+(?:have\s*n[o']?t|have\s+not|did\s*n[o']?t|did\s+not)\s+(?:yet\s+)?"
    r"(?:finish(?:ed)?|complete[d]?)\s+(?:the\s+task|everything|all\s+(?:of\s+)?(?:the\s+)?"
    r"(?:changes|requirements|work))"
    r")\b",
    _I,
)


#: In a heading or label line, only an explicit status counts as a task_complete claim:
#: a "Status:" prefix, a verb ("Everything is done"), or a status phrase ("Task complete").
#: A bare "Done", "Not done" or "Completed" names a section.
_STATUS_PREFIX = re.compile(r"^\W*(?:(?:final|overall)\s+)?(?:status|result|state)\s*[:\-]", _I)
_STATUS_STATEMENT = re.compile(
    r"\b(?:is|are|was|were|am|has\s+been|have\s+been)\b|'(?:s|re|m|ve)\b|\b(?:task|work)\s+complete"
    r"|\ball\s+set\b|\bready\s+(?:for\s+review|to\s+merge)\b|\bgood\s+to\s+go\b"
    r"|\bthat'?s\s+(?:it|everything)\b|\b(?:i|we)\s+(?:have|'ve)\b",
    _I,
)


def _task_complete(v: _View) -> list[_Candidate]:
    for regex, negated in ((_NOT_COMPLETE, True), (_COMPLETE, False)):
        match = regex.match(v.prose)
        if match is None:
            continue
        explicit = _STATUS_PREFIX.match(v.prose) or _STATUS_STATEMENT.search(match.group("claim"))
        if v.unit.label and not explicit:
            return []  # "## Done", "**Not done:**": a section name, not a claim
        hit = PatternHit(ClaimType.TASK_COMPLETE, {}, negated, match.span("claim"))
        return [_Candidate(hit, "complete", frozenset({"feature"}), match.span("claim"))]
    return []


_RAN_VERB = re.compile(
    r"(?P<neg>\b(?:did\s*n[o']?t|did\s+not|have\s*n[o']?t|have\s+not|has\s*n[o']?t|has\s+not"
    r"|had\s*n[o']?t|had\s+not|never)\s+(?:(?:yet|actually|even|get\s+to|bother\s+to)\s+)?)?"
    r"\b(?P<verb>re-?ran|reran|ran|executed|invoked|kicked\s+off|triggered|re-?run|run|execute)\b"
    r"(?!\s+(?:into|across|out\s+of)\b)",  # "ran into test failures" ran nothing
    _I,
)
_RAN_BASE_FORMS = frozenset({"run", "rerun", "re-run", "execute"})
_PERFECT = re.compile(
    r"(?:\b(?:have|has|had)|'ve|'d)\s+(?:(?:also|now|just|already|then|since|both)\s+){0,6}$", _I
)
_ADVICE_BEFORE = re.compile(
    r"\b(?:will|would|should|could|can|might|may|must|need\s+to|needs\s+to|have\s+to|has\s+to"
    r"|going\s+to|want\s+to|to|please|you|recommend|suggest|try|let'?s|lets|i'?ll|we'?ll)\s+"
    r"(?:(?:also|then|now|just|first|still|re-?)\s+){0,6}$",
    _I,
)
_ADVICE = re.compile(
    r"\b(?:you\s+can|you\s+could|you\s+may|you\s+should|you\s+might|to\s+run|can\s+be\s+run"
    r"|run\s+it\s+with|please\s+run|try\s+running|to\s+reproduce|to\s+verify|to\s+check"
    r"|if\s+you|recommend|suggest|next\s+steps?)\b",
    _I,
)
_VERIFIED_WITH = re.compile(
    r"\b(?:verified|tested|checked|confirmed|validated|exercised|smoke-tested|sanity-checked)"
    r"\s+(?:(?:it|this|that|them|everything|the\s+(?:fix|change|changes|behaviou?r|output|feature"
    r"|flag|cli|result|endpoint|script|command|patch))\s+)?(?:(?:manually|locally"
    r"|end[- ]to[- ]end|again|also|further)\s+){0,6}(?:with|using|via|by\s+running|through"
    r"|by\s+executing)\s+",
    _I,
)
_BY_RUNNING = re.compile(r"\b(?:by|after|when|while|from|upon)\s+(?:re-?)?running\s+", _I)
_RUNNING_START = re.compile(r"^\W*(?:re-?)?running\s+", _I)
_RUNNING_RESULT = re.compile(
    r"\s*(?:[:,→]|->|=>|-)?\s*(?:now\s+)?(?:shows?|gives?|yields?|reports?|returns?|prints?"
    r"|outputs?|produces?|results\s+in|passes|passed|fails|failed|succeeds?|succeeded|confirms?"
    r"|exits?|exited|completes?|completed|works?)\b",
    _I,
)
_SKIPPED = re.compile(r"\b(?:skipped|skipping)\s+(?:running\s+)?", _I)
_WITHOUT_RUNNING = re.compile(r"\bwithout\s+(?:re-?)?running\s+", _I)
_PASSIVE_RAN = re.compile(
    r"(?P<neg>\s+(?:was|were|has|have)\s*(?:n[o']?t|not)\s+(?:been\s+)?|\s+(?:was|were|has\s+been"
    r"|have\s+been)\s+)(?:re-?)?(?:run|executed)\b",
    _I,
)
_PASSIVE_SUBJECT = re.compile(
    r"(?:`C+`|(?:the\s+)?(?:(?:[\w-]+)\s+){0,2}?(?:test\s+suite|tests|linter|type\s*checker"
    r"|build))\s*$",
    _I,
)
_PASSIVE_RUN_WITH = re.compile(
    r"\b(?:were|was|been|is|are)\s+(?:re-?)?(?:run|executed)\s+(?:(?:again|locally|manually)\s+)?"
    r"(?:with|using|via)\s+",
    _I,
)
_NOT_RUN = re.compile(
    r"^\W*(?P<subj>(?:the\s+)?(?:(?:full|whole|entire|unit|integration|e2e)\s+)?(?:tests?"
    r"|test\s+suite|suite|linters?|lint(?:ing)?|type\s*check(?:er|ers|ing|s)?|typecheck(?:ing|s)?"
    r"|builds?))\s*(?::\s*)?(?:(?:were|was|have\s+been|has\s+been)\s+)?not\s+(?:yet\s+)?"
    r"(?:been\s+)?(?:re-?)?run\b",
    _I,
)
_BARE_NOT_RUN = re.compile(r"^[^\w`]*(?:not\s+(?:yet\s+)?run|none\s+run|skipped)\b", _I)
#: What may follow a bare "Not run" for it to mean the tests: nothing, or only a reason.
_REASON_ONLY = re.compile(r"\s*(?:[.!;]\s*)?$|\s*\(|\s*,?\s*(?:because|since|as|due\s+to)\b", _I)
_NOT_RUN_LEAD = re.compile(r"\s*(?::|-{1,2}|->)\s*", _I)
_TESTING_CONTEXT = re.compile(r"\b(?:tests?|testing|verification|validation)\b", _I)
_NEGATED_BEFORE = re.compile(r"(?:\bnot|n't|\bnever)\b", _I)
_UNIT_START_CODE = re.compile(r"^[^\w`]*(?:[A-Za-z][\w /-]{0,30}?\s*:\s*)?(?=`)")
_RESULT_AFTER = re.compile(
    r"\s*(?:[:→]|->|=>|-{1,2}\s|\(|✅|❌|✔|✖"
    r"|(?:now\s+)?(?:passe[sd]|fail(?:s|ed)|succeed(?:s|ed)|is\s+(?:clean|green|happy|passing"
    r"|failing)|reports?|shows?|returns?|gives?|exit(?:s|ed)?|runs?|ran|completes?|completed"
    r"|ok|works?|outputs?|prints?|produces?|compiles?|compiled|builds?|built|\d)\b)",
    _I,
)
_UNIT_START_BARE = re.compile(
    r"^\W*(?P<prog>pytest|mypy|ruff(?:\s+check)?|eslint|tsc|jest|vitest|flake8|pyright|pylint"
    r"|npm\s+test|npm\s+run\s+[\w:-]+|yarn\s+test|pnpm\s+test)\s*(?::|→|->|=>|\s-\s)",
    _I,
)
#: Section labels that list commands the agent ran ("Commands run", "How I verified",
#: "Verification"). Labels that give the reader instructions do not count.
_COMMANDS_CONTEXT = re.compile(
    r"\b(?:commands?\s+(?:i\s+|we\s+)?(?:ran|run|executed|used)|ran|executed|verification"
    r"|verified|testing|tests?\s+(?:run|ran|executed)|test\s+results?|checks?(?:\s+run)?"
    r"|how\s+(?:i|we)\s+(?:tested|verified|checked|validated)|what\s+(?:i|we)\s+ran|validation"
    r"|validated)\b",
    _I,
)
#: Instruction labels: "How to verify", "To run it locally", "Commands to run before
#: merging", "Testing instructions", "Steps to reproduce".
_INSTRUCTION_CONTEXT = re.compile(
    r"\b(?:how\s+to|to\s+(?:run|verify|test|check|reproduce|try|use|build|install|deploy)"
    r"|instructions?|steps\s+to|reproduc\w*|before\s+merg\w*|usage|you\s+can|next\s+steps?"
    r"|manual(?:ly)?|try\s+it|recommended|suggested|optional)\b",
    _I,
)


def _ran_command(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []

    def add(items: list[_CommandItem], negated: bool, anchor_start: int) -> None:
        for item in items:
            if negated and item.subset:
                # "I didn't run the integration tests": the verifier matches generic runs
                # of any part of the suite, so a negated subset claim cannot be judged.
                continue
            hit = PatternHit(
                ClaimType.RAN_COMMAND, {"command": item.command}, negated, (anchor_start, item.end)
            )
            blocks = _STATUS_FAMILIES if negated else frozenset()
            out.append(_Candidate(hit, "command", blocks, (anchor_start, item.end)))

    advice = bool(_ADVICE.search(v.prose))
    for match in _RAN_VERB.finditer(v.prose):
        negated = match.group("neg") is not None
        before = v.prose[: match.start()]
        verb = match.group("verb").lower().replace(" ", "")
        if verb in _RAN_BASE_FORMS and not negated and not _PERFECT.search(before):
            continue
        if not negated and _ADVICE_BEFORE.search(before):
            continue
        add(_command_items(v, match.end()), negated, match.start())
    if not advice:
        for regex in (_VERIFIED_WITH, _BY_RUNNING):
            for match in regex.finditer(v.prose):
                add(_command_items(v, match.end()), False, match.start())
        running = _RUNNING_START.match(v.prose)
        if running is not None:
            items = _command_items(v, running.end())
            if items and _RUNNING_RESULT.match(v.prose, items[-1].end):
                add(items, False, running.start())
    bare_not_run = _BARE_NOT_RUN.match(v.prose)
    if bare_not_run is not None and _TESTING_CONTEXT.search(v.context):
        # "**Testing**" then "- Not run (no AWS credentials)": only a reason follows, so
        # the tests were not run. "- Skipped the e2e suite" names what was skipped.
        rest = bare_not_run.end()
        lead = _NOT_RUN_LEAD.match(v.prose, rest)
        if _REASON_ONLY.match(v.prose, rest):
            add([_CommandItem(0, len(v.text), "the tests")], True, 0)
        elif lead is not None:
            items = _command_items(v, lead.end())
            if items:
                add(items, True, 0)
            else:
                add([_CommandItem(0, len(v.text), "the tests")], True, 0)  # "Not run: no DB"
    not_run = _NOT_RUN.match(v.prose)
    generic = generic_command(not_run.group("subj")) if not_run is not None else None
    if not_run is not None and generic is not None:
        phrase, subset = generic
        add([_CommandItem(not_run.start("subj"), not_run.end(), phrase, subset)], True, 0)
    for match in _PASSIVE_RUN_WITH.finditer(v.prose):
        if not advice and not _NEGATED_BEFORE.search(v.prose[: match.start()]):
            add(_command_items(v, match.end()), False, match.start())
    for regex in (_SKIPPED, _WITHOUT_RUNNING):
        for match in regex.finditer(v.prose):
            add(_command_items(v, match.end()), True, match.start())
    for match in _PASSIVE_RAN.finditer(v.prose):
        subject = _PASSIVE_SUBJECT.search(v.prose, 0, match.start())
        if subject is None:
            continue
        items = _command_items(v, subject.start())
        if items:
            add(items[-1:], "n" in match.group("neg").lower().replace("been", ""), subject.start())
    lead = _UNIT_START_CODE.match(v.prose)
    span = v.code_at(lead.end()) if lead is not None else None
    if span is not None and not advice:
        command = command_param(v.content(span))
        result = _RESULT_AFTER.match(v.prose, span[1])
        at_end = not v.prose[span[1] :].strip(" .:;,")
        listed = _COMMANDS_CONTEXT.search(v.context) and not _INSTRUCTION_CONTEXT.search(v.context)
        if command is not None and (result is not None or (at_end and listed)):
            add([_CommandItem(span[0], span[1], command)], False, span[0])
    bare = _UNIT_START_BARE.match(v.prose)
    if bare is not None and not advice:
        command = " ".join(v.text[bare.start("prog") : bare.end("prog")].split())
        add([_CommandItem(bare.start("prog"), bare.end("prog"), command)], False, bare.start())
    return out


_TEST_NOUN = r"(?:test\s+cases?|tests?|specs?|cases?)"
_COUNT_GAP = r"(?:(?:(?:[a-z][\w-]*)\s+)?" + _TEST_NOUN + r"\s+)?"
_NOT_REFERENCE = r"(?<![\w.])(?<!the\s)(?<!these\s)(?<!those\s)(?<!both\s)(?<!of\s)"
#: A number after one of these words is a date, a version or a quantity, not a test count
#: ("dates before 1970 fail to parse").
_NOT_AFTER_PREPOSITION = (
    r"(?<!before\s)(?<!after\s)(?<!since\s)(?<!until\s)(?<!from\s)(?<!than\s)(?<!in\s)"
    r"(?<!on\s)(?<!at\s)(?<!by\s)(?<!over\s)(?<!under\s)(?<!to\s)"
)
_ALL_N = re.compile(
    r"(?<!not\s)\ball\s+(?:of\s+the\s+|the\s+|of\s+)?(?P<n>"
    + _NUM
    + r")\s+"
    + _COUNT_GAP
    + r"(?:(?:now|still|also|are|were)\s+){0,6}(?:pass(?:es|ed|ing)?|succeed(?:s|ed)?|green|ok)\b",
    _I,
)
_N_ALL = re.compile(
    _NOT_REFERENCE
    + r"(?P<n>"
    + _NUM
    + r")\s+(?:(?:[a-z][\w-]*)\s+)?"
    + _TEST_NOUN
    + r"\s*[,:;(]?\s*(?:and\s+)?all\s+(?:of\s+them\s+)?(?:pass(?:es|ed|ing)?|green"
    r"|succeed(?:ed|s)?)",
    _I,
)
#: "12/13", "12 of 13", "12 out of 13", with an optional test noun and pass verb. The
#: denominator may end a sentence ("Tests: 40/42."), but a decimal ("40/42.5") is no count.
_FRACTION = re.compile(
    r"(?<![\w./])(?P<p>\d+)\s*(?:/|of|out\s+of)\s*(?:the\s+)?(?P<t>\d+)(?!\w|\.\d)"
    r"(?P<noun>\s+(?:(?:[a-z][\w-]*)\s+)?" + _TEST_NOUN + r")?"
    r"(?P<verb>\s+(?:(?:are|now|still|were)\s+){0,6}(?:pass(?:es|ed|ing)?|succeed(?:s|ed)?|green"
    r"|ok))?",
    _I,
)
_FAIL_AFTER = re.compile(
    r"\s+(?:(?:are|is|were|was|still|now|also|currently)\s+){0,6}(?:fail(?:s|ed|ing)?|broken|red"
    r"|erroring|error(?:s|ed)?)\b",
    _I,
)
#: A fraction after a pass word or a tests label: "Passing: 40/42", "Tests: 40/42.".
_FRACTION_LEAD = re.compile(
    r"\b(?:(?:passing|passed|pass)\s*[:=]?|(?:tests?|test\s+results?|unit\s+tests?)\s*[:=])"
    r"\s*(?P<p>\d+)\s*/\s*(?P<t>\d+)(?!\w|\.\d|\s*(?:\w+\s+)?(?:fail|broken|red|error))",
    _I,
)
_N_PASSED = re.compile(
    _NOT_REFERENCE
    + _NOT_AFTER_PREPOSITION
    + r"(?P<n>"
    + _NUM
    + r")\s+(?P<gap>"
    + _COUNT_GAP
    + r")(?:(?:now|all|still|also|are|were|have|had)\s+){0,6}(?:pass(?:ed|es|ing)?"
    r"|succeed(?:ed|s)?)\b(?!\s+(?:validation|the|a|an|through)\b)",
    _I,
)
_N_FAILED = re.compile(
    _NOT_REFERENCE
    + _NOT_AFTER_PREPOSITION
    + r"(?P<n>"
    + _NUM
    + r")\s+(?P<gap>"
    + _COUNT_GAP
    + r")(?:(?:are|is|were|was|still|now|also|currently)\s+){0,6}(?:fail(?:ed|s|ing)?"
    r"|failures?)\b(?!\s+to\b)",
    _I,
)
#: A failure count after a label: "Failures: 0", "Tests failing now: 0", "Failed: 2".
_LABELED_FAILURES = re.compile(
    r"\b(?:(?:tests?|specs?)\s+)?(?:failing(?:\s+tests?)?|failed(?:\s+tests?)?|failures?)"
    r"(?:\s+(?:now|remaining|left|still))?\s*[:=]\s*(?P<n>\d+|none|zero)\b(?!\s*/|\.\d)",
    _I,
)
_TOTALS = (
    re.compile(r"(?<![\w.])(?P<n>\d+)\s+total\b", _I),
    re.compile(
        r"\bran\s+(?:all\s+)?(?P<n>" + _NUM + r")\s+(?:(?:[a-z][\w-]*)\s+)?" + _TEST_NOUN + r"\b",
        _I,
    ),
    re.compile(
        _NOT_REFERENCE
        + r"(?P<n>"
        + _NUM
        + r")\s+(?:(?:[a-z][\w-]*)\s+)?"
        + _TEST_NOUN
        + r"\s+(?:ran|run|executed|collected)\b",
        _I,
    ),
)
_TOTAL_NO_FAILURES = re.compile(
    _NOT_REFERENCE
    + r"(?P<n>"
    + _NUM
    + r")\s+(?:(?:[a-z][\w-]*)\s+)?"
    + _TEST_NOUN
    + r"\s*[,;:(]?\s*(?:with\s+)?(?:0|zero|no)\s+(?:failures|failed)\b",
    _I,
)
_NO_FAILURES = re.compile(
    r"\b(?:no|zero|0)\s+(?:test\s+)?(?:failures|failed|failing\s+tests)\b", _I
)
#: Words that date a statement to before the agent's work ("3 tests failed before my
#: change", "Initially mypy reported 4 errors", "failed until I added the stub").
#: "previously failing tests" is an adjective, not a date.
_HISTORICAL = re.compile(
    r"\b(?:initially|originally|previously(?![- ](?:failing|failed|broken|flaky|skipped|red"
    r"|passing)\s+(?:tests?|specs?|cases?|suites?|checks?))|before\s+(?:my|the|this|i|we|that"
    r"|these|any)\b|at\s+first|at\s+the\s+(?:start|beginning)|earlier|used\s+to|prior\s+to"
    r"|beforehand|on\s+the\s+first\s+(?:run|try|attempt|pass)|the\s+first\s+time"
    r"|(?:were|was)\s+failing\s+before|until\s+(?:i|we)\s+(?:had\s+|have\s+|finally\s+)?"
    r"(?:\w+ed|wrote|made|set|put|ran|reran|re-ran|got|found|took|built|rebuilt|undid|split))\b",
    _I,
)
#: A failure in the past tense; only such a failure can be undone by a later clause.
_PAST_FAILURE = re.compile(
    r"\b(?:failed|(?:was|were)\s+(?:still\s+)?(?:failing|broken|red|erroring)|broke|errored"
    r"|crashed|timed\s+out|found|reported|flagged|showed|gave|had|complained|returned|produced"
    r"|listed|exited)\b",
    _I,
)
#: A later clause saying the thing now succeeds: "then passed on retry", "it passes now",
#: "now it's clean", "after adding annotations it passes", "which I fixed". Its subject
#: is a pronoun or nothing, so "now the build passes" does not undo a test failure.
_LATER_SUCCESS = re.compile(
    r"\b(?:then|now|later|eventually|finally|afterwards|after\s+that|since\s+then)\s+"
    r"(?:(?:it|they|both|all(?:\s+of\s+them)?|everything)\s+)?(?:(?:all|also|again|now)\s+)?"
    r"(?:pass(?:es|ed|ing)?|succeed(?:s|ed)?|builds?|built|compiles?|compiled|works?|worked"
    r"|(?:is|are|was|were|comes?\s+back|came\s+back)\s+(?:all\s+)?(?:clean|green|passing|fine"
    r"|happy))\b"
    r"|\bnow\s+(?:it|they|everything)(?:'s|'re|\s+is|\s+are)\s+(?:all\s+)?(?:clean|green"
    r"|passing|fine)\b"
    r"|\b(?:it|they|both|everything|all\s+of\s+them)(?:'s|'re|\s+is|\s+are)?\s+(?:(?:all|also"
    r"|now)\s+)?(?:pass(?:es)?|succeeds?|builds?|compiles?|works?|clean|green|passing|fine)\s+"
    r"(?:now|again)\b"
    r"|\bpass(?:es|ed)?\s+on\s+(?:a\s+|the\s+)?(?:retry|re-?run|second\s+(?:try|attempt|run))\b"
    r"|\bafter\s+[^.;]{1,80}?\b(?:it|they|everything|both)\s+(?:now\s+)?(?:all\s+)?"
    r"(?:pass(?:es)?|succeeds?|builds?|compiles?|works?|(?:is|are)\s+(?:clean|green))\b"
    r"|\b(?:which|that)\s+(?:i|we)\s+(?:then\s+|have\s+|also\s+|since\s+)?(?:fixed|resolved"
    r"|addressed|corrected)\b"
    r"|\b(?:i|we)\s+(?:then\s+|also\s+)?(?:fixed|resolved|addressed)\s+(?:them|those|these|it"
    r"|both|all\s+of\s+them)\b",
    _I,
)
#: A pass in the past tense, which a dating word turns into history ("Before my change
#: all tests passed").
_PAST_PASS = re.compile(
    r"\b(?:passed|succeeded|built|compiled|(?:was|were)\s+(?:all\s+)?(?:passing|green|clean"
    r"|happy|ok)|came\s+back\s+(?:green|clean))\b",
    _I,
)
_NOW = re.compile(r"\bnow\b", _I)
#: Dating words for a pass. "On the first run" dates a failure ("2 tests failed on the
#: first run") but not a pass ("all tests passed the first time" still holds).
_FIRST_TRY = re.compile(
    r"\b(?:on\s+the\s+first\s+(?:run|try|attempt|pass)|the\s+first\s+time)\b", _I
)


def _is_history(v: _View, span: Span, negated: bool) -> bool:
    """True when the status claim at ``span`` is about an earlier state, not the final one.

    A failure is history when the unit dates it ("Initially", "before my change", "at
    first", "until I added ...") or, for a failure in the past tense, when a later
    clause of the same sentence says it now succeeds ("`test_x` was failing; it passes
    now", "failed once, then passed on retry"). A pass is history when it is in the
    past tense in a dated unit with no "now" ("Before my change, all tests passed").
    """
    stated = v.prose[span[0] : span[1]]
    dated = bool(_HISTORICAL.search(v.prose))
    if not negated:
        dated = bool(_HISTORICAL.search(_FIRST_TRY.sub(" ", v.prose)))
        return dated and bool(_PAST_PASS.search(stated)) and not _NOW.search(v.prose)
    if dated:
        return True
    if not _PAST_FAILURE.search(stated):
        return False
    later = v.prose[span[1] :] + " " + mask_markdown(v.unit.rest, blank_code=True)
    return bool(_LATER_SUCCESS.search(later))


_SCOPE_WORDS = (
    "unit",
    "integration",
    "e2e",
    "end-to-end",
    "new",
    "existing",
    "regression",
    "smoke",
    "frontend",
    "backend",
)


def _scope_of(phrase: str, *, allow_all: bool = True) -> str | None:
    words = re.findall(r"[\w-]+", phrase.lower())
    if allow_all and "all" in words:
        return "all"
    for word in _SCOPE_WORDS:
        if word in words:
            return word
    return None


def _about_tests(v: _View) -> bool:
    """True when a bare count ("12 passed", "3 failed") in ``v`` can only count tests.

    The unit, its section, or the unit before it names tests, or the unit cites a
    command ("Ran `make check`: 12 passed").
    """
    if _MENTIONS_TESTS.search(v.prose) or _TESTING_CONTEXT.search(v.context):
        return True
    if any(command_param(v.content(span)) is not None for span in v.codes):
        return True
    return bool(_MENTIONS_TESTS.search(v.unit.previous))


def _test_numbers(v: _View) -> list[_Candidate]:
    numbers: dict[str, int] = {}
    anchors: list[Span] = []

    def put(key: str, value: int | None, span: Span) -> None:
        if value is not None and key not in numbers:
            numbers[key] = value
            anchors.append(span)

    taken: list[Span] = []

    def free(span: Span) -> bool:
        return not any(_overlaps(span, other) for other in taken)

    for match in _ALL_N.finditer(v.prose):
        value = _number(match.group("n"))
        put("passed", value, match.span())
        put("total", value, match.span())
        taken.append(match.span())
    for match in _N_ALL.finditer(v.prose):
        if free(match.span()):
            value = _number(match.group("n"))
            put("passed", value, match.span())
            put("total", value, match.span())
            taken.append(match.span())
    for match in [*_FRACTION.finditer(v.prose), *_FRACTION_LEAD.finditer(v.prose)]:
        if not free(match.span()):
            continue
        groups = match.groupdict()
        plain = "noun" in groups  # _FRACTION; _FRACTION_LEAD has a pass word or label
        fails = plain and not groups.get("verb") and _FAIL_AFTER.match(v.prose, match.end())
        unlabeled = plain and not (groups.get("noun") or groups.get("verb"))
        if unlabeled and not (fails and _about_tests(v)):
            continue  # "3/10" alone; "Tests: 3/10 failing" counts failures
        if fails:
            put("failed", int(match.group("p")), match.span())  # "3 of 10 tests fail"
        else:
            put("passed", int(match.group("p")), match.span())
        put("total", int(match.group("t")), match.span())
        taken.append(match.span())
    for match in _TOTAL_NO_FAILURES.finditer(v.prose):
        if free(match.span()):
            put("total", _number(match.group("n")), match.span())
            put("failed", 0, match.span())
            taken.append(match.span())
    for regex in _TOTALS:
        for match in regex.finditer(v.prose):
            if free(match.span()):
                put("total", _number(match.group("n")), match.span())
                taken.append(match.span())
    for match in _LABELED_FAILURES.finditer(v.prose):
        if free(match.span()):
            put("failed", _number(match.group("n")) or 0, match.span())
            taken.append(match.span())
    bare: list[tuple[str, re.Match[str]]] = []
    for key, regex in (("passed", _N_PASSED), ("failed", _N_FAILED)):
        for match in regex.finditer(v.prose):
            if not free(match.span()):
                continue
            if match.group("gap").strip():  # "12 tests passed": a test noun says what counts
                put(key, _number(match.group("n")), match.span())
                taken.append(match.span())
            else:
                bare.append((key, match))
    # "39 passed, 3 failed" is a test summary by its shape; a lone "12 passed" or
    # "1970 fail" counts tests only when the unit or its section is about tests.
    if bare and (numbers or len({key for key, _ in bare}) > 1 or _about_tests(v)):
        for key, match in bare:
            put(key, _number(match.group("n")), match.span())
            taken.append(match.span())
    if not numbers:
        return []
    if ("passed" in numbers or "total" in numbers) and "failed" not in numbers:
        none = _NO_FAILURES.search(v.prose)
        if none is not None and free(none.span()):
            put("failed", 0, none.span())
    anchor = (min(a for a, _ in anchors), max(b for _, b in anchors))
    whole = (0, len(v.text))
    if _is_history(v, anchor, negated=bool(numbers.get("failed"))):
        # "3 tests failed before the fix", "Before my change: 40 passed, 2 failed": not
        # about the final state. Reserve the unit so no other test rule reads it.
        hit = PatternHit(ClaimType.TESTS_PASS, {}, True, anchor)
        return [_Candidate(hit, _RESERVE_ONLY, frozenset({"tests"}), whole)]
    if "passed" in numbers or "total" in numbers or numbers.get("failed") == 0:
        keys = ("passed", "total", "failed")
        params: Params = {key: numbers[key] for key in keys if key in numbers}
        hit = PatternHit(ClaimType.TEST_COUNT, params, False, anchor)
        return [_Candidate(hit, "tests", frozenset({"tests"}), whole)]
    scope = _scope_of(v.prose[anchor[0] : anchor[1]]) or _scope_of(
        v.prose[: anchor[0]], allow_all=False
    )
    params = {"scope": scope} if scope else {}
    hit = PatternHit(ClaimType.TESTS_PASS, params, True, anchor)
    return [_Candidate(hit, "tests", frozenset({"tests"}), whole)]


#: Premodifiers of a test noun. Every alternative is one word or a phrase none of whose
#: prefixes is another alternative ("all the" is "all" then "the"), so a run of them
#: matches in one way only.
_PREMOD = (
    r"(?:(?:the|all|all\s+of\s+the|our|my|its|their|existing|new|added|remaining|other"
    r"|full|whole|entire|unit|integration|e2e|end-to-end|python|typescript|js|ts|relevant"
    r"|related|affected|both|previously[- ]failing|failing|original|old|local|updated|modified"
    r"|regression|smoke|focused|targeted|frontend|backend|api|cli|parser|core|these|those)\s+){0,6}"
)
_TNOUN = r"(?:test\s+suites?|test-suites?|testsuites?|suites?|tests?|specs?|test\s+cases?)"
_LOCATION = r"(?P<loc>\s+(?:in|for|under|of)\s+(?:`C+`|[\w./\-]+))?"
_PASS_WORD = r"(?:pass(?:es|ed|ing)?|succeed(?:s|ed|ing)?|green)"
_FAIL_WORD = (
    r"(?:fail(?:s|ed|ing)?|broken|red|erroring|error(?:s|ed)?|crash(?:es|ed|ing)?|time\s+out"
    r"|timing\s+out|timed\s+out)"
)
_HEDGE_BEFORE = re.compile(
    r"\b(?:should|would|will|might|may|can|could|must|need|needs|needed|expect|expected"
    r"|supposed|if|unless|until|whether|make|makes|making|get|getting|ensure|ensures|ensuring"
    r"|want|wanted|hope|try|trying|once|when)\s+(?:\w+\s+){0,3}$",
    _I,
)
_TESTS_POSITIVE = re.compile(
    r"\b(?P<subj>"
    + _PREMOD
    + _TNOUN
    + r")"
    + _LOCATION
    + r"\s+(?:(?:are|is|were|was|have|has|now|all|still|also|both|again|fully|consistently"
    r"|cleanly|successfully|then|back\s+to)\s+){0,6}(?P<status>" + _PASS_WORD + r")\b"
    # "pass" with an object is not a test outcome: "the tests pass an empty list". A time
    # phrase is no object: "all tests passed the first time".
    r"(?!\s+(?:through|to|if|unless|only\s+when|when(?!\s+(?:re-?)?run(?:ning)?\b))\b"
    r"|\s+(?:a|an|the|this|that|these|those|its|their|our|my|your|some|any|each|every|no)\b"
    r"(?!\s+(?:(?:first|second|third|last|next|whole|entire)\s+)?(?:time|try|attempt|run|round"
    r"|way)\b)|\s+[`\"'])",
    _I,
)
_TESTS_STATE = re.compile(
    r"\b(?P<subj>(?:the\s+)?(?:test\s+suite|tests|suite|test\s+run))\s+(?:is|are|was|were)\s+"
    r"(?:(?:now|all|fully|back|still)\s+){0,6}(?:clean|happy|ok|passing|green)\b",
    _I,
)
_EVERYTHING_PASSES = re.compile(
    r"\b(?:everything|all)\s+(?:(?:is|still|now|else)\s+){0,6}(?:pass(?:es|ing)?|green)\b", _I
)
_NO_FAILURES_PHRASE = re.compile(
    r"\b(?:with\s+)?no\s+(?:test\s+)?failures\b|\bnothing\s+(?:is\s+)?fail(?:s|ing)\b", _I
)
_RUNNER_PASSES = re.compile(
    r"(?P<cmd>`C+`|\b(?:pytest|py\.test|jest|vitest|mocha|ava|tox|nox|unittest|npm\s+test"
    r"|npm\s+run\s+test|yarn\s+test|pnpm\s+test|bun\s+test|go\s+test|cargo\s+test|make\s+test"
    r"|run_tests(?:\(\))?)\b)\s+(?:(?:now|also|still|again|then|all|fully|cleanly)\s+){0,6}"
    r"(?P<status>pass(?:es|ed)?|succeeds?|succeeded|is\s+green|comes\s+back\s+green"
    r"|reports?\s+(?:all\s+(?:tests\s+)?passing|no\s+failures)|runs?\s+(?:green|clean(?:ly)?)"
    r"|exits?\s+(?:0|cleanly|successfully|with\s+(?:code\s+)?0)|is\s+(?:clean|happy|passing)"
    r"|(?:still\s+)?fails|failed|reports?\s+(?:\w+\s+)?failures?|is\s+red"
    r"|exits?\s+(?:1|non-?zero|with\s+(?:code\s+)?[1-9]))\b",
    _I,
)
_TESTS_NO_LONGER_FAIL = re.compile(
    r"\b(?P<subj>" + _PREMOD + _TNOUN + r")\s+(?:now\s+)?no\s+longer\s+fail(?:s)?\b", _I
)
_TESTS_NEGATIVE = re.compile(
    r"\b(?P<subj>"
    + _PREMOD
    + _TNOUN
    + r")"
    + _LOCATION
    + r"\s+(?:(?:are|is|were|was|still|now|also|currently|consistently|all|both)\s+){0,6}"
    r"(?P<status>" + _FAIL_WORD + r")\b",
    _I,
)
_TESTS_NOT_PASSING = re.compile(
    r"\b(?P<subj>" + _PREMOD + _TNOUN + r")\s+(?:still\s+)?(?P<aux>do(?:es)?\s*n[o']?t"
    r"|do(?:es)?\s+not|are\s*n[o']?t|is\s*n[o']?t|are\s+not|is\s+not|won'?t|will\s+not"
    r"|no\s+longer|never|did\s*n[o']?t|did\s+not|were\s*n[o']?t|was\s*n[o']?t|were\s+not"
    r"|was\s+not)\s+"
    r"(?:(?:yet|all|fully|currently|quite|reliably|consistently|even)\s+){0,6}"
    r"(?P<status>pass(?:es|ing)?|green|succeed(?:ing)?|run(?:ning)?)\b",
    _I,
)
_BE_AUX = re.compile(r"(?:was|were|is|are)\b|(?:was|were|is|are)n", _I)
_NONE_BEFORE = re.compile(
    r"\b(?:no|none\s+of(?:\s+the)?|zero|not\s+(?:a\s+single|one|any)(?:\s+of(?:\s+the)?)?"
    r"|without\s+any)\s*$",
    _I,
)
_EXCEPT_AFTER = re.compile(
    r"\s*,?\s*(?:except|but\s+for|apart\s+from|other\s+than|save\s+for|besides|excluding)\b",
    _I,
)
_NOT_ALL_PASS = re.compile(
    r"\bnot\s+all\s+(?:of\s+the\s+)?(?:[\w-]+\s+)?"
    + _TNOUN
    + r"\s+(?:pass|are\s+passing|passed|succeed)",
    _I,
)
_SOME_FAIL = re.compile(
    r"\b(?:some|several|a\s+few|few|many|a\s+couple\s+of|a\s+handful\s+of|multiple|a)\s+"
    r"(?:(?:[a-z][\w-]*)\s+)?" + _TNOUN + r"\s+(?:(?:are|is|still|now|also|currently)\s+){0,6}"
    r"(?:fail(?:s|ed|ing)?|broken|erroring)\b",
    _I,
)
_FAILURES_REMAIN = re.compile(
    r"\b(?:there\s+(?:is|are|was|were)\s+)?(?:still\s+)?(?:some|several|a\s+few|a\s+couple\s+of"
    r"|remaining|pre-?existing|known|unrelated|flaky)\s+(?:test\s+)?failures?\b"
    r"|\b(?:test\s+)?failures?\s+(?:remain|persist|are\s+left)\b"
    r"|\bthere\s+(?:is|are)\s+(?:still\s+)?(?:a|one|some|several|a\s+few)\s+(?:failing|broken"
    r"|red)\s+tests?\b",
    _I,
)
_ALL_EXCEPT = re.compile(
    r"\b(?:all|every)\s+(?:of\s+the\s+)?(?:[\w-]+\s+)?"
    + _TNOUN
    + r"\s+(?:now\s+)?(?:pass(?:es)?|are\s+passing|passed)\s+(?:except|but|apart\s+from"
    r"|other\s+than|save\s+for|besides)\b|\ball\s+but\s+(?:\w+\s+){0,2}?" + _TNOUN,
    _I,
)
_TEST_NAME_STATUS = re.compile(
    r"(?P<name>`C+`|\btest_\w+)\s+(?:(?:is|are|was|still|now|also|currently|all)\s+){0,6}"
    r"(?:(?P<fail>fail(?:s|ed|ing)?|broken|erroring|errors)|(?P<pass>pass(?:es|ed)?|is\s+passing"
    r"|succeeds?))\b",
    _I,
)
#: "..., and they pass": a pronoun with a test status. Its antecedent is checked in code
#: (:func:`_anaphora`), so "I rewrote `deploy.sh`, and it succeeds now" is not a test.
_PRONOUN_STATUS = re.compile(
    r"(?:\band\b|,|;)\s+(?P<pron>(?:they|it|both|all\s+of\s+them|all|everything)\s+"
    r"(?:(?:now|all|still|also|both|again)\s+){0,6}"
    r"(?:(?P<pos>pass(?:es|ed|ing)?|succeed(?:s|ed)?|are\s+(?:passing|green)|is\s+(?:passing"
    r"|green)|green)|(?P<neg>fail(?:s|ed|ing)?|are\s+(?:still\s+)?failing|(?:do|does|did)\s*n[o']?t"
    r"\s+pass|(?:do|does|did)\s+not\s+pass|are\s*n[o']?t\s+passing|are\s+not\s+passing)))\b",
    _I,
)
_ANTECEDENT = re.compile(
    r"\btests?\b|\bsuites?\b|\bspecs?\b|\bpytest\b|\bjest\b|\bvitest\b|\bmocha\b|`C+`", _I
)


def _anaphora(v: _View) -> tuple[bool, Span] | None:
    """A pronoun test status and its anchor: "Ran `pytest` and it passes" gives (False, ...).

    The antecedent is the nearest test word or inline code before the pronoun, in the
    same sentence and at most 200 characters back. Inline code counts only when it is a
    test command or a test name; a plural pronoun ("they") skips other code to reach an
    earlier test word ("Ran the tests on `src/` and they pass"). Returns (negated,
    anchor) or None.
    """
    for match in _PRONOUN_STATUS.finditer(v.prose):
        start = match.start()
        window = max(v.prose.rfind(".", 0, start) + 1, start - 200)
        plural = not match.group("pron").lower().startswith(("it", "everything"))
        for ante in reversed(list(_ANTECEDENT.finditer(v.prose, window, start))):
            if not ante.group(0).startswith("`"):
                return match.group("neg") is not None, (match.start("pron"), match.end())
            span = v.code_at(ante.start())
            command = command_param(v.content(span)) if span is not None else None
            if (command is not None and "test" in command_kinds(command)) or _test_name_ok(
                v, ante.start()
            ):
                return match.group("neg") is not None, (match.start("pron"), match.end())
            if not plural:
                break
    return None


_PREVIOUS_ANAPHORA = re.compile(
    r"^\W*(?:they|it|both|all\s+of\s+them)\s+(?:(?:now|all|still|also|both|again)\s+){0,6}"
    r"(?:(?P<pos>pass(?:es|ed|ing)?|succeed(?:s|ed)?|are\s+(?:passing|green))"
    r"|(?P<neg>fail(?:s|ed|ing)?|are\s+(?:still\s+)?failing|do\s*n[o']?t\s+pass"
    r"|do\s+not\s+pass))\b",
    _I,
)
_MENTIONS_TESTS = re.compile(r"\b(?:tests?|suite|specs?|pytest|jest|vitest|mocha|run_tests)\b", _I)


def _test_name_ok(v: _View, start: int) -> str | None:
    span = v.code_at(start)
    if span is None:
        name = re.match(r"test_\w+", v.text[start:])
        return name.group(0) if name else None
    content = v.content(span)
    if re.match(r"^(?:[\w/.\-]+::)?test\w*(?:\[[^\]]*\])?$", content) or re.match(
        r"^[\w/.\-]+\.(?:test|spec)\.[cm]?[jt]sx?$", content
    ):
        return content
    return None


def _tests_pass(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []

    def add(negated: bool, span: Span, scope: str | None = None) -> None:
        if _is_history(v, span, negated):
            return  # "3 tests failed before my change", "`test_x` was failing; it passes now"
        params: Params = {"scope": scope} if scope else {}
        hit = PatternHit(ClaimType.TESTS_PASS, params, negated, span)
        out.append(_Candidate(hit, "tests", frozenset({"tests"}), span))

    def hedged(start: int) -> bool:
        return bool(_HEDGE_BEFORE.search(v.prose[:start]))

    for match in _ALL_EXCEPT.finditer(v.prose):
        add(True, match.span(), None)
    for match in _NOT_ALL_PASS.finditer(v.prose):
        add(True, match.span(), None)
    for regex in (_SOME_FAIL, _FAILURES_REMAIN):
        if regex is _FAILURES_REMAIN and v.unit.label:
            continue  # "## Known failures" names a section; its items say what fails
        for match in regex.finditer(v.prose):
            add(True, match.span(), _scope_of(match.group(0)))
    for match in _TESTS_NOT_PASSING.finditer(v.prose):
        passive = match.group("status").lower() == "run" and _BE_AUX.match(match.group("aux"))
        if passive or hedged(match.start()):
            continue  # "the suite was not run" is about the agent, not test outcomes
        add(True, match.span(), _scope_of(match.group("subj")))
    for match in _TESTS_NEGATIVE.finditer(v.prose):
        if hedged(match.start()):
            continue
        scope = _location_scope(v, match) or _scope_of(match.group("subj"))
        # "None of the tests fail" and "No tests fail" say the tests pass.
        add(not _NONE_BEFORE.search(v.prose[: match.start()]), match.span(), scope)
    for match in _TESTS_NO_LONGER_FAIL.finditer(v.prose):
        add(False, match.span(), _scope_of(match.group("subj")))
    for match in _TESTS_POSITIVE.finditer(v.prose):
        if not hedged(match.start()):
            scope = _location_scope(v, match) or _scope_of(match.group("subj"))
            # "The suite passes except for `test_x`" admits a failure.
            add(bool(_EXCEPT_AFTER.match(v.prose, match.end())), match.span(), scope)
    for match in _TESTS_STATE.finditer(v.prose):
        if not hedged(match.start()):
            add(False, match.span(), _scope_of(match.group("subj")))
    for match in _RUNNER_PASSES.finditer(v.prose):
        cmd = match.group("cmd")
        if cmd.startswith("`"):
            span = v.code_at(match.start("cmd"))
            command = command_param(v.content(span)) if span else None
            if command is None or "test" not in command_kinds(command):
                continue
        status = match.group("status").lower()
        add(bool(re.search(r"fail|red|non-?zero|[1-9]", status)), match.span(), None)
    for match in _TEST_NAME_STATUS.finditer(v.prose):
        name = _test_name_ok(v, match.start("name"))
        if name is not None:
            add(bool(match.group("fail")), match.span(), name)
    for regex in (_EVERYTHING_PASSES, _NO_FAILURES_PHRASE):
        for match in regex.finditer(v.prose):
            if not hedged(match.start()):
                add(False, match.span(), None)
    anaphora = _anaphora(v)
    if anaphora is not None:  # anchored at "they pass", which no description reserves
        add(anaphora[0], anaphora[1], None)
    previous = _PREVIOUS_ANAPHORA.match(v.prose)
    if previous is not None and _MENTIONS_TESTS.search(v.unit.previous):
        add(previous.group("neg") is not None, previous.span(), None)
    return _first_per_span(out)


def _location_scope(v: _View, match: re.Match[str]) -> str | None:
    """The place a test status is about: "tests in `tests/test_io.py`" gives the path."""
    if not match.group("loc"):
        return None
    # The location group is " in <target>": a preposition, then one word or code span.
    target = v.text[match.start("loc") : match.end("loc")].split(None, 1)[-1].strip("`")
    return path_param(target) or target


def _first_per_span(candidates: list[_Candidate]) -> list[_Candidate]:
    """Drop candidates whose anchor overlaps an earlier candidate's anchor."""
    kept: list[_Candidate] = []
    for candidate in candidates:
        if not any(_overlaps(candidate.hit.anchor, k.hit.anchor) for k in kept):
            kept.append(candidate)
    return kept


_LINT_TOOL = (
    r"(?:ruff(?:\s+check)?|flake8|pylint|eslint|biome(?:\s+(?:check|lint))?|oxlint|pycodestyle"
    r"|pyflakes|stylelint)"
)
_LINT_GENERIC = (
    r"(?:(?:the\s+)?(?:linters?|linting|lint\s+checks?|lint|style\s+checks?|code\s+style))"
)
_TYPE_TOOL = (
    r"(?:mypy(?:\s+--strict)?|pyright|basedpyright|pytype|pyre|tsc(?:\s+--noEmit)?|vue-tsc)"
)
_TYPE_GENERIC = (
    r"(?:(?:the\s+)?(?:type\s*checkers?|type[- ]?check(?:s|ing)?|typecheck(?:s|ing)?|type\s+checks?"
    r"|static\s+typing|types|typing))"
)
_STATUS_GAP = (
    r"\s*(?:\((?P<paren>[^)]*)\)\s*)?(?:[:|→]|->|=>|-)?\s*(?:(?:is|are|was|were|reports?"
    r"|reported|shows?|showed|returns?|returned|gives|gave|comes?\s+back|came\s+back|runs?|ran"
    r"|now|also|still|completely|fully|all|both|again|with|and|says|said)\s+){0,6}"
)
_CLEAN = (
    r"(?:clean(?:ly)?|pass(?:es|ed|ing)?|green|happy|ok(?:ay)?|succeed(?:s|ed)?"
    r"|success(?:ful(?:ly)?)?|no\s+(?:issues|errors|problems|findings|violations|complaints"
    r"|warnings|diagnostics|type\s+errors|lint\s+errors)(?:\s+found)?|0\s+(?:issues|errors"
    r"|problems|violations)|zero\s+(?:issues|errors|problems|violations)|without\s+(?:any\s+)?"
    r"(?:issues|errors|problems|warnings|complaints|type\s+errors)|all\s+checks\s+passed"
    r"|nothing\s+to\s+(?:fix|report)|✅|✔|✓"
    r"|exit(?:s|ed)?\s+(?:with\s+)?(?:(?:code|status)\s+)?0\b|exit(?:s|ed)?\s+cleanly"
    r"|returned\s+0\b)"
)
_REPORTS_ERRORS = (
    r"(?:(?:still\s+)?(?:reports?|reported|shows?|showed|flags?|flagged|finds?|found"
    r"|complains?\s+about|complained\s+about|gives|gave|has|had|returns?|returned|produces?"
    r"|produced|lists?|listed)\s+)?(?P<n>\d+|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|some|several|a\s+few|many|multiple|a\s+couple\s+of)\s+(?:(?:\w+)\s+){0,2}?"
)
_FAILS = (
    r"(?:still\s+)?(?:fails|failed|is\s+failing|complains|is\s+not\s+clean|isn't\s+clean"
    r"|is\s+red)\b"
)


def _static_rules(
    tools: str, generic: str, nouns: str, kind: str
) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    subject = r"(?P<tool>`C+`|\b(?:" + tools + r"|" + generic + r"))"
    positive = re.compile(subject + _STATUS_GAP + r"(?P<status>" + _CLEAN + r")", _I)
    negative = re.compile(
        subject + _STATUS_GAP + r"(?:" + _REPORTS_ERRORS + nouns + r"|" + _FAILS + r")",
        _I,
    )
    counted = re.compile(
        r"\b(?P<n>\d+|one|two|three|some|several|a\s+few|many)\s+(?:remaining\s+|new\s+"
        r"|pre-?existing\s+)?(?P<tool>" + kind + r")\s+(?:errors|issues|violations|findings"
        r"|problems)\b|\b(?P<tool2>" + kind + r")\s+(?:errors|issues|violations)\s+"
        r"(?:remain|persist)\b",
        _I,
    )
    return positive, negative, counted


_LINT_RULES = _static_rules(
    _LINT_TOOL,
    _LINT_GENERIC,
    r"(?:issues|errors|problems|findings|violations|lint\s+errors)",
    r"lint|linting|ruff|flake8|eslint|pylint|style",
)
_TYPE_RULES = _static_rules(
    _TYPE_TOOL,
    _TYPE_GENERIC,
    r"(?:type\s+errors|errors|issues|problems)",
    r"type|typing|mypy|pyright|tsc",
)
_LINT_EXTRA = re.compile(
    r"\bno\s+(?P<tool>lint|linting|ruff|flake8|eslint|pylint|style)\s+(?:issues|errors|warnings"
    r"|violations|findings|problems)\b|\blint[- ]clean\b",
    _I,
)
_TYPE_EXTRA = re.compile(
    r"\bno\s+(?P<tool>type|typing|mypy|pyright|tsc)\s+(?:errors|issues|problems)\b"
    r"|(?P<tool2>`C+`|\btsc)(?:\s+--noEmit)?\s+(?:now\s+)?compiles?\s+(?:cleanly"
    r"|without\s+(?:any\s+)?errors|successfully)\b|\bsuccess:\s*no\s+issues\s+found\b",
    _I,
)


def _program_of(command: str) -> str | None:
    """The program a command runs, or None when it runs through a package manager script."""
    segments = _segments(command)
    program = segments[0][0] if segments else ""
    return program if program and program not in _PACKAGE_MANAGERS else None


_PAREN_AFTER = re.compile(r"\s*\((?P<inner>[^)]*)\)")


def _tool_param(v: _View, match: re.Match[str], kind: str) -> str | None:
    """The tool a static-check claim names: a program name, or None for generic words."""
    for group in ("tool", "tool2"):
        if group not in match.groupdict() or match.group(group) is None:
            continue
        start = match.start(group)
        span = v.code_at(start)
        if span is not None:
            command = command_param(v.content(span))
            if command is None or kind not in command_kinds(command):
                return "\0"
            return _program_of(command)
        word = v.text[start : match.end(group)].lower().split()[0].strip("`")
        if word in (
            "ruff",
            "flake8",
            "pylint",
            "eslint",
            "biome",
            "oxlint",
            "pycodestyle",
            "pyflakes",
            "stylelint",
            "mypy",
            "pyright",
            "basedpyright",
            "pytype",
            "pyre",
            "tsc",
            "vue-tsc",
        ):
            return word
        return None
    return None


def _static(
    v: _View,
    rules: tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]],
    extra: re.Pattern[str],
    claim_type: ClaimType,
    kind: str,
    family: str,
) -> list[_Candidate]:
    positive, negative, counted = rules
    out: list[_Candidate] = []

    def add(negated: bool, match: re.Match[str]) -> None:
        if _HEDGE_BEFORE.search(v.prose[: match.start()]) or _is_history(v, match.span(), negated):
            return  # "if mypy passes", "Initially mypy failed with 4 errors"
        tool = _tool_param(v, match, kind)
        if tool == "\0":
            return
        if tool is None:
            # A generic subject with the command in parentheses: "Type checking passes
            # (`mypy --strict src`)" or "Lint (`ruff check .`): clean".
            inner: Span | None = None
            if match.groupdict().get("paren") is not None:
                inner = match.span("paren")
            else:
                after = _PAREN_AFTER.match(v.prose, match.end())
                inner = after.span("inner") if after is not None else None
            cited = _cited_command(v, inner[0], inner[1], kind) if inner else None
            tool = _program_of(cited) if cited is not None else None
        params: Params = {"tool": tool} if tool else {}
        hit = PatternHit(claim_type, params, negated, match.span())
        out.append(_Candidate(hit, family, frozenset(), match.span()))

    for match in negative.finditer(v.prose):
        number = match.groupdict().get("n")
        if number is not None and _number(number) == 0:
            add(False, match)
        else:
            add(True, match)
    for match in counted.finditer(v.prose):
        add(True, match)
    for match in positive.finditer(_clean_output_prose(v)):
        add(False, match)
    for match in extra.finditer(v.prose):
        add(False, match)
    return _first_per_span(out)


def _lint(v: _View) -> list[_Candidate]:
    return _static(v, _LINT_RULES, _LINT_EXTRA, ClaimType.LINT_CLEAN, "lint", "lint")


def _typecheck(v: _View) -> list[_Candidate]:
    return _static(v, _TYPE_RULES, _TYPE_EXTRA, ClaimType.TYPECHECK_CLEAN, "typecheck", "typecheck")


_BUILD_COMMANDS = (
    r"(?:npm\s+run\s+build|yarn\s+build|yarn\s+run\s+build|pnpm\s+(?:run\s+)?build"
    r"|bun\s+run\s+build|make\s+build|python3?\s+-m\s+build|uv\s+build|vite\s+build|next\s+build"
    r"|cargo\s+build|go\s+build|hatch\s+build|poetry\s+build|webpack)"
)
_BUILD_OK = (
    r"(?:succeeds|succeeded|passes|passed|works|completes|completed|is\s+green|is\s+clean"
    r"|is\s+successful|was\s+successful|runs?\s+clean(?:ly)?|goes\s+through|went\s+through"
    r"|finishes|finished|is\s+passing|exits?\s+(?:0|cleanly|successfully|with\s+(?:code\s+)?0)"
    r"|✅)"
)
_BUILD_BAD = (
    r"(?:fails|failed|is\s+failing|is\s+broken|breaks|broke|errors(?:\s+out)?|errored"
    r"|exits?\s+(?:1|non-?zero|with\s+(?:code\s+)?[1-9]))"
)
_BUILD_SUBJECT = (
    r"(?:(?:the\s+)?(?:(?:production|project|package|docs|typescript|ts|frontend|python|wheel)\s+)?"
    r"build(?:\s+step)?)"
)
_BUILD = re.compile(
    r"(?P<subj>\b" + _BUILD_SUBJECT + r"|(?P<cmd>`C+`|\b" + _BUILD_COMMANDS + r"))"
    r"(?:\s*\((?P<paren>[^)]*)\))?"
    r"\s*(?::|→|->)?\s*(?:(?:now|also|still|again)\s+){0,6}(?:(?P<ok>"
    + _BUILD_OK
    + r")|(?P<bad>"
    + _BUILD_BAD
    + r"))\b",
    _I,
)
_BUILDS_FINE = re.compile(
    r"\b(?:the\s+)?(?:project|package|app|code|library|it|everything)\s+(?:now\s+)?"
    r"(?:builds|compiles|built)\s+(?:cleanly|successfully|fine|without\s+(?:any\s+)?(?:errors"
    r"|warnings|issues))\b|\bbuilt\s+successfully\b",
    _I,
)
_DOES_NOT_BUILD = re.compile(
    r"\b(?:does\s*n[o']?t|does\s+not|won'?t|will\s+not|did\s*n[o']?t|did\s+not)\s+"
    r"(?:build|compile)\b|\bbuild\s+errors?\s+(?:remain|persist)\b",
    _I,
)


def _cited_command(v: _View, start: int, end: int, kind: str) -> str | None:
    """The first command of ``kind`` written as inline code between ``start`` and ``end``."""
    for span in v.codes:
        if start <= span[0] and span[1] <= end:
            command = command_param(v.content(span))
            if command is not None and kind in command_kinds(command):
                return command
    return None


def _build(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []
    for match in _BUILD.finditer(v.prose):
        negated = bool(match.group("bad"))
        if _HEDGE_BEFORE.search(v.prose[: match.start()]) or _is_history(v, match.span(), negated):
            continue  # "once the build passes", "the build failed at first"
        params: Params = {}
        cmd = match.group("cmd")
        if cmd:
            if cmd.startswith("`"):
                span = v.code_at(match.start("cmd"))
                command = command_param(v.content(span)) if span else None
                if command is None or "build" not in command_kinds(command):
                    continue
                params["tool"] = command
            else:
                params["tool"] = " ".join(v.text[match.start("cmd") : match.end("cmd")].split())
        elif match.group("paren") is not None:
            cited = _cited_command(v, match.start("paren"), match.end("paren"), "build")
            if cited is not None:
                params["tool"] = cited
        hit = PatternHit(ClaimType.BUILD_SUCCEEDS, params, negated, match.span())
        out.append(_Candidate(hit, "build", frozenset(), match.span()))
    for regex, negated in ((_BUILDS_FINE, False), (_DOES_NOT_BUILD, True)):
        for match in regex.finditer(v.prose):
            if _HEDGE_BEFORE.search(v.prose[: match.start()]) or _is_history(
                v, match.span(), negated
            ):
                continue
            hit = PatternHit(ClaimType.BUILD_SUCCEEDS, {}, negated, match.span())
            out.append(_Candidate(hit, "build", frozenset(), match.span()))
    return _first_per_span(out)


_PACKAGE = (
    r"(?:`[^`\n]+`|@?[A-Za-z0-9][\w.\-]*(?:/[\w.\-]+)?(?:\[[\w,\- ]+\])?"
    r"(?:\s*(?:===|==|>=|<=|~=|!=|>|<|\^|~|@)\s*v?\d[\w.\-*]*(?:\s*,\s*(?:==|>=|<=|~=|!=|>|<)"
    r"\s*v?\d[\w.\-*]*)*)?)"
)
_PACKAGE_LIST = (
    r"(?P<pkgs>"
    + _PACKAGE
    + r"(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*|\s+plus\s+)"
    + _PACKAGE
    + r")*)"
)
_DEP_NOUN = (
    r"(?:(?:new\s+|runtime\s+|dev(?:elopment)?\s+|test\s+|optional\s+|direct\s+|third-party\s+"
    r"|python\s+|npm\s+|pip\s+|project\s+){0,6}(?:dependency|dependencies|dep|deps|requirements?"
    r"|packages?|librar(?:y|ies)|devDependency|devDependencies))"
)
_MANIFEST = (
    r"(?:`?(?:requirements(?:[-_.][\w.-]+)?\.(?:txt|in)|pyproject\.toml|package\.json|setup\.py"
    r"|setup\.cfg|Pipfile|environment\.ya?ml|Cargo\.toml|go\.mod|constraints\.txt)`?)"
)
_DEP_ADDED_ON = re.compile(
    r"\b(?:added|adds|introduced|introduces|declared)\s+(?:a\s+)?(?:new\s+)?(?:(?:runtime|dev"
    r"(?:elopment)?|test|optional)\s+)?(?:dependency|dep|requirement)\s+on\s+" + _PACKAGE_LIST,
    _I,
)
_DEP_ADDED = re.compile(
    r"\b(?:added|adds|adding|(?<=to\s)add|introduced|introduces|pulled\s+in|brought\s+in"
    r"|installed|declared|listed)\s+"
    + _PACKAGE_LIST
    + r"\s+(?:as\s+(?:a\s+|an\s+)?|to\s+(?:the\s+)?(?:project(?:'s)?\s+)?|in\s+(?:the\s+)?"
    r"|under\s+(?:the\s+)?|into\s+(?:the\s+)?)?(?:" + _DEP_NOUN + r"|" + _MANIFEST + r")",
    _I,
)
_DEP_ADDED_PASSIVE = re.compile(
    r"\b(?P<pkgs>" + _PACKAGE + r")\s+(?:was|is|has\s+been)\s+(?:now\s+)?(?:added|declared)\s+"
    r"(?:as\s+(?:a\s+)?"
    + _DEP_NOUN
    + r"|to\s+(?:the\s+)?(?:"
    + _DEP_NOUN
    + r"|"
    + _MANIFEST
    + r"))",
    _I,
)
#: A manifest named as a label for the change: "updated requirements.txt: added flask-cors".
_MANIFEST_LABEL_ADDED = re.compile(_MANIFEST + r"\s*:\s*(?:added|adds|add)\s+" + _PACKAGE_LIST, _I)
_DEP_CONTEXT = re.compile(
    r"^(?:(?:new\s+)?dependenc(?:y|ies)(?:\s+(?:added|changes))?|(?:new\s+)?packages?"
    r"(?:\s+added)?|deps)$",
    _I,
)
_VERSION = r"(?P<ver>`[^`\n]+`|v?\d[\w.\-*]*|latest|the\s+latest(?:\s+version)?)"
#: A word after the new value that makes it a quantity, not a version ("to 5 seconds").
_NOT_A_VERSION_AFTER = (
    r"(?!\s*(?:%|percent|seconds?|secs?|s\b|ms\b|minutes?|mins?|hours?|days?|retries"
    r"|attempts|workers|threads|processes|items|rows|lines|chars|characters|bytes|kb|mb|gb"
    r"|px|times|x\b))"
)
_DEP_UPDATED = re.compile(
    r"\b(?P<verb>bumped|bumps|upgraded|upgrades|updated|updates|pinned|pins|raised|moved"
    r"|downgraded|downgrades)\s+(?:the\s+)?(?:(?:vendored|pinned|bundled)\s+)?(?P<noun1>"
    + _DEP_NOUN
    + r"\s+)?(?P<pkg>"
    + _PACKAGE
    + r")(?P<noun2>\s+(?:"
    + _DEP_NOUN
    + r"|version|pin|requirement|constraint))?(?P<manifest>\s+(?:in|within)\s+"
    + _MANIFEST
    + r")?"
    r"\s+(?:from\s+(?:version\s+)?`?v?[\w.\-^~<>=*]+`?\s+)?(?:to|->|→)\s+(?:version\s+"
    r"|v(?=\d))?" + _VERSION + _NOT_A_VERSION_AFTER,
    _I,
)
_DEP_UPDATED_NOUN = re.compile(
    r"\b(?P<verb>bumped|upgraded|updated|pinned|downgraded)\s+(?:the\s+)?(?P<pkg>"
    + _PACKAGE
    + r")\s+(?:"
    + _DEP_NOUN
    + r"|version|pin)\b(?!\s+(?:from|to)\b)",
    _I,
)
_DEP_UPDATED_PASSIVE = re.compile(
    r"\b(?P<pkg>" + _PACKAGE + r")\s+(?:was|has\s+been|is\s+now)\s+(?P<verb>bumped|upgraded"
    r"|updated|pinned)\s+(?:from\s+\S+\s+)?to\s+(?:version\s+|v(?=\d))?"
    + _VERSION
    + _NOT_A_VERSION_AFTER,
    _I,
)
#: A "Dependencies:" label; the packages after it are read like a dependency list item.
_DEP_LABEL = re.compile(
    r"^\W*(?:new\s+)?(?:dependenc(?:y|ies)|deps?|packages?)(?:\s+(?:added|changes|changed))?"
    r"\s*:\s*",
    _I,
)
#: The change a dependency list item states, before the packages ("Removed `six`") or
#: after them ("`requests` (removed)", "`urllib3` bumped to 2.2.1").
_DEP_ITEM_VERB = re.compile(
    r"(?:(?P<add>added|adds|add|new|introduced|installed)|(?P<remove>removed|removes|dropped"
    r"|drops|deleted|uninstalled)|(?P<update>bumped|bumps|upgraded|upgrades|updated|updates"
    r"|downgraded|downgrades|pinned|pins|raised))\s*:?\s+(?=\S)",
    _I,
)
_DEP_ITEM_STATUS = re.compile(
    r"\s*(?:\(\s*|[:,-]\s*)?(?:(?P<add>added|new)|(?P<remove>removed|dropped|deleted|uninstalled)"
    r"|(?P<update>bumped|upgraded|updated|downgraded|pinned))\b(?:\s+(?:from\s+\S+\s+)?to\s+"
    r"(?:version\s+)?(?P<ver>v?\d[\w.\-]*))?",
    _I,
)
_DEP_UPDATED_INLINE = re.compile(
    r"\b(?P<verb>bumped|upgraded|updated|pinned)\s+(?:the\s+)?(?P<pkg>`[^`\n]*(?:@|==)v?\d[^`\n]*`"
    r"|@?[\w.\-/]+@v?\d[\w.\-]*|[\w.\-]+==\d[\w.\-]*)",
    _I,
)
_DEP_REMOVED = re.compile(
    r"\b(?:removed|removes|dropped|drops|uninstalled|deleted|eliminated|got\s+rid\s+of)\s+"
    r"(?:the\s+)?(?:(?:unused|obsolete|legacy|old|stale|deprecated|redundant|unnecessary|dead)\s+){0,6}"
    r"(?:(?P<before>"
    + _DEP_NOUN
    + r")\s+(?:on\s+)?)?"
    + _PACKAGE_LIST
    + r"(?P<after>\s+(?:"
    + _DEP_NOUN
    + r"|from\s+(?:the\s+)?(?:project(?:'s)?\s+)?(?:"
    + _DEP_NOUN
    + r"|"
    + _MANIFEST
    + r")))?",
    _I,
)
_DEP_NAME_STOPWORDS = _words(
    "a an the it this that them these those everything version versions project package"
    " packages app code docs documentation readme changelog config configuration tests test"
    " dependencies dependency deps imports import lockfile lock file files function"
    " functions method methods logic parser cli schema api types typing comments docstring"
    " docstrings examples example todo references links link ci workflow script scripts"
    " defaults default settings threshold timeout limit constant constants variable"
    " variables message messages output logging log logs error errors loop condition check"
    " checks value values regex pattern patterns path paths url urls query signature"
    " behavior behaviour support validation flag flags option options helper helpers new"
    " unused old some all both any requirements requirement library libraries python npm"
    " pip node none nothing nil no not n/a na tbd added adds add removed removes remove"
    " dropped drops deleted bumped bumps upgraded upgrades downgraded downgrades updated"
    " updates pinned pins installed uninstalled unchanged changed"
)
_VERSION_NUMBER = re.compile(r"\d+(?:\.\d+)*")
_DEP_HEDGE = re.compile(
    r"\b(?:you|need\s+to|needs\s+to|have\s+to|has\s+to|should|must|please|will|would|could"
    r"|might|may|can|want\s+to|plan\s+to)\b",
    _I,
)
_SPEC_SPLIT = re.compile(r"\s*(?:===|==|>=|<=|~=|!=|>|<|\^|~|@(?=v?\d))")


def dependency_param(raw: str) -> tuple[str, str | None] | None:
    """Split a dependency as written ("`requests>=2.32`", "lodash@4.17.21") into name, version.

    The name loses backticks, quotes, extras ("[socks]"), and any version specifier; the
    version is the first version number of the specifier, or None. Returns None when
    the text is not a plausible package name (a common word, a path, a constant).
    """
    text = raw.strip().strip("`'\"").strip().rstrip(".,;:!?")
    if not text or " " in text.split(",")[0].strip():
        pieces = _SPEC_SPLIT.split(text, maxsplit=1)
        if " " in pieces[0].strip():
            return None
    parts = _SPEC_SPLIT.split(text, maxsplit=1)
    name = re.sub(r"\[[^\]]*\]$", "", parts[0].strip())
    version_match = _VERSION_NUMBER.search(parts[1]) if len(parts) > 1 else None
    version = version_match.group(0) if version_match else None
    if not re.fullmatch(r"@?[A-Za-z0-9][\w.\-]*(?:/[\w.\-]+)?", name):
        return None
    if name.lower() in _DEP_NAME_STOPWORDS or path_param(name) is not None:
        return None
    if "/" in name and not name.startswith("@"):
        return None
    if re.fullmatch(r"[A-Z0-9_]+", name) and "_" in name:
        return None
    return name, version


def _split_packages(v: _View, start: int, end: int) -> list[tuple[str, str | None, Span]]:
    out: list[tuple[str, str | None, Span]] = []
    pattern = re.compile(_PACKAGE, _I)
    pos = start
    while pos < end:
        match = pattern.match(v.plain, pos, end)
        if match is None:
            break
        parsed = dependency_param(v.text[match.start() : match.end()])
        if parsed is not None:
            out.append((parsed[0], parsed[1], match.span()))
        separator = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*|\s+plus\s+", _I).match(
            v.plain, match.end(), end
        )
        if separator is None:
            break
        pos = separator.end()
    return out


def _version_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    match = _VERSION_NUMBER.search(raw)
    return match.group(0) if match else None


_DEP_KINDS: Mapping[str, ClaimType] = {
    "add": ClaimType.DEPENDENCY_ADDED,
    "remove": ClaimType.DEPENDENCY_REMOVED,
    "update": ClaimType.DEPENDENCY_UPDATED,
}


def _listed_dependencies(v: _View, start: int) -> list[tuple[ClaimType, str, str | None, Span]]:
    """The dependency changes a list item or label value states from ``start`` on.

    The change is added unless a leading verb ("Removed `six`") or a status after the
    packages ("`requests` (removed)", "`urllib3` bumped to 2.2.1") says otherwise. An
    empty or negative value ("None", "no new dependencies") states none.
    """
    start = _skip_space(v.plain, start)
    if _NONE_VALUE.match(v.prose, start):
        return []
    kind = ClaimType.DEPENDENCY_ADDED
    status_version: str | None = None
    verb = _DEP_ITEM_VERB.match(v.plain, start)
    if verb is not None:
        kind = _DEP_KINDS[next(k for k in _DEP_KINDS if verb.group(k))]
        start = verb.end()
    packages = _split_packages(v, start, len(v.text))
    if packages and verb is None:
        status = _DEP_ITEM_STATUS.match(v.plain, packages[-1][2][1])
        if status is not None:
            kind = _DEP_KINDS[next(k for k in _DEP_KINDS if status.group(k))]
            status_version = _version_value(status.group("ver"))
    return [(kind, name, status_version or version, span) for name, version, span in packages]


def _dependencies(v: _View) -> list[_Candidate]:
    out: list[_Candidate] = []

    def add(kind: ClaimType, name: str, version: str | None, span: Span) -> None:
        params: Params = {"name": name}
        if version is not None and kind is not ClaimType.DEPENDENCY_REMOVED:
            params["version"] = version
        hit = PatternHit(kind, params, False, span)
        out.append(_Candidate(hit, "dependency", frozenset({"feature"}), span))

    added = ClaimType.DEPENDENCY_ADDED
    advice = bool(_ADVICE.search(v.prose))
    for regex in (_DEP_ADDED_ON, _DEP_ADDED, _DEP_ADDED_PASSIVE):
        for match in regex.finditer(v.plain):
            if advice or _DEP_HEDGE.search(v.prose[: match.start()]):
                continue  # "You need to add `httpx` as a dependency"
            for name, version, span in _split_packages(v, match.start("pkgs"), match.end("pkgs")):
                add(added, name, version, span)
    if not advice:
        for match in _MANIFEST_LABEL_ADDED.finditer(v.plain):
            for name, version, span in _split_packages(v, match.start("pkgs"), match.end("pkgs")):
                add(added, name, version, span)
        label = _DEP_LABEL.match(v.plain)
        if label is not None:  # "New dependencies: `httpx`", "Dependencies: none"
            for kind, name, version, span in _listed_dependencies(v, label.end()):
                add(kind, name, version, span)
    if _DEP_CONTEXT.match(v.context) and v.unit.kind == "list_item" and v.unit.first:
        for kind, name, version, span in _listed_dependencies(v, 0):
            add(kind, name, version, span)
    updated = ClaimType.DEPENDENCY_UPDATED
    for regex in (_DEP_UPDATED, _DEP_UPDATED_PASSIVE):
        for match in regex.finditer(v.plain):
            parsed = dependency_param(match.group("pkg"))
            raw = match.group("ver")
            if parsed is None:
                continue
            latest = "latest" in raw.lower()
            version = None if latest else _version_value(raw)
            # "Bumped `max_retries` to 5" changes a setting: a dependency update needs a
            # version-like value, a dependency noun, a manifest, or a version spec.
            groups = match.groupdict()
            cue = (
                latest
                or bool(re.search(r"\d\.\d|^v\d|[\^~<>=]", raw.strip("` ")))
                or bool(groups.get("noun1") or groups.get("noun2") or groups.get("manifest"))
                or parsed[1] is not None
            )
            if cue:
                add(updated, parsed[0], version or parsed[1], match.span())
    stated = [c.hit.anchor for c in out if c.hit.type is updated]
    for regex in (_DEP_UPDATED_NOUN, _DEP_UPDATED_INLINE):
        for match in regex.finditer(v.plain):
            if any(_overlaps(match.span(), span) for span in stated):
                continue  # "Bumped `requests==2.31` to 2.32.3": 2.31 is the old pin
            parsed = dependency_param(match.group("pkg"))
            if parsed is not None:
                add(updated, parsed[0], parsed[1], match.span())
    for match in _DEP_REMOVED.finditer(v.plain):
        uninstalled = match.group(0).lower().startswith("uninstalled")
        if not (match.group("before") or match.group("after") or uninstalled):
            continue
        for name, _, span in _split_packages(v, match.start("pkgs"), match.end("pkgs")):
            add(ClaimType.DEPENDENCY_REMOVED, name, None, span)
    return out


_FILE_VERB = re.compile(
    r"\b(?:(?P<create>created|creates|creating|added|adds|adding|wrote|writes|writing|introduced"
    r"|introduces|introducing|generated|scaffolded|initiali[sz]ed|set\s+up"
    r"|new\s+(?:test\s+)?(?:file|module|script|page|component|config|workflow)s?)"
    r"|(?P<delete>deleted|deletes|deleting|removed|removes|removing|dropped|drops|got\s+rid\s+of"
    r"|eliminated|erased|purged)"
    r"|(?P<move>renamed|renames|renaming|moved|moves|moving|relocated)"
    r"|(?P<modify>(?:changes|edits|modifications|updates|tweaks|fixes)\s+(?:to|in)"
    r"|applied\s+(?:an?\s+|the\s+|my\s+)?(?:edits?|changes?|patch(?:es)?|diffs?)\s+to"
    r"|(?:the|my|this|that)\s+(?:fix|change|changes|edit|edits|patch)\s+(?:is|are|was|were"
    r"|lives?|went)\s+(?:all\s+|entirely\s+|only\s+|mostly\s+)?(?:in|into)"
    r"|updated|updates|updating|modified|modifies|modifying|changed|changes|changing"
    r"|edited|edits|editing|tweaked|adjusted|refactored|refactors|refactoring|rewrote|rewrites"
    r"|rewritten|rewriting|reworked|restructured|reorgani[sz]ed|cleaned\s+up|simplified|patched"
    r"|touched|touching|extended|extends|amended|revised|reformatted|formatted|fixed|fixes"
    r"|fixing|corrected|tidied(?:\s+up)?|hardened|improved|optimi[sz]ed|converted|migrated"
    r"|annotated|documented|implemented|implementing|wired\s+up|hooked\s+up|replaced|ported"
    r"|commented|expanded|regenerated|configured|registered|exported|guarded|declared|bumped"
    r"|sorted|reordered))\b",
    _I,
)
_FILE_VERB_NEGATED = re.compile(
    r"\b(?P<neg>did\s*n[o']?t|did\s+not|do\s*n[o']?t|do\s+not|have\s*n[o']?t|have\s+not"
    r"|has\s*n[o']?t|has\s+not|had\s+not|never|not|without|no\s+need\s+to)\s+"
    r"(?:(?:even|actually|need\s+to|have\s+to|bother\s+to|yet|any)\s+){0,6}"
    r"(?:(?P<create>create|created|creating|add|added|adding|write|wrote|writing)"
    r"|(?P<delete>delete|deleted|deleting|remove|removed|removing|drop|dropped|dropping)"
    r"|(?P<modify>touch|touched|touching|modify|modified|modifying|change|changed|changing|edit"
    r"|edited|editing|update|updated|updating|alter|altered|altering|refactor|refactored"
    r"|refactoring|rewrite|rewrote|rewriting))\b",
    _I,
)
_STRONG_STOPS = _words(
    "so because since which that who when where while if unless until after before using"
    " via with like per see based according than as but matching match matches mirroring"
    " following reading read reads against versus vs instead rather except whether although"
    " though described referenced mentioned called named"
)
_WEAK_STOPS = _words(
    "for about around regarding covering describing documenting explaining testing"
)
_LOCATIONS = _words("in inside within at into of on under across throughout")
_SEPARATOR_ONLY = re.compile(r"^\s*(?:,|and|&|plus|as\s+well\s+as|along\s+with|\s)*\s*$", _I)
_PASSIVE_FILE = re.compile(
    r"(?:\s*(?:,|and|&)\s*(?:`[^`]*`|[\w@./\-]+))*\s+(?:(?:was|were|is|are|has\s+been|have\s+been"
    r"|got|is\s+now|are\s+now)\s+)(?:(?:also|now|both|then|just)\s+){0,6}(?:(?P<modify>updated"
    r"|modified|changed|edited|refactored|rewritten|touched|fixed|adjusted|patched|reworked)"
    r"|(?P<create>created|added|generated|introduced|new)|(?P<delete>deleted|removed|dropped"
    r"|gone))\b",
    _I,
)
_PASSIVE_UNCHANGED = re.compile(
    r"\s+(?:(?:is|was|remains|remained|stays|stayed|was\s+left|is\s+left|has\s+been\s+left"
    r"|were\s+left|are)\s+(?:completely\s+|entirely\s+|still\s+)?(?:unchanged|untouched"
    r"|unmodified|as[- ]is|alone|intact)|(?:was|were|is|are|has|have)\s*(?:n[o']?t|not)\s+"
    r"(?:been\s+)?(?:modified|changed|touched|edited|updated))\b",
    _I,
)
_LEFT_UNCHANGED = re.compile(
    r"\b(?:left|kept)\s+(?P<path>`[^`]*`|[\w@./\-]+)\s+(?:completely\s+|entirely\s+)?"
    r"(?:unchanged|untouched|unmodified|as[- ]is|alone|intact)\b"
    r"|\bno\s+(?:changes|edits|modifications)\s+(?:were\s+made\s+)?(?:to|in)\s+"
    r"(?P<path2>`[^`]*`|[\w@./\-]+)",
    _I,
)
_PAREN_STATUS = re.compile(
    r"\s*\(\s*(?:(?P<create>new|new\s+file|added|created)|(?P<delete>deleted|removed)"
    r"|(?P<modify>modified|updated|changed|edited)|(?P<unchanged>unchanged|untouched|unmodified"
    r"|not\s+(?:modified|changed|touched|edited)|no\s+changes?|as[- ]is))\s*\)",
    _I,
)
#: A file description that says the file was not changed: "untouched", "no changes
#: needed", "reviewed only, no edits", "left as is" ("otherwise unchanged" is not one).
_ITEM_UNCHANGED = re.compile(
    r"(?<!otherwise\s)(?<!else\s)(?<!rest\s)\b(?:unchanged|untouched|unmodified|not\s+(?:modified"
    r"|changed|touched|edited|updated)|no\s+(?:changes?|edits?|modifications?)|left\s+(?:as[- ]is"
    r"|alone|unchanged|untouched|intact)|kept\s+(?:as[- ]is|unchanged|intact)|as[- ]is|read[- ]only"
    r"|reviewed\s+only|only\s+reviewed)\b",
    _I,
)
#: A word in a file description that states a change ("added the flag", "fix parsing",
#: "+12 -3"). It does not count after a negation or hedge ("no edits", "should be removed").
_CHANGE_CUE = re.compile(
    r"\b(?:add(?:s|ed|ing)?|new|creat\w*|introduc\w*|fix(?:es|ed|ing)?|updat\w*|chang\w*"
    r"|modif\w*|edit\w*|refactor\w*|rewr\w*|renam\w*|mov(?:e|es|ed|ing)|remov\w*|delet\w*"
    r"|drop(?:s|ped|ping)?|replac\w*|extract\w*|implement\w*|handl(?:e|es|ed|ing)|support\w*"
    r"|wir(?:e|es|ed|ing)|register(?:s|ed|ing)?|export(?:s|ed|ing)?|switch\w*|bump\w*"
    r"|pin(?:s|ned)?|clean\w*|simplif\w*|document(?:s|ed|ing)?|annotat\w*|tweak\w*|adjust\w*"
    r"|correct\w*|patch(?:es|ed|ing)?|convert\w*|migrat\w*|expos\w*|guard(?:s|ed|ing)?"
    r"|harden\w*|improv\w*|optimi[sz]\w*|extend\w*|expand\w*|restructur\w*|rework\w*"
    r"|reorder\w*|split(?:s|ting)?|merg(?:e|es|ed|ing)|use[sd]?|accept\w*|emit\w*"
    r"|return(?:s|ed)?|rais(?:e|es|ed)|skip(?:s|ped)?|cach(?:e|es|ed|ing))\b|\+\d+",
    _I,
)
_CUE_BLOCKED = re.compile(
    r"(?:\b(?:no|not|never|without|nothing|should|would|could|will|might|may|must|considered"
    r"|consider(?:ing)?|plan(?:ned|ning)?\s+to|need(?:s|ed)?\s+to|to\s+be|going\s+to"
    r"|want(?:ed)?\s+to|todo|tbd)\s+(?:\w+\s+){0,2}|n't\s+(?:\w+\s+){0,2})$",
    _I,
)
#: A file description that is about something other than a change: a hedge, a plan, a
#: test status, or a reading note ("still failing (unrelated)", "reviewed", "see below").
_ITEM_NOT_A_CHANGE = re.compile(
    r"\b(?:should|would|could|will|might|may|must|considered|plan(?:ned)?\s+to|need(?:s|ed)?\s+to"
    r"|to\s+be|todo|tbd|follow[- ]?up|later|still|fail(?:s|ed|ing)|flaky|unrelated|reviewed"
    r"|looked\s+at|inspected|referenced|reference|see|context|nothing|none|n/a)\b",
    _I,
)
#: Verbs a commit-style description may open with ("parse `--json` and pass it on").
_BASE_VERBS = _words(
    "add fix update change modify edit refactor rewrite rename move remove delete drop replace"
    " extract implement handle support wire register export switch bump pin clean simplify"
    " document annotate tweak adjust correct patch convert migrate expose guard harden improve"
    " optimize extend expand restructure rework reorder split merge use accept emit return raise"
    " skip cache parse pass print write read load save call log check validate sort filter"
    " format render wrap catch retry set compute create introduce make allow enable disable"
    " prevent avoid ensure keep reject strip trim normalize escape encode decode serialize"
    " include exclude import inject initialize configure define declare mark warn show hide"
    " limit cap clamp round count track store fetch send map group join compare detect resolve"
    " apply schedule cancel close open start stop build run"
)
_IRREGULAR_PAST = _words("wrote rewrote made kept ran built sent took got split set put")


def _is_verb(word: str) -> bool:
    """True when ``word`` is a form of a common code-change verb ("parses", "dropped")."""
    w = word.lower()
    if w in _BASE_VERBS or w in _IRREGULAR_PAST:
        return True
    for suffix in ("ing", "ed", "es", "s", "d"):
        if not w.endswith(suffix) or len(w) <= len(suffix) + 1:
            continue
        stem = w[: -len(suffix)]
        if stem in _BASE_VERBS or stem + "e" in _BASE_VERBS:
            return True
        if suffix in ("ed", "ing") and stem[-1] == stem[-2] and stem[:-1] in _BASE_VERBS:
            return True  # "dropped", "mapping"
        if suffix in ("es", "ed") and stem.endswith("i") and stem[:-1] + "y" in _BASE_VERBS:
            return True  # "applies", "applied"
    return False


_FIRST_WORD = re.compile(r"^\W*(?:(?:now|also|then)\s+)?(?P<word>[A-Za-z][\w'-]*)")


def _item_change(description: str, default: ClaimType | None) -> ClaimType | None:
    """The file claim a path's description states, in a list item or a table row.

    A change cue that is not negated or hedged gives ``file_modified``; otherwise an
    unchanged cue gives ``file_unchanged``; a hedge, a plan, a test status or a reading
    note gives no claim; otherwise ``default`` (from a "Files changed" label or a
    "Change" header) applies, or ``file_modified`` when the description opens with a
    verb ("parse `--json` and pass it on"). A plain noun phrase gives no claim.
    """
    for match in _CHANGE_CUE.finditer(description):
        if not _CUE_BLOCKED.search(description[: match.start()]):
            return ClaimType.FILE_MODIFIED
    if _ITEM_UNCHANGED.search(description):
        return ClaimType.FILE_UNCHANGED
    if _ITEM_NOT_A_CHANGE.search(description):
        return None
    if default is not None:
        return default
    first = _FIRST_WORD.match(description)
    return ClaimType.FILE_MODIFIED if first is not None and _is_verb(first.group("word")) else None


_PREFIX_SEPARATOR = re.compile(r"\s*(?::|-{1,2}(?=\s)|→|->|=>|,|\s\(|$)")
_PREFIX_CREATED = re.compile(
    r"^\s*(?:\(?\s*new(?:\s+(?:file|module|test\s+file|script))?\s*\)?\s*(?:[:.,;-]|$)"
    r"|(?:created|added)\s*(?:$|[.(,;])|new\s+(?:file|module|test\s+file|script)\b)",
    _I,
)
_PREFIX_DELETED = re.compile(r"^\s*\(?\s*(?:deleted|removed)\s*\)?\s*(?:$|[.(,;])", _I)
_FILES_CONTEXT = re.compile(
    r"\b(?:(?P<create>new\s+files?|files?\s+(?:created|added)|(?:created|added)\s+files?)"
    r"|(?P<delete>files?\s+(?:deleted|removed)|(?:deleted|removed)\s+files?)"
    r"|(?P<modify>files?\s+(?:changed|modified|updated|touched|edited)|(?:changed|modified"
    r"|updated|touched|edited)\s+files?|changes|changed|what\s+(?:i\s+)?changed"
    r"|summary\s+of\s+changes|^files$))\b",
    _I,
)
_STATUS_CELL: Mapping[str, ClaimType] = {
    "unchanged": ClaimType.FILE_UNCHANGED,
    "untouched": ClaimType.FILE_UNCHANGED,
    "unmodified": ClaimType.FILE_UNCHANGED,
    "nottouched": ClaimType.FILE_UNCHANGED,
    "notmodified": ClaimType.FILE_UNCHANGED,
    "notchanged": ClaimType.FILE_UNCHANGED,
    "nochanges": ClaimType.FILE_UNCHANGED,
    "nochange": ClaimType.FILE_UNCHANGED,
    "noedits": ClaimType.FILE_UNCHANGED,
    "asis": ClaimType.FILE_UNCHANGED,
    "added": ClaimType.FILE_CREATED,
    "new": ClaimType.FILE_CREATED,
    "created": ClaimType.FILE_CREATED,
    "a": ClaimType.FILE_CREATED,
    "deleted": ClaimType.FILE_DELETED,
    "removed": ClaimType.FILE_DELETED,
    "d": ClaimType.FILE_DELETED,
    "modified": ClaimType.FILE_MODIFIED,
    "updated": ClaimType.FILE_MODIFIED,
    "changed": ClaimType.FILE_MODIFIED,
    "edited": ClaimType.FILE_MODIFIED,
    "m": ClaimType.FILE_MODIFIED,
}
_STATUS_LEAD = re.compile(r"^\W*(new|added|created|deleted|removed)\s*(?::|-{1,2}\s|\()", _I)
_CHANGE_HEADER = re.compile(r"chang|modif|updat|what|descri|summar|edit|status|action|diff", _I)
_FRONTED_LOCATION = re.compile(r"^\W*(?:in|inside|within)\s+(?:the\s+)?(?=`|[\w./-]+\.\w)", _I)


@dataclass(frozen=True)
class _VerbRef:
    start: int
    end: int
    kind: str
    negated: bool


def _file_verbs(v: _View) -> list[_VerbRef]:
    verbs: list[_VerbRef] = []
    negated_spans: list[Span] = []
    for match in _FILE_VERB_NEGATED.finditer(v.prose):
        kind = next(k for k in ("create", "delete", "modify") if match.group(k))
        verbs.append(_VerbRef(match.start(), match.end(), kind, True))
        negated_spans.append(match.span())
    for match in _FILE_VERB.finditer(v.prose):
        if any(_overlaps(match.span(), span) for span in negated_spans):
            continue
        kind = next(k for k in ("create", "delete", "move", "modify") if match.group(k))
        verbs.append(_VerbRef(match.start(), match.end(), kind, False))
    return sorted(verbs, key=lambda r: r.start)


def _file_type(kind: str, relation: str, negated: bool) -> tuple[ClaimType, bool]:
    if relation == "location" or kind == "modify":
        return (ClaimType.FILE_UNCHANGED, False) if negated else (ClaimType.FILE_MODIFIED, False)
    if kind == "create":
        return ClaimType.FILE_CREATED, negated
    return ClaimType.FILE_DELETED, negated


def _drop_value_change(words: list[str], kind: str) -> list[str]:
    """Drop "from" and "to" of a value change that a location follows.

    "Changed the log level from DEBUG to INFO in `settings.py`": the change is in the
    file. Without a location after the pair ("from `a.py` to `b.py`") nothing is dropped.
    """
    if kind != "modify" or "from" not in words:
        return words
    start = words.index("from")
    if "to" not in words[start + 1 :]:
        return words
    to = words.index("to", start + 1)
    if not any(word in ("in", "inside", "within") for word in words[to + 1 :]):
        return words
    return words[:start] + words[start + 1 : to] + words[to + 1 :]


def _relation(words: list[str], kind: str) -> str | None:
    """How a path relates to a change verb, from the words between them.

    Returns "direct" (the path is the verb's object), "location" (the change happened in
    the path), or None (the path is a reference, a purpose, or otherwise not changed).
    """
    to_is_location = kind in ("create", "delete", "move")
    from_is_location = kind in ("delete", "move")
    words = _drop_value_change(words, kind)
    strong_seen = soft_seen = False
    last: str | None = None
    last_word = ""
    for word in words:
        if word == "that":
            soft_seen = True  # "the imports that referenced it in `app/main.py`"
            last = "stop"
        elif (
            word in _STRONG_STOPS
            or (word == "to" and not to_is_location)
            or (word == "from" and not from_is_location)
        ):
            strong_seen = True
            last = "stop"
        elif word in _WEAK_STOPS:
            last = "weak"
        elif word in _LOCATIONS or word in ("to", "from"):
            last = "location"
            last_word = word
    if last is None:
        return None if strong_seen or soft_seen else "direct"
    if last == "location":
        if strong_seen or (soft_seen and last_word not in ("in", "inside", "within")):
            return None
        return "location"
    return None


#: Hedges and plans right before a file verb: "I should have updated", "I considered
#: editing", "make sure ... is updated".
_FILE_HEDGE = re.compile(
    r"\b(?:should|would|could|might|must|may|will|shall|can|i'?ll|we'?ll|you'?ll|need\s+to"
    r"|needs\s+to|want\s+to|wanted\s+to|plan\s+to|planned\s+to|planning\s+to|going\s+to"
    r"|try\s+to|tried\s+to|forgot\s+to|remember\s+to|meant\s+to|intend(?:ed)?\s+to|about\s+to"
    r"|considered|consider|considering|thinking\s+of|make\s+sure|ensure|be\s+sure\s+to"
    r"|don'?t\s+forget\s+to|please|recommend|suggest|todo)\s+(?:(?:not|also|have|just|still"
    r"|then|first|be|to|really|probably|definitely|eventually|later)\s+){0,3}$",
    _I,
)
#: A condition that governs the rest of its clause: "If `settings.py` is updated later",
#: "Once `schema.sql` is created". "When I updated `a.py`" reports an event, not a condition.
_FILE_CONDITION = re.compile(
    r"\b(?:if|unless|in\s+case|whether|provided\s+that|once|when|whenever|as\s+soon\s+as)\b"
    r"(?![^,;]*\b(?:i|we)\s+(?:had\s+|have\s+|also\s+|then\s+|first\s+)?(?:\w+ed|wrote|made"
    r"|ran|set|put|rewrote|split)\b)[^,;]*$",
    _I,
)
_CONTRAST = re.compile(r"\b(?:only|but|instead|rather|except|not|versus|vs)\b", _I)
_VALUE_TO_IN = re.compile(
    r"\bto\s+(?:-?\d[\w.%]*|`C+`|true|false|none|null|\"[^\"]*\"|'[^']*')\s+(?:in|inside|within)"
    r"\s+(?:the\s+)?$",
    _I,
)


def _file_hedged(v: _View, start: int, end: int) -> bool:
    """True when a file claim at ``start`` (its verb ending at ``end``) is hedged.

    A hedge or plan right before it ("should have", "considered", "make sure") or a
    condition earlier in its clause ("if", "once", "when" without "I ... -ed").
    """
    return bool(_FILE_HEDGE.search(v.prose[:start]) or _FILE_CONDITION.search(v.prose[:end]))


def _drop_last(words: list[str], word: str) -> list[str]:
    """``words`` without the last occurrence of ``word``."""
    if word not in words:
        return words
    index = len(words) - 1 - words[::-1].index(word)
    return words[:index] + words[index + 1 :]


def _between_words(v: _View, start: int, end: int, refs: Sequence[_PathRef]) -> list[str]:
    chars = list(v.prose[start:end])
    for ref in refs:
        for k in range(max(ref.start, start), min(ref.end, end)):
            chars[k - start] = " "
    return re.findall(r"[a-z][a-z'-]*", "".join(chars).lower())


def _file_rows(v: _View, refs: list[_PathRef]) -> tuple[list[_Candidate], set[int]]:
    """File claims for paths that fill a table cell, and the starts of those paths.

    The status comes from another cell ("Added", "M", "New: ...") or, failing that, from
    a change-describing header or context ("Change", "Files changed").
    """
    cells = table_cells(v.text)
    out: list[_Candidate] = []
    whole: set[int] = set()
    header_changes = any(_CHANGE_HEADER.search(h) for h in v.unit.header)
    context_kind = _FILES_CONTEXT.search(v.context)
    for ref in refs:
        cell = next((c for c in cells if c[0] <= ref.start and ref.end <= c[1]), None)
        if cell is None or _clip(v.text, cell[0], cell[1]) != _clip(v.text, ref.start, ref.end):
            continue
        whole.add(ref.start)
        status: ClaimType | None = None
        texts: list[str] = []
        for other in cells:
            if other == cell:
                continue
            raw = mask_markdown(v.text[other[0] : other[1]])
            word = re.sub(r"[^a-z]", "", raw.lower())
            lead = _STATUS_LEAD.match(raw)
            if word in _STATUS_CELL:
                status = _STATUS_CELL[word]
                break
            if lead is not None:
                status = _STATUS_CELL[lead.group(1).lower()]
                break
            texts.append(raw)
        if status is None and (header_changes or context_kind):
            # "| `b.py` | Reviewed, no edits |" under a "Change" header is not a change.
            status = _item_change(" ".join(texts), ClaimType.FILE_MODIFIED)
        if status is not None:
            hit = PatternHit(status, {"path": ref.value}, False, (ref.start, ref.end))
            out.append(_Candidate(hit, "file", frozenset(), (ref.start, ref.end)))
    return out, whole


def _files(v: _View) -> list[_Candidate]:
    refs = _paths(v)
    if not refs:
        return []
    out: list[_Candidate] = []
    decided: set[int] = set()
    if v.unit.kind == "table_row":
        rows, whole = _file_rows(v, refs)
        out.extend(rows)
        decided |= whole
        refs = [ref for ref in refs if ref.start not in whole]
        if not refs:
            return out

    def add(ref: _PathRef, claim_type: ClaimType, negated: bool, anchor_start: int) -> None:
        if ref.start in decided:
            return
        decided.add(ref.start)
        hit = PatternHit(claim_type, {"path": ref.value}, negated, (anchor_start, ref.end))
        out.append(_Candidate(hit, "file", frozenset(), (anchor_start, ref.end)))

    first = refs[0]
    prefix = v.prose[: first.start]
    is_item = v.unit.kind == "list_item" and v.unit.first
    if is_item and not re.search(r"[A-Za-z0-9]", prefix):
        after = _PAREN_STATUS.match(v.prose, first.end)
        rest_at = after.end() if after else first.end
        separator = _PREFIX_SEPARATOR.match(v.prose, rest_at)
        context_kind = _FILES_CONTEXT.search(v.context)
        if after is not None:
            kinds = ("create", "delete", "modify", "unchanged")
            kind = next(k for k in kinds if after.group(k))
            if kind == "unchanged":  # "- `src/config.py` (unchanged)"
                add(first, ClaimType.FILE_UNCHANGED, False, first.start)
            else:
                add(first, _file_type(kind, "direct", False)[0], False, first.start)
        elif separator is not None:
            # The rest of the sentence belongs to the description: "- `docs/usage.md`:
            # considered updating, but left as is" is cut before "left as is".
            description = v.prose[separator.end() :]
            if description.strip(" .;:,"):
                description += " " + mask_markdown(v.unit.rest, blank_code=True)
            default: ClaimType | None = None
            if context_kind is not None:
                kind = next(k for k in ("create", "delete", "modify") if context_kind.group(k))
                default = _file_type(kind, "direct", False)[0]
            if not description.strip(" .;:,"):
                if default is not None:
                    add(first, default, False, first.start)
            elif _PREFIX_CREATED.match(description):
                add(first, ClaimType.FILE_CREATED, False, first.start)
            elif _PREFIX_DELETED.match(description):
                add(first, ClaimType.FILE_DELETED, False, first.start)
            else:
                # "- `api.py`: untouched", "- `legacy.py`: should be removed later"
                claim_type = _item_change(description, default)
                if claim_type is None:
                    decided.add(first.start)
                else:
                    add(first, claim_type, False, first.start)
    fronted = _FRONTED_LOCATION.match(v.prose)
    if fronted is not None and first.start == fronted.end():
        # "In `src/app.py`, added a `--json` flag": the change happened in the path.
        later = [verb for verb in _file_verbs(v) if verb.start >= first.end]
        if later and not _file_hedged(v, later[0].start, later[0].end):
            claim_type, negated = _file_type("modify", "location", later[0].negated)
            add(first, claim_type, negated, first.start)
    for match in _LEFT_UNCHANGED.finditer(v.prose):
        start = match.start("path") if match.group("path") else match.start("path2")
        ref = next((r for r in refs if r.start == start), None)
        if ref is not None and not _file_hedged(v, match.start(), match.start()):
            add(ref, ClaimType.FILE_UNCHANGED, False, match.start())
    for ref in refs:
        if _file_hedged(v, ref.start, ref.start):
            continue  # "If `settings.py` is updated later", "Make sure `a.py` is updated"
        unchanged = _PASSIVE_UNCHANGED.match(v.prose, ref.end)
        if unchanged is not None:
            add(ref, ClaimType.FILE_UNCHANGED, False, ref.start)
            continue
        status = _PAREN_STATUS.match(v.prose, ref.end)
        passive = _PASSIVE_FILE.match(v.prose, ref.end)
        chosen = status or passive
        if chosen is not None and not _FILE_VERB.search(v.prose, 0, ref.start):
            kinds = ("create", "delete", "modify", "unchanged")
            kind = next(k for k in kinds if chosen.groupdict().get(k))
            if kind == "unchanged":
                add(ref, ClaimType.FILE_UNCHANGED, False, ref.start)
            else:
                add(ref, _file_type(kind, "direct", False)[0], False, ref.start)
    verbs = _file_verbs(v)
    relations: dict[int, str | None] = {}
    for index, ref in enumerate(refs):
        verb = next((vb for vb in reversed(verbs) if vb.end <= ref.start), None)
        if verb is None or ref.start in decided:
            continue
        if _file_hedged(v, verb.start, verb.end):
            continue  # "I should have updated `settings.py`", "I considered editing it"
        previous = refs[index - 1] if index else None
        after_previous = previous is not None and previous.start >= verb.end
        if (
            after_previous
            and previous is not None
            and _CONTRAST.search(v.prose[previous.end : ref.start])
        ):
            # "I didn't change `api.py`, only `cli.py`": the relation does not carry over.
            relations[ref.start] = None
            continue
        if (
            after_previous
            and previous is not None
            and _SEPARATOR_ONLY.match(v.prose[previous.end : ref.start])
            and previous.start in relations
        ):
            relation = relations[previous.start]
        else:
            words = _between_words(v, verb.end, ref.start, refs)
            if "from" not in words and _VALUE_TO_IN.search(v.prose, verb.end, ref.start):
                # "Bumped `max_retries` to 5 in `src/client.py`": the value change
                # happened in the path.
                words = _drop_last(words, "to")
            relation = _relation(words, verb.kind)
        if relation == "direct" and ref.node:
            relation = "location"  # "added test `tests/x.py::test_y`" changes tests/x.py
        relations[ref.start] = relation
        if relation is None:
            continue
        if verb.kind == "move":
            if relation == "direct":
                add(ref, ClaimType.FILE_DELETED, False, verb.start)
                continue
            words = _between_words(v, previous.end if previous else verb.end, ref.start, refs)
            moved_from = previous is not None and relations.get(previous.start) == "direct"
            renamed = v.text[verb.start : verb.end].lower().startswith("renam")
            if (moved_from or renamed) and words and words[-1] in ("to", "into", "as"):
                add(ref, ClaimType.FILE_CREATED, False, verb.start)
                continue
            add(ref, ClaimType.FILE_MODIFIED, False, verb.start)
            continue
        claim_type, negated = _file_type(verb.kind, relation, verb.negated)
        add(ref, claim_type, negated, verb.start)
    return out


_KIND_CLAIMS: Mapping[str, tuple[ClaimType, str]] = {
    "test": (ClaimType.TESTS_PASS, "tests"),
    "lint": (ClaimType.LINT_CLEAN, "lint"),
    "typecheck": (ClaimType.TYPECHECK_CLEAN, "typecheck"),
    "build": (ClaimType.BUILD_SUCCEEDS, "build"),
}


def _item_kinds(command: str) -> frozenset[str]:
    """Check kinds of a command item: a generic phrase by its noun, else by its program."""
    if generic_command(command) is None:
        return command_kinds(command)
    if re.search(r"\b(?:tests?|specs?|suites?|test\s+suites?)$", command):
        return frozenset({"test"})
    for word, kind in (("lint", "lint"), ("type", "typecheck"), ("build", "build")):
        if word in command:
            return frozenset({kind})
    return frozenset()


def _status_claims(command: str, negated: bool, anchor: Span) -> list[_Candidate]:
    """The status claims a run of ``command`` reports: tests pass, lint clean, and so on."""
    kinds = _item_kinds(command)
    out: list[_Candidate] = []
    for kind in ("test", "lint", "typecheck", "build"):
        if kind not in kinds:
            continue
        claim_type, family = _KIND_CLAIMS[kind]
        params: Params = {}
        program = _program_of(command) if generic_command(command) is None else None
        if kind in ("lint", "typecheck") and program:
            params["tool"] = program
        if kind == "build" and generic_command(command) is None:
            params["tool"] = command
        hit = PatternHit(claim_type, params, negated, anchor)
        out.append(_Candidate(hit, family, frozenset(), anchor))
    return out


_CHECK_MARK = re.compile(
    r"^\W*?(?:(?P<ok>✅|✔️?|✓|☑️?)|(?P<bad>❌|✖️?"
    r"|✗|⛔))\s*(?:[A-Za-z][\w /-]{0,30}?\s*:\s*)?(?=`)"
)


def _checkmark(v: _View) -> list[_Candidate]:
    """A status line opening with a check mark and a command: "- ✅ `ruff check src`"."""
    match = _CHECK_MARK.match(v.prose)
    span = v.code_at(match.end()) if match is not None else None
    if match is None or span is None:
        return []
    command = command_param(v.content(span))
    if command is None:
        return []
    anchor = (match.start(), span[1])
    ran = PatternHit(ClaimType.RAN_COMMAND, {"command": command}, False, anchor)
    out = [_Candidate(ran, "command", frozenset(), anchor)]
    return out + _status_claims(command, match.group("bad") is not None, anchor)


_LIST_STATUS = re.compile(
    r"\s*[:,;]?\s*(?:and\s+)?(?:they\s+all|they\s+both|both\s+of\s+them|all\s+of\s+them|they"
    r"|both|all|each)\s+(?:(?:now|still|also)\s+){0,6}(?:(?P<ok>pass(?:es|ed)?|succeed(?:s|ed)?"
    r"|are\s+(?:green|clean|passing)|were\s+(?:green|clean|successful))|(?P<bad>fail(?:s|ed)?"
    r"|are\s+failing))\b",
    _I,
)


def _command_status(v: _View) -> list[_Candidate]:
    """Status of commands listed after a run verb: "Ran `pytest` and `ruff check .`: both pass"."""
    if _ADVICE.search(v.prose):
        return []
    out: list[_Candidate] = []
    for match in _RAN_VERB.finditer(v.prose):
        verb = match.group("verb").lower().replace(" ", "")
        before = v.prose[: match.start()]
        if match.group("neg") is not None or _ADVICE_BEFORE.search(before):
            continue
        if verb in _RAN_BASE_FORMS and not _PERFECT.search(before):
            continue
        items = _command_items(v, match.end())
        status = _LIST_STATUS.match(v.prose, items[-1].end) if items else None
        if status is None:
            continue
        anchor = (match.start(), status.end())
        for item in items:
            out.extend(_status_claims(item.command, status.group("bad") is not None, anchor))
    return out


_CLEAN_OUTPUT = re.compile(
    r"^(?:all\s+checks\s+passed!?|success:\s*no\s+issues\s+found.*|found\s+0\s+errors.*"
    r"|0\s+errors.*|no\s+issues\s+found.*|0\s+problems.*|no\s+(?:errors|problems)\s+found.*)$",
    _I,
)


def _clean_output_prose(v: _View) -> str:
    """``v.prose`` with inline code that quotes a clean result ("`All checks passed!`")
    replaced by the word "clean", at the same length."""
    chars = list(v.prose)
    for start, end in v.codes:
        if _CLEAN_OUTPUT.match(v.content((start, end))):
            chars[start:end] = list("clean".ljust(end - start))
    return "".join(chars)


_CITED_WITH = re.compile(
    r"\b(?:with|using|via|from|per|by\s+running|after\s+running|running)\s*$", _I
)


def _evidence_commands(v: _View, kept: Sequence[_Candidate]) -> list[_Candidate]:
    status_types = {
        ClaimType.TESTS_PASS,
        ClaimType.TEST_COUNT,
        ClaimType.LINT_CLEAN,
        ClaimType.TYPECHECK_CLEAN,
        ClaimType.BUILD_SUCCEEDS,
    }
    status = [c for c in kept if c.hit.type in status_types]
    if not status or _ADVICE.search(v.prose):
        return []
    if any(
        c.hit.type is ClaimType.COULD_NOT or (c.family == "command" and c.hit.negated) for c in kept
    ):
        return []
    first_status_end = min(c.hit.anchor[1] for c in status)
    depth = 0
    depths: list[int] = []
    for char in v.prose:
        if char == "(":
            depth += 1
        depths.append(depth)
        if char == ")" and depth:
            depth -= 1
    out: list[_Candidate] = []
    for span in v.codes:
        command = command_param(v.content(span))
        if command is None:
            continue
        before = v.prose[: span[0]]
        cited = depths[span[0]] > 0 or (
            span[0] >= first_status_end and _CITED_WITH.search(before) is not None
        )
        if cited:
            hit = PatternHit(ClaimType.RAN_COMMAND, {"command": command}, False, span)
            out.append(_Candidate(hit, "command", frozenset(), span))
    return out


_RULES: tuple[Rule, ...] = (
    _tests_added,
    _bug_fixed,
    _feature,
    _could_not,
    _task_complete,
    _ran_command,
    _test_numbers,
    _tests_pass,
    _lint,
    _typecheck,
    _build,
    _checkmark,
    _command_status,
    _dependencies,
    _files,
)
#: The rules read in a heading or label line: explicit status statements only ("## All
#: 42 tests pass", "**Status: done**"). "## Done", "## Known failures" or "## Fixed bugs"
#: name a section and state nothing.
_LABEL_RULES: tuple[Rule, ...] = (
    _task_complete,
    _test_numbers,
    _tests_pass,
    _lint,
    _typecheck,
    _build,
    _checkmark,
)
#: Sections that list work not done ("Not done", "Next steps", "TODO"): a positive claim
#: about the work there ("- Added pagination") describes what is still to do.
_NOT_DONE_CONTEXT = re.compile(
    r"^\W*(?:not\s+(?:yet\s+)?(?:done|implemented|completed?|finished|addressed|included|fixed"
    r"|started)|to\s*-?\s*dos?|todos?|next\s+steps?|follow[- ]?ups?|future\s+(?:work"
    r"|improvements?|steps)|possible\s+(?:improvements?|follow[- ]?ups?|next\s+steps?)"
    r"|remaining\s+(?:work|tasks?|items?|steps?)|left\s+to\s+do|still\s+to\s+do|open\s+(?:items"
    r"|questions|tasks)|pending|deferred|out\s+of\s+scope|incomplete|unfinished|what'?s\s+left"
    r"|what\s+remains|suggestions?|recommendations?|ideas|blocked|won'?t\s+(?:do|fix))\b",
    _I,
)
#: Claim types that report work done; in a not-done section only their admissions stay.
_WORK_TYPES = frozenset(
    {
        ClaimType.TESTS_ADDED,
        ClaimType.BUG_FIXED,
        ClaimType.FEATURE_IMPLEMENTED,
        ClaimType.TASK_COMPLETE,
        ClaimType.RAN_COMMAND,
        ClaimType.FILE_MODIFIED,
        ClaimType.FILE_CREATED,
        ClaimType.FILE_DELETED,
        ClaimType.DEPENDENCY_ADDED,
        ClaimType.DEPENDENCY_UPDATED,
        ClaimType.DEPENDENCY_REMOVED,
    }
)


def _count_admission(hit: PatternHit) -> PatternHit | None:
    """The negated ``tests_pass`` a test count with failures implies ("39 passed, 3 failed")."""
    failed = hit.params.get("failed")
    if hit.type is not ClaimType.TEST_COUNT or not isinstance(failed, int) or failed <= 0:
        return None
    return PatternHit(ClaimType.TESTS_PASS, {}, True, hit.anchor)


def match_unit(unit: Unit) -> list[PatternHit]:
    """Every claim the pattern rules find in ``unit``, in the order they appear in it.

    Rules run in priority order (see the module docstring); a candidate whose anchor
    overlaps a region reserved by an earlier rule for its family is dropped, and
    claims with identical (type, params) are kept once, the first in unit order. A
    heading or label line is read only for explicit status statements; an unchecked
    task box ("- [ ] Added pagination") gives no claim; and for the items listed under
    a section of work not done ("Next steps", "Not done", "TODO") only admissions and
    status claims are kept.
    """
    if unit.checked is False:
        return []
    view = _View(unit)
    kept: list[_Candidate] = []
    reserved: list[tuple[frozenset[str], Span]] = []
    for rule in _LABEL_RULES if unit.label else _RULES:
        for candidate in rule(view):
            if candidate.family == _RESERVE_ONLY:
                reserved.append((candidate.blocks, candidate.region))
                continue
            if any(
                candidate.family in families and _overlaps(candidate.hit.anchor, region)
                for families, region in reserved
            ):
                continue
            kept.append(candidate)
            if candidate.blocks:
                reserved.append((candidate.blocks, candidate.region))
    kept.extend(_evidence_commands(view, kept))
    if unit.kind in ("list_item", "table_row") and _NOT_DONE_CONTEXT.match(view.context):
        kept = [c for c in kept if c.hit.negated or c.hit.type not in _WORK_TYPES]
    seen: set[tuple[ClaimType, tuple[tuple[str, ParamValue], ...]]] = set()
    hits: list[PatternHit] = []
    for candidate in sorted(kept, key=lambda c: (c.hit.anchor[0], c.hit.anchor[1])):
        for hit in (candidate.hit, _count_admission(candidate.hit)):
            if hit is None or hit.key() in seen:
                continue
            seen.add(hit.key())
            hits.append(hit)
    return hits


@dataclass(frozen=True)
class UnitMatches:
    """The pattern claims of one unit.

    Attributes:
        unit: The unit.
        hits: Its pattern claims in order (empty when no rule matched).
    """

    unit: Unit
    hits: tuple[PatternHit, ...] = field(default_factory=tuple)


def match_units(segmentation: Segmentation) -> list[UnitMatches]:
    """:func:`match_unit` for every unit of a segmented report, in report order."""
    return [UnitMatches(unit, tuple(match_unit(unit))) for unit in segmentation.units]


def hit_claim(unit: Unit, hit: PatternHit, claim_id: str) -> Claim:
    """The :class:`Claim` for one pattern hit: the unit's text and span, extractor "pattern"."""
    return Claim(
        claim_id=claim_id,
        type=hit.type,
        text=unit.text,
        span=unit.span,
        params=dict(hit.params),
        negated=hit.negated,
        extractor="pattern",
    )


def pattern_claims(report: str) -> list[Claim]:
    """Every pattern claim in ``report``, with ids ``"c0"``, ``"c1"``, ... in report order."""
    claims: list[Claim] = []
    for matches in match_units(segment(report)):
        for hit in matches.hits:
            claims.append(hit_claim(matches.unit, hit, f"c{len(claims)}"))
    return claims
