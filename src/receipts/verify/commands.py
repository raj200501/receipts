"""Shell command normalization, matching, and classification.

A report says "ran pytest" while the ledger records
``uv run --no-sync python -m pytest -q tests/``. :func:`split_command` reduces
both to comparable token tuples, and :func:`segment_matches` decides whether a
claimed command is one the agent ran. The normalization:

- removes quotes and backticks and lowercases everything;
- splits on ``&&``, ``||``, ``;``, ``|`` and newlines, and drops ``cd`` steps;
- drops leading environment assignments and wrappers (``env``, ``time``,
  ``sudo``, ``exec``, ``command``, ``nohup``);
- strips runner prefixes (``uv run``, ``poetry run``, ``pipenv run``,
  ``pdm run``, ``pnpm exec``, ``npx``, ``bunx``, ``python -m``) together with
  the runner's own leading options (``--no-sync``, ``-y``);
- reduces the program to its basename, ``python3.11`` to ``python``, and
  ``npm run test`` to ``npm test`` (also for yarn, pnpm, and bun);
- drops shell redirections (``2>&1``, ``> out.txt``, ``<in``);
- strips ``./`` and trailing ``/`` from arguments.

On the claimed side, :func:`core_segments` also ignores output filters in a
pipeline (``| tail -20``, ``| grep FAILED``) when another command remains.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

Segment = tuple[str, ...]
GenericKind = Literal["test", "lint", "typecheck", "build"]

_SEPARATORS = re.compile(r"&&|\|\||;|\||\n")
_QUOTES = str.maketrans("", "", "'\"`")
_ENV_ASSIGN = re.compile(r"^[a-z_][a-z0-9_]*=", re.IGNORECASE)
_PYTHON = re.compile(r"^python(\d+(\.\d+)?)?$")
_WRAPPERS = frozenset({"env", "time", "sudo", "exec", "command", "nohup"})
_RUNNERS: tuple[Segment, ...] = (
    ("uv", "run"),
    ("poetry", "run"),
    ("pipenv", "run"),
    ("pdm", "run"),
    ("pnpm", "exec"),
    ("npx",),
    ("bunx",),
    ("python", "-m"),
)
_PACKAGE_MANAGERS = frozenset({"npm", "yarn", "pnpm", "bun"})
_REDIRECT = re.compile(r"^(\d*|&)(>>?|<)")
_BARE_REDIRECT = re.compile(r"^(\d*|&)(>>?|<)$")
_OUTPUT_FILTERS = frozenset(
    {"tail", "head", "grep", "egrep", "rg", "tee", "less", "more", "cat", "wc", "sort", "uniq"}
    | {"cut", "awk", "sed", "tr", "column", "jq", "xargs"}
)

_TEST_PROGRAMS = frozenset(
    {"pytest", "py.test", "jest", "vitest", "mocha", "ava", "unittest", "nose2", "tox", "nox"}
)
_LINT_PROGRAMS = frozenset(
    {"ruff", "flake8", "pylint", "eslint", "pycodestyle", "pyflakes", "biome", "oxlint"}
)
_TYPECHECK_PROGRAMS = frozenset({"mypy", "pyright", "basedpyright", "pytype", "tsc"})

_GENERIC_PATTERNS: tuple[tuple[GenericKind, re.Pattern[str]], ...] = (
    (
        "test",
        re.compile(
            r"^(the |all the |all |my |our )?"
            r"((full|whole|entire|complete|existing|new|unit|integration|relevant|"
            r"python|typescript|javascript|js|ts|project) )*"
            r"(test suite|test-suite|testsuite|tests?|specs?|suite)$"
        ),
    ),
    ("lint", re.compile(r"^(the )?(linters?|lint|linting|lint checks?|style checks?)$")),
    (
        "typecheck",
        re.compile(r"^(the )?(type ?checkers?|type[- ]?checks?|type ?checking|typecheck(s|ing)?)$"),
    ),
    ("build", re.compile(r"^(the )?(builds?|build step|build script)$")),
)


def _clean_arg(token: str) -> str:
    while token.startswith("./") and len(token) > 2:
        token = token[2:]
    if len(token) > 1 and token.endswith("/"):
        token = token.rstrip("/") or token
    return token


def _drop_redirections(tokens: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
        elif _BARE_REDIRECT.match(token):
            skip = True
        elif not _REDIRECT.match(token):
            out.append(token)
    return out


def _normalize_tokens(tokens: list[str]) -> Segment:
    tokens = _drop_redirections(tokens)
    changed = True
    while changed and tokens:
        changed = False
        while tokens and (_ENV_ASSIGN.match(tokens[0]) or tokens[0] in _WRAPPERS):
            tokens = tokens[1:]
            changed = True
        if not tokens:
            break
        program = tokens[0].rsplit("/", 1)[-1] or tokens[0]
        if _PYTHON.match(program):
            program = "python"
        tokens = [program, *tokens[1:]]
        for runner in _RUNNERS:
            if tuple(tokens[: len(runner)]) == runner and len(tokens) > len(runner):
                tokens = tokens[len(runner) :]
                if runner[0] != "python":
                    while tokens and tokens[0].startswith("-"):
                        tokens = tokens[1:]
                changed = True
                break
    if len(tokens) > 1 and tokens[0] in _PACKAGE_MANAGERS:
        if tokens[1] == "run" and len(tokens) > 2:
            tokens = [tokens[0], *tokens[2:]]
        if tokens[1] == "t":
            tokens = [tokens[0], "test", *tokens[2:]]
    return tuple(_clean_arg(token) for token in tokens)


def split_command(cmd: str) -> list[Segment]:
    """Split a command line into normalized token tuples, one per simple command.

    ``cd`` steps and empty pieces are dropped, so ``cd app && uv run pytest -q``
    becomes ``[("pytest", "-q")]``.
    """
    text = cmd.translate(_QUOTES).lower()
    segments: list[Segment] = []
    for part in _SEPARATORS.split(text):
        tokens = _normalize_tokens(part.split())
        if tokens and tokens[0] != "cd":
            segments.append(tokens)
    return segments


def segment_matches(claimed: Segment, recorded: Segment) -> bool:
    """True when ``recorded`` runs the claimed program with at least the claimed arguments.

    The programs must be equal; every other claimed token (flag or argument) must
    appear among the recorded tokens, which may carry extra trailing flags or
    arguments ("pytest" matches "pytest -q tests").
    """
    if not claimed or not recorded or claimed[0] != recorded[0]:
        return False
    return set(claimed[1:]) <= set(recorded[1:])


def core_segments(segments: Sequence[Segment]) -> list[Segment]:
    """Drop output filters (``tail``, ``head``, ``grep``, ``tee``, ...) unless nothing else remains.

    Used on claimed commands, so "ran ``pytest -q | tail -20``" needs only the
    ``pytest -q`` part to match a recorded command.
    """
    kept = [seg for seg in segments if seg[0] not in _OUTPUT_FILTERS]
    return kept if kept else list(segments)


def command_matches(claimed: str, recorded: str) -> bool:
    """True when every core simple command in ``claimed`` matches one in ``recorded``."""
    wanted = core_segments(split_command(claimed))
    have = split_command(recorded)
    return bool(wanted) and all(any(segment_matches(w, h) for h in have) for w in wanted)


def generic_kind(claimed: str) -> GenericKind | None:
    """Classify a generic claim such as "the tests" or "the linter", or return None."""
    text = " ".join(re.sub(r"[^a-z0-9 -]", " ", claimed.lower()).split())
    for kind, pattern in _GENERIC_PATTERNS:
        if pattern.match(text):
            return kind
    return None


def _is_test(seg: Segment) -> bool:
    program, rest = seg[0], seg[1:]
    if program in _TEST_PROGRAMS:
        return True
    if program in _PACKAGE_MANAGERS and rest[:1] == ("test",):
        return True
    if program in ("go", "cargo", "dotnet") and rest[:1] == ("test",):
        return True
    if program == "make" and "test" in rest:
        return True
    return program in ("node", "deno", "bun") and ("--test" in rest or rest[:1] == ("test",))


def _is_lint(seg: Segment) -> bool:
    program, rest = seg[0], seg[1:]
    if program in _LINT_PROGRAMS:
        return not (program == "ruff" and rest[:1] == ("format",) and "--check" not in rest)
    if program in _PACKAGE_MANAGERS and rest[:1] == ("lint",):
        return True
    return program == "make" and "lint" in rest


def _is_typecheck(seg: Segment) -> bool:
    program, rest = seg[0], seg[1:]
    if program in _TYPECHECK_PROGRAMS:
        return True
    if program in _PACKAGE_MANAGERS and rest[:1] in (("typecheck",), ("type-check",)):
        return True
    return program == "make" and "typecheck" in rest


def _is_build(seg: Segment) -> bool:
    program, rest = seg[0], seg[1:]
    if program in ("tsc", "build", "webpack"):
        return True
    if program in _PACKAGE_MANAGERS and rest[:1] == ("build",):
        return True
    builders = ("make", "uv", "cargo", "go", "hatch", "poetry", "vite", "next", "pdm", "dotnet")
    return program in builders and rest[:1] == ("build",)


_CLASSIFIERS = {
    "test": _is_test,
    "lint": _is_lint,
    "typecheck": _is_typecheck,
    "build": _is_build,
}


def command_is(kind: GenericKind, cmd: str) -> bool:
    """True when any simple command in ``cmd`` is of ``kind``.

    Build commands are ``npm run build`` (and the yarn, pnpm, and bun forms),
    ``tsc``, ``python -m build``, ``uv build``, ``make build``, ``cargo build``,
    ``go build``, ``hatch build``, ``poetry build``, ``vite build``,
    ``next build``, and ``webpack``.
    """
    check = _CLASSIFIERS[kind]
    return any(check(seg) for seg in split_command(cmd))


def describe(segments: Sequence[Segment]) -> str:
    """Join normalized segments back into one readable command string."""
    return " && ".join(" ".join(seg) for seg in segments)
