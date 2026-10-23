"""Find every test, lint, and type-check run in one command's output.

Detection is output-based first: each parser looks for its own tool's summary,
so ``make test``, ``uv run pytest -q``, ``npm test``, ``npx jest`` and unknown
wrapper scripts are all recognized. The command line (and the commands that
npm and yarn echo before running a script) adds hints for three things output
cannot show on its own:

- tools that print nothing on success (flake8, ESLint, tsc): when the command
  names one, exits 0, and printed nothing but wrapper chatter, a clean run is
  recorded;
- TAP output, which Mocha's TAP reporter shares with ``node --test``;
- a bare ``Found N errors.`` line, which both ruff and older tsc print.

When several frameworks could match, the most specific signature wins: a
native runner summary beats a JUnit XML report of the same run, and tsc's
``error TS`` lines claim a bare ``Found N errors.`` line unless ruff is named.

Commands that only display text (``cat log.txt``, ``tail -n 20 out.txt``,
``grep``, ``echo``) are not runs, so nothing is derived from them even when the
text they print looks like a test summary.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from receipts.ledger.parsers.junit import parse_junit
from receipts.ledger.parsers.linters import (
    parse_eslint,
    parse_flake8,
    parse_format_check,
    parse_ruff,
)
from receipts.ledger.parsers.node import parse_jest, parse_mocha, parse_node_test, parse_vitest
from receipts.ledger.parsers.python_tests import parse_pytest, parse_unittest
from receipts.ledger.parsers.results import ParsedLint, ParsedTestRun, ParsedTypecheck
from receipts.ledger.parsers.text import clean_lines
from receipts.ledger.parsers.typecheckers import parse_mypy, parse_pyright, parse_tsc


@dataclass(frozen=True)
class DerivedRuns:
    """Every run recognized in one command's output, in a fixed order per kind."""

    tests: tuple[ParsedTestRun, ...] = ()
    lints: tuple[ParsedLint, ...] = ()
    typechecks: tuple[ParsedTypecheck, ...] = ()

    def __bool__(self) -> bool:
        """True when anything was recognized."""
        return bool(self.tests or self.lints or self.typechecks)


_HINTS: dict[str, re.Pattern[str]] = {
    "pytest": re.compile(r"\bpy\.?test\b"),
    "jest": re.compile(r"\bjest\b"),
    "vitest": re.compile(r"\bvitest\b"),
    "mocha": re.compile(r"\bmocha\b"),
    "node-test": re.compile(r"\bnode\b[^\n;&|]*\s--test\b"),
    "ruff": re.compile(r"\bruff\b"),
    "flake8": re.compile(r"\bflake8\b"),
    "eslint": re.compile(r"\beslint\b"),
    "mypy": re.compile(r"\bd?mypy\b"),
    "pyright": re.compile(r"\b(?:based)?pyright\b"),
    "tsc": re.compile(r"\b(?:vue-)?tsc\b"),
}
_NPM_HEADER = re.compile(r"^> (?:@[\w.-]+/)?[\w.-]+@\S+ [\w:.-]+(?: .*)?$")
_YARN_HEADER = re.compile(r"^yarn run v\d")
_CHATTER = re.compile(r"^(?:> .*|\$ .*|npm (?:warn|WARN|notice) .*|yarn run v.*|Done in .*)$")

_VIEWER_NAMES = """
cat head tail less more grep egrep fgrep rg ag sed awk echo printf cut sort uniq wc jq bat
cd ls pwd true false diff nl tac strings xxd od file stat tr column fold fmt type which
test [ sleep tee
"""
VIEWERS = frozenset(_VIEWER_NAMES.split())
_PREFIXES = frozenset({"sudo", "env", "time", "command", "builtin", "exec", "nice", "nohup"})
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "{", "}", "!"})
_REDIRECTS = frozenset({">", ">>", "<", ">&", "<&", "&>", "&>>", ">|", "<<", "<<<", "<>"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _programs(cmd: str) -> list[str] | None:
    """The program run by each simple command in ``cmd``, or None if it does not lex."""
    lexer = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    programs: list[str] = []
    expecting = True
    skip_next = False
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if token in _SEPARATORS:
            expecting = True
            continue
        if token in _REDIRECTS:
            skip_next = True
            continue
        if not expecting:
            continue
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
        if (
            _ASSIGNMENT.match(token)
            or token in _PREFIXES
            or (token.isdigit() and nxt in _REDIRECTS)
        ):
            continue
        programs.append(PurePosixPath(token).name)
        expecting = False
    return programs


def is_viewer_command(cmd: str) -> bool:
    """True when every program in ``cmd`` only displays or filters text (``cat``, ``tail``).

    Such commands can print an old or hand-made test summary, so the recorder
    derives no runs from them. A command that also runs anything else (``pytest
    > out.txt; tail out.txt``) is not a viewer command.
    """
    programs = _programs(cmd)
    return bool(programs) and all(program in VIEWERS for program in programs or ())


def command_hints(cmd: str, lines: Sequence[str] = ()) -> frozenset[str]:
    """Tool names mentioned by ``cmd`` or by script commands that npm or yarn echoed.

    npm echoes ``> pkg@1.0.0 test`` then ``> jest``; yarn echoes ``$ jest`` after
    ``yarn run v1``. Only those echo lines are read from the output.
    """
    sources = [cmd]
    yarn = any(_YARN_HEADER.match(line) for line in lines)
    for index, line in enumerate(lines):
        npm_echo = index > 0 and bool(_NPM_HEADER.match(lines[index - 1]))
        if (npm_echo and line.startswith("> ")) or (yarn and line.startswith("$ ")):
            sources.append(line[2:])
    joined = "\n".join(sources)
    return frozenset(name for name, pattern in _HINTS.items() if pattern.search(joined))


def is_quiet(lines: Sequence[str]) -> bool:
    """True when the output holds nothing but blank lines and npm or yarn chatter."""
    return all(not line.strip() or _CHATTER.match(line) for line in lines)


def _detect_tests(text: str, hints: frozenset[str]) -> list[ParsedTestRun]:
    runs: list[ParsedTestRun] = []
    pytest_run = parse_pytest(text)
    if pytest_run is not None:
        runs.append(pytest_run)
    else:
        unittest_run = parse_unittest(text)
        if unittest_run is not None:
            runs.append(unittest_run)
    node_run = parse_node_test(text)
    if node_run is not None:
        if "mocha" in hints and "node-test" not in hints:
            node_run["framework"] = "mocha"  # Mocha's TAP reporter prints the same summary
        runs.append(node_run)
    parsers: list[Callable[[str], ParsedTestRun | None]] = [parse_jest, parse_vitest, parse_mocha]
    for parser in parsers:
        run = parser(text)
        if run is not None:
            runs.append(run)
    if not runs:
        junit_run = parse_junit(text)
        if junit_run is not None:
            runs.append(junit_run)
    return runs


def analyze_output(
    cmd: str, stdout: str, stderr: str = "", exit_code: int | None = None
) -> DerivedRuns:
    """Recognize every test, lint, and type-check run in one command's output.

    ``stdout`` and ``stderr`` are read together (Jest and npm write to stderr).
    ``exit_code`` enables the clean-run inference for silent tools; pass None
    when it is unknown. Returns an empty :class:`DerivedRuns` for viewer
    commands (see :func:`is_viewer_command`).
    """
    if is_viewer_command(cmd):
        return DerivedRuns()
    text = "\n".join(part for part in (stdout, stderr) if part)
    lines = clean_lines(text)
    hints = command_hints(cmd, lines)
    quiet = exit_code == 0 and is_quiet(lines)

    typechecks: list[ParsedTypecheck] = []
    for parser in (parse_mypy, parse_pyright):
        found = parser(text)
        if found is not None:
            typechecks.append(found)
    tsc = parse_tsc(text)
    if tsc is None and quiet and "tsc" in hints:
        tsc = ParsedTypecheck(tool="tsc", errors=0)
    if tsc is not None:
        typechecks.append(tsc)

    lints: list[ParsedLint] = []
    ruff = parse_ruff(text)
    ruff_specific = "ruff" in hints or any(line.strip() == "All checks passed!" for line in lines)
    if ruff is not None and (tsc is None or ruff_specific):
        lints.append(ruff)
    else:
        ruff = None
    flake8 = parse_flake8(text)
    if flake8 is None and quiet and "flake8" in hints:
        flake8 = ParsedLint(tool="flake8", errors=0, warnings=0)
    if flake8 is not None and (ruff is None or "flake8" in hints):
        lints.append(flake8)
    eslint = parse_eslint(text)
    if eslint is None and quiet and "eslint" in hints:
        eslint = ParsedLint(tool="eslint", errors=0, warnings=0)
    if eslint is not None:
        lints.append(eslint)
    formatter = parse_format_check(text)
    if formatter is not None:
        lints.append(formatter)

    return DerivedRuns(
        tests=tuple(_detect_tests(text, hints)), lints=tuple(lints), typechecks=tuple(typechecks)
    )
