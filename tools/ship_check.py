#!/usr/bin/env python3
"""``make ship-check``: the 14 Definition-of-Done gates (docs/BUILD_BRIEF.md section 6).

Order of work:

1. In the original checkout, check the parts of G14 that concern it: the working
   tree is clean (and no tracked file hides a change behind a skip-worktree or
   assume-unchanged bit), nothing under ``private/`` is tracked, ``private/`` is
   ignored, and any private hash manifest matches.
2. Clone HEAD into a temporary directory and run every other check there, so
   only committed state counts. Sub-commands see the caller's environment minus
   the variables that would change what runs or what counts there (an import
   path, pytest or coverage options, make overrides, another project or venv),
   and every make command line pins ``PY=3.11`` and ``PYTEST_ARGS`` (D14, D16).

It verifies banked artifacts (presence, provenance, hashes, preregistration
links, thresholds) and recomputes statistics from them. It never runs an
experiment and never calls a model. It writes nothing inside the working tree;
sub-command logs and the harness's own settings files (coverage and mypy
settings, a pytest trace plugin for contract tests) go to the temporary
directory, named on stderr.

stdout is exactly ``HEAD <sha> fresh-clone``, one ``G<n> <PASS|FAIL> <evidence>``
line per gate, and then ``SHIP-CHECK: PASS 14/14`` or ``SHIP-CHECK: FAIL <n>/14``.
With ``--fast`` slow steps are skipped (``make ci`` is not re-run and tests marked
``slow`` are deselected) and the last line is
``SHIP-CHECK-FAST (does not count): <n>/14``. Only a full run counts.

The artifact layout each gate reads is documented in docs/PLAN.md under
"Artifact contract". This file is stdlib-only so it runs before ``make setup``.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import ast  # noqa: E402
import fnmatch  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import posixpath  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tokenize  # noqa: E402
import tomllib  # noqa: E402
import urllib.parse  # noqa: E402
from collections import Counter  # noqa: E402
from collections.abc import Callable, Iterable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, TypeGuard  # noqa: E402

CORE_MODULES: tuple[str, ...] = ("ledger", "claims", "verify", "analysis", "hook")
COVERAGE_MIN = 85.0
DEMO_LIMIT_S = 180.0
G5_PRECISION_MIN = 0.95
G5_RECALL_MIN = 0.90
G6_MIN_TASKS = 30
G7_MIN_CONFIGS = 3
G7_MIN_FAMILIES = 2
G7_MIN_RUNS = 60
HOOK_MEDIAN_MAX_S = 5.0
REPORT_WORDS = (4000, 8000)
REQUIRED_FILES = ("LICENSE", "CITATION.cff", "SECURITY.md", "CONTRIBUTING.md")
# Hype words (rule 12), also when hyphenated, wrapped across lines, or abbreviated.
HYPE = re.compile(
    r"\b(?i:revolutionar(?:y|ies)|ground[-\s]?breaking|state[-\s]+of[-\s]+the[-\s]+art)\b"
    r"|\bSOTA\b"
)
EM_DASH = "\N{EM DASH}"
# HTML entities that GitHub renders as an em dash.
EM_DASH_ENTITY = re.compile(r"(?i)&(?:mdash|#0*8212|#x0*2014);")
MECHANISM_CLASSES = frozenset({"saw_and_reported_otherwise", "truncated_before_agent", "never_saw"})
VERDICTS = frozenset({"supported", "contradicted", "unverifiable"})
# Words that mark a smoke-run agent label as something other than an agent run (G5, G6):
# "minimal-agent/mock" has the words minimal, agent, and mock.
NON_AGENT_WORDS = frozenset(
    {
        "mock",
        "mocked",
        "fixture",
        "fixtures",
        "synthetic",
        "reference",
        "fake",
        "dummy",
        "stub",
        "scripted",
        "replay",
        "replayed",
        "canned",
        "recorded",
    }
)
HOOK_DEMO_LIMIT_S = 30.0
README_SECTIONS = (
    "what it is",
    "result",
    "how it works",
    "your own",
    "reproduc",
    "limitation",
    "disclosure",
    "related work",
    "citation",
    "license",
)
REPORT_SECTIONS = (
    "abstract",
    "introduction",
    "related work",
    "method",
    "experiment",
    "result",
    "limitation",
    "ethic",
    "reproducib",
)

# Variables that point git at another repository, index, or object store.
GIT_REPO_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)
# Caller variables that change what runs in the clone or what counts there: an import
# path, pytest or coverage options, make overrides, a shell startup file, or another
# project, directory, repository, or venv. They never reach a sub-command. Secret-named
# variables stay (secrets_scan.py looks for their values in tracked files), as do
# CAP_SHARE, PATH, HOME, and the proxy, TLS, cache, and index settings.
ENV_DROP = frozenset(
    {
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "MAKEFLAGS",
        "MFLAGS",
        "MAKEOVERRIDES",
        "GNUMAKEFLAGS",
        "MAKEFILES",
        "MAKELEVEL",
        "PY",
        "PYTEST_ARGS",
        "COV_JSON",
        "BASH_ENV",
        "ENV",
        "UV_PROJECT",
        "UV_PROJECT_ENVIRONMENT",
        "UV_WORKING_DIR",
        "UV_WORKING_DIRECTORY",
        "UV_ENV_FILE",
        "UV_NO_PROJECT",
        "UV_ISOLATED",
        "UV_PYTHON",
        "UV_NO_SYNC",
        "UV_FROZEN",
        "UV_NO_DEV",
        "UV_NO_DEFAULT_GROUPS",
        "UV_NO_EDITABLE",
        "UV_NO_INSTALL_PROJECT",
        "UV_NO_INSTALL_LOCAL",
        "UV_NO_SOURCES",
        *GIT_REPO_VARS,
    }
)
ENV_DROP_PREFIXES = ("PYTHON", "PYTEST_", "COVERAGE_", "COV_CORE_", "MYPY", "BASH_FUNC_")
# Makefile knobs fixed on every make command line, which beats the environment and
# MAKEFLAGS: Python 3.11 (D14) and the full test selection (only G1 fast mode narrows it).
MAKE_PINS = ("PY=3.11", "PYTEST_ARGS=")
# Network isolators tried in order (D9 as amended): each counts only if a child run
# under it provably cannot reach a listener on this host's loopback.
ISOLATORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unshare -rn", ("unshare", "-rn")),
    ("bwrap", ("bwrap", "--unshare-net", "--die-with-parent", "--dev-bind", "/", "/")),
    ("sandbox-exec", ("sandbox-exec", "-p", "(version 1)(allow default)(deny network*)")),
)
LOOPBACK_PROBE = (
    "import socket, sys\n"
    "s = socket.socket()\n"
    "s.settimeout(5)\n"
    "print('ISOLATED' if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) else 'CONNECTED')\n"
)
DEAD_PROXY = "http://127.0.0.1:9"
# Offline runs: RECEIPTS_OFFLINE for the model client, and dead proxies as a second
# layer under the network isolator (never instead of it).
OFFLINE_ENV = {
    "RECEIPTS_OFFLINE": "1",
    "HTTPS_PROXY": DEAD_PROXY,
    "HTTP_PROXY": DEAD_PROXY,
    "ALL_PROXY": DEAD_PROXY,
    "https_proxy": DEAD_PROXY,
    "http_proxy": DEAD_PROXY,
    "all_proxy": DEAD_PROXY,
    "NO_PROXY": "",
    "no_proxy": "",
}


class GateError(Exception):
    """Raised inside a gate check with the short evidence for its FAIL line."""


@dataclass
class CmdResult:
    """Outcome of one sub-command."""

    name: str
    returncode: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def ok(self) -> bool:
        """True when the command exited 0."""
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stdout followed by stderr, for logs."""
        return self.stdout + self.stderr

    def last_line(self) -> str:
        """Return the last non-empty stdout line (stderr carries tool warnings)."""
        lines = [line for line in self.stdout.splitlines() if line.strip()]
        return lines[-1].strip() if lines else ""

    def last_output_line(self) -> str:
        """Return the last non-empty line of stdout and then stderr (where a tool that
        refuses says why)."""
        lines = [line for line in f"{self.stdout}\n{self.stderr}".splitlines() if line.strip()]
        return lines[-1].strip() if lines else ""

    def first_line(self) -> str:
        """Return the first non-empty line of stdout, else of stderr (a tool's first error)."""
        for stream in (self.stdout, self.stderr):
            for line in stream.splitlines():
                if line.strip():
                    return line.strip()
        return ""


@dataclass
class Context:
    """Shared state for one ship-check run."""

    orig: Path
    clone: Path
    logs: Path
    fast: bool
    sha: str
    pre: dict[str, str] = field(default_factory=dict)
    results: dict[str, CmdResult] = field(default_factory=dict)
    isolator: tuple[str, list[str]] | None = None
    isolation_probed: bool = False

    def env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Environment for sub-commands: the caller's, minus what changes what runs."""
        env, _ = scrub_environment(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.update(extra or {})
        return env

    def isolation(self) -> tuple[str, list[str]] | None:
        """The network isolator for offline runs as ``(name, prefix)``, probed once."""
        if not self.isolation_probed:
            self.isolator = network_isolation()
            self.isolation_probed = True
        return self.isolator

    def run(
        self,
        name: str,
        argv: Sequence[str],
        timeout: float,
        extra_env: Mapping[str, str] | None = None,
    ) -> CmdResult:
        """Run ``argv`` in the clone, log it, and cache the result by ``name``."""
        if name in self.results:
            return self.results[name]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                list(argv),
                cwd=self.clone,
                env=self.env(extra_env),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            text = out.decode(errors="replace") if isinstance(out, bytes) else out
            code, stdout, stderr = 124, text, f"[timeout after {timeout:.0f}s]"
        except FileNotFoundError as exc:
            code, stdout, stderr = 127, "", str(exc)
        result = CmdResult(name, code, stdout, stderr, time.monotonic() - start)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        (self.logs / f"{safe}.log").write_text(
            f"$ {' '.join(argv)}\n[exit {code} in {result.seconds:.1f}s]\n"
            f"--- stdout\n{stdout}--- stderr\n{stderr}",
            encoding="utf-8",
        )
        self.results[name] = result
        return result

    def make(
        self,
        target: str,
        timeout: float,
        *args: str,
        extra_env: Mapping[str, str] | None = None,
    ) -> CmdResult:
        """Run ``make <target>`` in the clone with the Makefile knobs pinned (later args win)."""
        argv = ["make", "--no-print-directory", target, *MAKE_PINS, *args]
        return self.run(f"make-{target}", argv, timeout, extra_env)

    def python(self, name: str, script_args: Sequence[str], timeout: float) -> CmdResult:
        """Run a repository script with the clone's environment."""
        return self.run(name, ["uv", "run", "--no-sync", "python", *script_args], timeout)


# ---------------------------------------------------------------- small helpers


def scrub_environment(environ: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Split ``environ`` into what sub-commands may see and the sorted names dropped."""
    kept: dict[str, str] = {}
    dropped: list[str] = []
    for name, value in environ.items():
        if name in ENV_DROP or name.startswith(ENV_DROP_PREFIXES):
            dropped.append(name)
        else:
            kept[name] = value
    return kept, sorted(dropped)


def git_env() -> dict[str, str]:
    """The caller's environment minus the variables that point git at another repository."""
    return {name: value for name, value in os.environ.items() if name not in GIT_REPO_VARS}


def git(root: Path, *args: str) -> str:
    """Run git in ``root`` and return stdout (raises CalledProcessError on failure)."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        env=git_env(),
    ).stdout


def tracked(root: Path, *pathspecs: str) -> list[str]:
    """Tracked paths in ``root`` matching git ``pathspecs`` (a ``*`` also crosses ``/``)."""
    return [p for p in git(root, "ls-files", "-z", "--", *pathspecs).split("\0") if p]


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(directory: Path) -> str:
    """Hash a directory: sorted relative paths with each file's SHA-256."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        digest.update(f"{rel}\0{sha256_file(path)}\n".encode())
    return digest.hexdigest()


def load_json(root: Path, rel: str) -> Any:
    """Load a JSON artifact or fail the gate naming it."""
    path = root / rel
    if not path.is_file():
        raise GateError(f"{rel} missing")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError(f"{rel} is not valid JSON ({exc.msg})") from exc


def load_jsonl(root: Path, rel: str) -> list[Any]:
    """Load a JSONL artifact or fail the gate naming it."""
    path = root / rel
    if not path.is_file():
        raise GateError(f"{rel} missing")
    rows: list[Any] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise GateError(f"{rel}:{number} is not valid JSON") from exc
    return rows


def require(condition: bool, evidence: str) -> None:
    """Fail the gate with ``evidence`` unless ``condition`` holds."""
    if not condition:
        raise GateError(evidence)


def require_provenance(rel: str, data: Mapping[str, Any]) -> None:
    """Every banked artifact carries provenance with at least a git SHA and a command."""
    prov = data.get("provenance")
    require(isinstance(prov, dict), f"{rel} has no provenance")
    assert isinstance(prov, dict)
    for key in ("git_sha", "command", "created"):
        require(bool(prov.get(key)), f"{rel} provenance lacks {key}")


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_ci(successes: int, n: int) -> str:
    """Format ``successes/n`` as an estimate with its Wilson interval."""
    lo, hi = wilson(successes, n)
    est = successes / n if n else float("nan")
    return f"{est:.3f}[{lo:.3f},{hi:.3f}]"


# Markdown structure as GitHub renders it (CommonMark): fenced code may be indented up
# to three spaces and an unclosed fence runs to the end; HTML comments are invisible.
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
HEADING_LINE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
INLINE_COMMENT = re.compile(r"<!--(?!n:|/n).*?-->")
# What a text line shows that is not prose: an HTML comment other than a claimcheck
# marker, or an inline code span (a backtick run, its text within one paragraph, and a
# closing run as long). One left-to-right pass, so whichever opens first wins.
HIDDEN_INLINE = re.compile(
    INLINE_COMMENT.pattern + r"|(?<!`)(`+)(?!`)(?:(?!\n[ \t]*\n)[\s\S])+?(?<!`)\1(?!`)"
)


def _fence_opens(line: str) -> str | None:
    """The fence string if ``line`` opens a fenced code block."""
    opened = FENCE_OPEN.match(line)
    if opened is None or (opened.group(1)[0] == "`" and "`" in opened.group(2)):
        return None
    return opened.group(1)


def _fence_closes(line: str, fence: str) -> bool:
    closed = FENCE_CLOSE.match(line)
    return (
        closed is not None and closed.group(1)[0] == fence[0] and len(closed.group(1)) >= len(fence)
    )


def md_lines(text: str) -> list[tuple[str, str]]:
    """Each line of Markdown ``text`` with its kind: ``text``, ``code``, or ``comment``.

    ``code`` covers a fenced block including its fence lines; ``comment`` covers the
    lines of an HTML comment that spans lines. Single-line comments stay ``text``.
    """
    out: list[tuple[str, str]] = []
    fence: str | None = None
    in_comment = False
    for line in text.split("\n"):
        if fence is not None:
            if _fence_closes(line, fence):
                fence = None
            out.append((line, "code"))
        elif in_comment:
            out.append((line, "comment"))
            in_comment = "-->" not in line
        elif (opened := _fence_opens(line)) is not None:
            fence = opened
            out.append((line, "code"))
        else:
            visible = INLINE_COMMENT.sub("", line)
            opened_comment = re.search(r"<!--(?!n:|/n)", visible)
            if opened_comment is not None:
                in_comment = True
                out.append((visible[: opened_comment.start()], "text"))
            else:
                out.append((line, "text"))
    return out


def _heading(line: str) -> tuple[int, str] | None:
    """``(level, lowercased title)`` if ``line`` (a text line) is an ATX heading."""
    match = HEADING_LINE.match(INLINE_COMMENT.sub("", line))
    return (len(match.group(1)), match.group(2).strip().lower()) if match else None


def headings(text: str) -> list[str]:
    """Return the lowercased Markdown headings in ``text`` (not inside code or comments)."""
    found = [_heading(line) for line, kind in md_lines(text) if kind == "text"]
    return [head[1] for head in found if head is not None]


def md_sections(text: str) -> list[tuple[str, str]]:
    """``(lowercased heading, body)`` for every heading; a body runs to the next
    heading of the same or a higher level."""
    lines = md_lines(text)
    heads = [
        (index, *head)
        for index, (line, kind) in enumerate(lines)
        if kind == "text" and (head := _heading(line)) is not None
    ]
    out: list[tuple[str, str]] = []
    for number, (index, level, title) in enumerate(heads):
        end = next((i for i, lvl, _ in heads[number + 1 :] if lvl <= level), len(lines))
        out.append((title, "\n".join(line for line, _ in lines[index + 1 : end])))
    return out


def section_text(text: str, keyword: str) -> str:
    """The bodies of every section whose heading contains ``keyword``."""
    return "\n\n".join(body for title, body in md_sections(text) if keyword in title)


def strip_code(text: str) -> str:
    """Remove fenced code blocks (each becomes one empty line)."""
    out: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        if fence is not None:
            if _fence_closes(line, fence):
                fence = None
        elif (opened := _fence_opens(line)) is not None:
            fence = opened
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def _text_lines(text: str) -> str:
    """Markdown ``text`` with every line of fenced code or of a multi-line HTML comment
    made empty, so the blocks around it stay apart."""
    return "\n".join(line if kind == "text" else "" for line, kind in md_lines(text))


def visible_text(text: str) -> str:
    """Markdown ``text`` as it renders: fenced code and HTML comments removed, except the
    claimcheck markers (``<!--n:KEY-->value<!--/n-->``), whose values are visible. Apply
    it to a whole document before taking sections: a section body from
    :func:`md_sections` has lost the line that opens a multi-line comment."""
    return INLINE_COMMENT.sub("", _text_lines(text))


def visible_prose(text: str) -> str:
    """:func:`visible_text` without inline code spans either: the prose a reader follows
    links in. Claimcheck markers stay."""
    return HIDDEN_INLINE.sub("", _text_lines(text))


def names_word(text: str, word: str) -> bool:
    """True if ``word`` (an id such as ``judge-a``) is in ``text`` as a whole word, not
    as part of a longer id (letters, digits, ``_``, ``-``, and a ``.`` between them)."""
    edge = r"(?<![\w-])(?<![\w-]\.)" + re.escape(word) + r"(?![\w-])(?!\.[\w-])"
    return re.search(edge, text) is not None


HEX40 = re.compile(r"[0-9a-f]{40}")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RENAME_HOPS = 20


def git_or_none(root: Path, *args: str) -> str | None:
    """Run git in ``root``; its stdout, or None when git fails (no such path or commit)."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=git_env(),
    )
    return proc.stdout if proc.returncode == 0 else None


def is_commit(root: Path, sha: object) -> bool:
    """True if ``sha`` is the full hex name of a commit in ``root``."""
    return (
        isinstance(sha, str)
        and HEX40.fullmatch(sha) is not None
        and git_or_none(root, "cat-file", "-e", f"{sha}^{{commit}}") is not None
    )


def history_order(root: Path) -> dict[str, int]:
    """Every commit reachable from HEAD with its position, oldest first."""
    shas = git(root, "rev-list", "--reverse", "--topo-order", "HEAD").split()
    return {sha: index for index, sha in enumerate(shas)}


def first_exact_add(root: Path, rel: str) -> str | None:
    """The oldest commit that added the path ``rel`` itself (a rename into it counts)."""
    shas = git(root, "log", "--no-renames", "--diff-filter=A", "--format=%H", "--", rel).split()
    return shas[-1] if shas else None


def add_commits(root: Path, pathspecs: Sequence[str]) -> dict[str, list[str]]:
    """Every commit that added each path under ``pathspecs`` (a rename into it counts)."""
    out = git(
        root,
        "log",
        "--no-renames",
        "--diff-filter=A",
        "--name-only",
        "-z",
        "--format=%x01%H",
        "--",
        *pathspecs,
    )
    adds: dict[str, list[str]] = {}
    for record in out.split("\x01"):
        sha, _, names = record.partition("\0")
        for name in names.split("\0"):
            path = name.lstrip("\n")
            if sha and path:
                adds.setdefault(path, []).append(sha)
    return adds


def rename_sources(root: Path, sha: str) -> dict[str, str]:
    """``{new path: old path}`` for every rename in commit ``sha`` (a copy is no rename)."""
    out = git_or_none(
        root,
        "-c",
        "diff.renameLimit=0",
        "diff",
        "--find-renames",
        "--name-status",
        "-z",
        "--diff-filter=R",
        f"{sha}^1",
        sha,
    )
    tokens = (out or "").split("\0")
    return {
        tokens[i + 2]: tokens[i + 1] for i in range(0, len(tokens) - 2, 3) if tokens[i][:1] == "R"
    }


def first_added(
    root: Path, rels: Sequence[str], pathspecs: Sequence[str] | None = None
) -> dict[str, str | None]:
    """The oldest commit that added each of ``rels``, following renames into it.

    Copies are never followed. git's ``--follow`` also follows them, so it dates a new
    file by the add of an older look-alike (a held-out evaluation by the development
    evaluation it resembles). ``pathspecs`` covers ``rels`` and is read in one query.
    """
    order = history_order(root)
    adds = add_commits(root, pathspecs or rels)
    renames: dict[str, dict[str, str]] = {}

    def adds_of(path: str) -> list[str]:
        if path not in adds:
            adds[path] = add_commits(root, [path]).get(path, [])
        return adds[path]

    out: dict[str, str | None] = {}
    for rel in rels:
        found: list[str] = []
        todo: list[str] = [rel]
        seen: set[str] = set()
        while todo and len(seen) < RENAME_HOPS:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            for sha in adds_of(path):
                found.append(sha)
                if sha not in renames:
                    renames[sha] = rename_sources(root, sha)
                source = renames[sha].get(path)
                if source is not None:
                    todo.append(source)
        known = [sha for sha in found if sha in order]
        out[rel] = min(known, key=order.__getitem__) if known else None
    return out


def commits_after(root: Path, since: str, rel: str) -> list[str]:
    """Commits after ``since`` (up to HEAD) that touch ``rel``."""
    return git(root, "log", "--format=%H", f"{since}..HEAD", "--", rel).split()


def strictly_before(root: Path, older: str, newer: str) -> bool:
    """True if commit ``older`` is a strict ancestor of commit ``newer``."""
    if older == newer:
        return False
    proc = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
        check=False,
        env=git_env(),
    )
    return proc.returncode == 0


LOCK_REL = "prereg/LOCK.json"


def lock_entries(text: str | None) -> dict[str, str]:
    """``{preregistration: locked sha256}`` from a prereg/LOCK.json text ({} if unreadable)."""
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        e["file"]: str(e.get("sha256", ""))
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("file"), str)
    }


def frozen_preregs(root: Path) -> dict[str, str]:
    """The preregistrations prereg/LOCK.json freezes at HEAD, with their locked SHA-256."""
    path = root / LOCK_REL
    return lock_entries(path.read_text(encoding="utf-8")) if path.is_file() else {}


def freeze_commit(root: Path, prereg: str) -> str | None:
    """The first commit whose prereg/LOCK.json lists ``prereg`` (its freeze commit)."""
    for sha in git(root, "log", "--reverse", "--topo-order", "--format=%H", "--", LOCK_REL).split():
        if prereg in lock_entries(git_or_none(root, "show", f"{sha}:{LOCK_REL}")):
            return sha
    return None


def repo_path(rel: object) -> str | None:
    """``rel`` as a normalized path inside the repository; None if absolute or outside."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel:
        return None
    norm = posixpath.normpath(rel)
    return None if norm in (".", "..") or norm.startswith("../") else norm


def is_number(value: object) -> TypeGuard[int | float]:
    """A finite JSON number; a boolean is not one."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def is_count(value: object) -> TypeGuard[int]:
    """A non-negative JSON integer; a boolean is not one."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_text(value: object) -> TypeGuard[str]:
    """A string with something other than white space in it."""
    return isinstance(value, str) and bool(value.strip())


def close(value: object, want: float) -> bool:
    """True if ``value`` is a number within 1e-9 of ``want``."""
    return is_number(value) and abs(float(value) - want) < 1e-9


def has_content(body: str, *, code: bool = False) -> bool:
    """True if a section body says something: a visible word outside headings, HTML
    comments, and (unless ``code``) fenced code."""
    for line, kind in md_lines(body):
        if kind == "code" and code and _fence_opens(line) is None and re.search(r"\w", line):
            return True
        visible = INLINE_COMMENT.sub("", line)
        if kind == "text" and _heading(line) is None and re.search(r"[A-Za-z]{2,}", visible):
            return True
    return False


def has_section(text: str, title: re.Pattern[str], *, code: bool = False) -> bool:
    """True if ``text`` has a heading matching ``title`` whose section has content."""
    return any(
        title.search(head) and has_content(body, code=code) for head, body in md_sections(text)
    )


def isolates(prefix: Sequence[str]) -> bool:
    """True if a child run under ``prefix`` cannot reach a listener on 127.0.0.1.

    A control run without the prefix must reach the same listener, so a probe that
    cannot connect for some other reason proves nothing.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        probe = [sys.executable, "-I", "-c", LOOPBACK_PROBE, str(server.getsockname()[1])]
        try:
            control = subprocess.run(probe, capture_output=True, text=True, timeout=30)
            inside = subprocess.run([*prefix, *probe], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
    return (
        control.stdout.strip() == "CONNECTED"
        and inside.returncode == 0
        and inside.stdout.strip() == "ISOLATED"
    )


def network_isolation() -> tuple[str, list[str]] | None:
    """Return ``(name, prefix)`` of the first isolator that provably cuts the network."""
    for name, argv in ISOLATORS:
        exe = shutil.which(argv[0])
        if exe is not None and isolates([exe, *argv[1:]]):
            return name, [exe, *argv[1:]]
    return None


# ---------------------------------------------------------------- pre-phase (G14)


def pre_phase(orig: Path) -> dict[str, str]:
    """Check the original checkout; returns problems keyed by check name."""
    problems: dict[str, str] = {}
    dirty: list[str] = []
    status = git(orig, "status", "--porcelain", "--untracked-files=all")
    if status.strip():
        dirty.append(f"working tree not clean ({len(status.splitlines())} entries)")
    # git status trusts these index bits, so a changed file behind one looks clean.
    hidden = [
        line
        for line in git(orig, "ls-files", "-v").splitlines()
        if line[:1] == "S" or line[:1].islower()
    ]
    if hidden:
        dirty.append(f"{len(hidden)} tracked file(s) marked skip-worktree or assume-unchanged")
    if dirty:
        problems["clean"] = "; ".join(dirty)
    tracked_private = git(orig, "ls-files", "--", "private").split()
    if tracked_private:
        problems["private"] = f"{len(tracked_private)} file(s) under private/ are tracked"
    ignored = subprocess.run(
        ["git", "-C", str(orig), "check-ignore", "-q", "private/probe"],
        check=False,
        env=git_env(),
    )
    if ignored.returncode != 0:
        problems["private-ignore"] = "private/ is not git-ignored"
    manifest = orig / "artifacts" / "private_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for rel, digest in dict(data.get("files", {})).items():
            path = orig / str(rel)
            if not str(rel).startswith("private/"):
                problems["manifest"] = f"private manifest lists {rel} outside private/"
            elif not path.is_file() or sha256_file(path) != digest:
                problems["manifest"] = f"private manifest mismatch for {rel}"
    return problems


# ---------------------------------------------------------------- G1

# Coverage settings owned by the harness, so the project's own coverage config (any
# file, any omit, include, or exclusion) cannot drop code from the measurement. The
# only exclusions are coverage 7's defaults for never-executed typing stubs (``...``
# bodies) and ``if TYPE_CHECKING:`` blocks; ``# pragma: no cover`` is not honored.
COVERAGE_STUB_EXCLUDES = (
    r"^\s*(((async )?def .*?)?[\])]+(\s*->.*?)?:\s*)?\.\.\.\s*(#|$)",
    r"^\s*if (typing\.)?TYPE_CHECKING:",
)
# coverage.py's own filter for source file names in a measured package directory.
COVERAGE_FILE_NAME = re.compile(r"^[^.#~!$@%^&*()+=,]+\.pyw?$")
CONTRACT_PLUGIN_MODULE = "ship_check_contract_trace"
CONTRACT_PLUGIN = '''\
"""pytest plugin written by tools/ship_check.py (gate G1) for one contract-test run.

It records each test outcome, the lines run in the omitted package files, and every
file opened under tests/fixtures/recorded/, and writes them as JSON to the path in
SHIP_CHECK_TRACE_OUT. It changes nothing about the run itself.
"""

import json
import os
import sys
import threading

import pytest

OUT = os.environ["SHIP_CHECK_TRACE_OUT"]
TARGETS = frozenset(json.loads(os.environ["SHIP_CHECK_TRACE_TARGETS"]))
FIXTURES = os.environ["SHIP_CHECK_TRACE_FIXTURES"].rstrip(os.sep) + os.sep
COUNTS = {"passed": 0, "skipped": 0, "failed": 0}
LINES = {}
OPENED = set()
REAL = {}


def _real(filename):
    real = REAL.get(filename)
    if real is None:
        real = REAL[filename] = os.path.realpath(filename)
    return real


def _local(frame, event, arg):
    if event == "line":
        LINES.setdefault(_real(frame.f_code.co_filename), set()).add(frame.f_lineno)
    return _local


def _global(frame, event, arg):
    if event == "call" and _real(frame.f_code.co_filename) in TARGETS:
        LINES.setdefault(_real(frame.f_code.co_filename), set()).add(frame.f_lineno)
        return _local
    return None


def _audit(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    try:
        path = os.path.realpath(os.fsdecode(args[0]))
    except (TypeError, ValueError, OSError):
        return
    if path.startswith(FIXTURES):
        OPENED.add(path)


def pytest_configure(config):
    sys.addaudithook(_audit)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    previous, previous_thread = sys.gettrace(), threading.gettrace()
    sys.settrace(_global)
    threading.settrace(_global)
    try:
        yield
    finally:
        sys.settrace(previous)
        threading.settrace(previous_thread)


def pytest_runtest_logreport(report):
    if hasattr(report, "wasxfail") or report.skipped:
        COUNTS["skipped"] += 1
    elif report.failed:
        COUNTS["failed"] += 1
    elif report.when == "call":
        COUNTS["passed"] += 1


def pytest_collectreport(report):
    if report.failed:
        COUNTS["failed"] += 1
    elif report.skipped:
        COUNTS["skipped"] += 1


def pytest_sessionfinish(session, exitstatus):
    payload = {
        "counts": COUNTS,
        "lines": {path: sorted(lines) for path, lines in LINES.items()},
        "opened": sorted(OPENED),
        "exitstatus": int(exitstatus),
    }
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
'''


def tracked_package_sources(root: Path) -> list[str]:
    """Tracked ``src/receipts`` source files, as coverage.py would find them."""
    return [
        rel
        for rel in tracked(root, "src/receipts/*.py")
        if COVERAGE_FILE_NAME.match(posixpath.basename(rel))
    ]


def write_coverage_settings(ctx: Context) -> tuple[Path, Path]:
    """Write the harness-owned coverage settings; return ``(rcfile, data file)``."""
    data = ctx.logs / "g1.coverage"
    rcfile = ctx.logs / "g1.coveragerc"
    rcfile.write_text(
        "# Written by tools/ship_check.py (gate G1): measure every package file.\n"
        "[run]\nsource = receipts\nbranch = false\n"
        f"data_file = {data}\n\n"
        "[report]\ninclude_namespace_packages = true\nexclude_lines =\n"
        + "".join(f"    {pattern}\n" for pattern in COVERAGE_STUB_EXCLUDES),
        encoding="utf-8",
    )
    return rcfile, data


def measured_files(root: Path, report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Coverage summaries keyed by path relative to ``root`` (files elsewhere dropped)."""
    base = Path(os.path.realpath(root))
    out: dict[str, Mapping[str, Any]] = {}
    for name, info in dict(report.get("files", {})).items():
        path = Path(os.path.realpath(base / str(name)))
        if path.is_relative_to(base) and isinstance(info, dict):
            out[path.relative_to(base).as_posix()] = dict(info.get("summary", {}))
    return out


def coverage_omissions(ctx: Context, sources: Sequence[str]) -> dict[str, str]:
    """Package files ``[tool.coverage.run] omit`` names, each mapped to its contract test.

    D6: an omission needs ``tests/contract/test_<stem>.py``. Patterns are resolved to
    tracked package files first, so a glob's own stem never names a contract test.
    """
    pyproject = tomllib.loads((ctx.clone / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject.get("tool", {}).get("coverage", {}).get("run", {}).get("omit", [])
    if isinstance(patterns, str):
        patterns = [patterns]
    contracts = set(tracked(ctx.clone, "tests/contract"))
    omitted: dict[str, str] = {}
    for pattern in map(str, patterns):
        absolute = pattern if pattern[:1] in "*?[/" else str(ctx.clone / pattern)
        for rel in sources:
            if fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(
                str(ctx.clone / rel), absolute
            ):
                contract = f"tests/contract/test_{Path(rel).stem}.py"
                require(
                    contract in contracts,
                    f"coverage omits {rel} without a recorded-fixture contract test ({contract})",
                )
                omitted[rel] = contract
    return omitted


def function_body_lines(source: str) -> set[int]:
    """Lines of the statements inside function bodies: what calling the code runs."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for stmt in node.body:
                lines.update(
                    inner.lineno for inner in ast.walk(stmt) if isinstance(inner, ast.stmt)
                )
    return lines


def check_contract_tests(ctx: Context, omitted: Mapping[str, str]) -> None:
    """Run each contract test alone and offline; it must pass with no skips, call code in
    every file it covers, and read a committed file under tests/fixtures/recorded/."""
    isolation = ctx.isolation()
    require(
        isolation is not None,
        "cannot run the contract tests offline: no working network isolation"
        " (unshare -rn, bwrap, sandbox-exec)",
    )
    assert isolation is not None
    method, prefix = isolation
    (ctx.logs / f"{CONTRACT_PLUGIN_MODULE}.py").write_text(CONTRACT_PLUGIN, encoding="utf-8")
    fixtures = os.path.realpath(ctx.clone / "tests" / "fixtures" / "recorded")
    recorded = {
        os.path.realpath(ctx.clone / rel) for rel in tracked(ctx.clone, "tests/fixtures/recorded")
    }
    by_test: dict[str, list[str]] = {}
    for rel, test in sorted(omitted.items()):
        by_test.setdefault(test, []).append(rel)
    for test, files in sorted(by_test.items()):
        name = re.sub(r"[^A-Za-z0-9_]", "_", Path(test).stem)
        out = ctx.logs / f"contract_{name}.json"
        targets = {os.path.realpath(ctx.clone / rel): rel for rel in files}
        env = {
            **OFFLINE_ENV,
            "PYTHONPATH": str(ctx.logs),
            "SHIP_CHECK_TRACE_OUT": str(out),
            "SHIP_CHECK_TRACE_TARGETS": json.dumps(sorted(targets)),
            "SHIP_CHECK_TRACE_FIXTURES": fixtures,
        }
        argv = [*prefix, "uv", "run", "--no-sync", "python", "-m", "pytest", "-q"]
        argv += ["-p", "no:cacheprovider", "-p", CONTRACT_PLUGIN_MODULE, test]
        result = ctx.run(f"contract-{name}", argv, 600, env)
        trace: dict[str, Any] = {}
        if out.is_file():
            loaded = json.loads(out.read_text(encoding="utf-8"))
            trace = loaded if isinstance(loaded, dict) else {}
        counts = dict(trace.get("counts", {}))
        passed, skipped, failed = (int(counts.get(k, 0)) for k in ("passed", "skipped", "failed"))
        require(
            bool(trace), f"contract test {test} did not run (exit {result.returncode}, {method})"
        )
        require(passed > 0, f"contract test {test} ran no passing test (exit {result.returncode})")
        require(
            result.ok and failed == 0,
            f"contract test {test} failed offline (exit {result.returncode}, {method})",
        )
        require(skipped == 0, f"contract test {test} skipped {skipped} test(s), so covers nothing")
        lines = dict(trace.get("lines", {}))
        for real, rel in sorted(targets.items(), key=lambda item: item[1]):
            body = function_body_lines((ctx.clone / rel).read_text(encoding="utf-8"))
            require(
                bool(body & {int(n) for n in lines.get(real, [])}),
                f"contract test {test} calls no code in {rel}",
            )
        opened = {str(p) for p in trace.get("opened", [])}
        require(
            bool(opened & recorded),
            f"contract test {test} reads no committed file under tests/fixtures/recorded/",
        )


def g1(ctx: Context) -> str:
    """Build and tests: setup, tests pass, coverage >= 85% on core modules (D6)."""
    setup = ctx.make("setup", 900)
    require(setup.ok, f"make setup failed (exit {setup.returncode})")
    sources = tracked_package_sources(ctx.clone)
    omitted = coverage_omissions(ctx, sources)
    rcfile, data = write_coverage_settings(ctx)
    cov = ctx.logs / "coverage.json"
    pytest_args = f"--cov-config={shlex.quote(str(rcfile))}"
    if ctx.fast:
        pytest_args = f"-m 'not slow' {pytest_args}"
    test = ctx.make(
        "test",
        1800,
        f"COV_JSON={cov}",
        f"PYTEST_ARGS={pytest_args}",
        extra_env={"COVERAGE_RCFILE": str(rcfile)},
    )
    require(test.ok, f"make test failed (exit {test.returncode})")
    require(data.is_file(), "make test did not measure coverage with the harness coverage settings")
    report_path = ctx.logs / "g1_coverage.json"
    settings = [f"--rcfile={rcfile}", f"--data-file={data}", "-o", str(report_path)]
    report = ctx.run(
        "g1-coverage-json",
        ["uv", "run", "--no-sync", "python", "-m", "coverage", "json", *settings],
        600,
    )
    require(
        report.ok and report_path.is_file(),
        f"coverage json failed on the measured data (exit {report.returncode})",
    )
    measured = measured_files(ctx.clone, json.loads(report_path.read_text(encoding="utf-8")))
    absent = [rel for rel in sources if rel not in measured]
    require(
        not absent,
        f"coverage report lacks {len(absent)} tracked package file(s): " + ", ".join(absent[:3]),
    )
    per_module: dict[str, list[int]] = {}
    total = [0, 0]
    for rel, summary in measured.items():
        if not rel.startswith("src/receipts/") or rel in omitted:
            continue
        covered, statements = int(summary["covered_lines"]), int(summary["num_statements"])
        total[0] += covered
        total[1] += statements
        module = rel.split("/")[2].removesuffix(".py")
        bucket = per_module.setdefault(module, [0, 0])
        bucket[0] += covered
        bucket[1] += statements
    missing = [
        m
        for m in CORE_MODULES
        if not (ctx.clone / "src" / "receipts" / m).is_dir()
        and not (ctx.clone / "src" / "receipts" / f"{m}.py").is_file()
    ]
    require(not missing, "core modules missing: " + ", ".join(missing))
    overall = 100.0 * total[0] / total[1] if total[1] else 0.0
    require(overall >= COVERAGE_MIN, f"package coverage {overall:.1f}% < {COVERAGE_MIN:.0f}%")
    low = []
    for module in CORE_MODULES:
        covered, statements = per_module.get(module, [0, 0])
        pct = 100.0 * covered / statements if statements else 0.0
        if pct < COVERAGE_MIN:
            low.append(f"{module} {pct:.1f}%")
    require(not low, "core coverage below 85%: " + ", ".join(low))
    tail = ""
    if omitted:
        check_contract_tests(ctx, omitted)
        tail = f"; {len(omitted)} omitted file(s) covered by recorded-fixture contract tests"
    return f"setup ok; tests pass; coverage {overall:.1f}%, every core module >= 85%{tail}"


# ---------------------------------------------------------------- G2

# A ``type: ignore`` comment as CPython's tokenizer and mypy read it: at the start of a
# comment, or right after a PEP 484 type comment (``# type: int  # type: ignore``).
TYPE_IGNORE = re.compile(
    r"^#[ \t]*type:(?:[^#]*#\s*type:)?[ \t]*ignore(?![A-Za-z0-9]|[^\x00-\x7f])(?P<rest>.*)$"
)
TYPE_IGNORE_OK = re.compile(r"^\[[\w,\- ]+\]\s*#\s*\S.{2,}")
# mypy reads inline settings only from lines that start with exactly this prefix.
MYPY_DIRECTIVE = "# mypy: "
MYPY_STRICTER = re.compile(
    r"^(?:warn_\w+|disallow_\w+|strict_\w+|check_untyped_defs|extra_checks"
    r"|local_partial_types|no_implicit_reexport|no_implicit_optional)$"
)
# A file-level ruff exemption as ruff honors it: an own-line comment, lowercase tool name.
FILE_NOQA = re.compile(r"^#\s*(?:ruff|flake8)\s*:\s*(?i:noqa)(?P<rest>.*)$")
NO_TYPE_CHECK = frozenset({"no_type_check", "no_type_check_decorator"})
REASON_LINE = re.compile(r"^\s*#\s*(?!(?:type:|noqa|ruff:|flake8:|fmt:|pragma|mypy:))\S.{2,}$")


def unexplained_type_ignores(source: str) -> list[int]:
    """Line numbers of ``type: ignore`` comments that lack an error code and a reason.

    Only real comments count (found with ``tokenize``), so text inside string
    literals, such as test data, is ignored. Untokenizable source reports line 0.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return [0]
    bad: list[int] = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        m = TYPE_IGNORE.match(token.string)
        if m and not TYPE_IGNORE_OK.match(m.group("rest").strip()):
            bad.append(token.start[0])
    return bad


def _mypy_options(text: str) -> list[tuple[str, str]]:
    """``(name, value)`` pairs of an inline mypy setting, split as mypy splits them."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    options = []
    for part in parts:
        name, sep, value = part.partition("=")
        if name.strip():
            options.append((name.strip().replace("-", "_"), value.strip() if sep else "True"))
    return options


def suppression_problems(rel: str, source: str) -> list[str]:
    """Suppressions that silence mypy or ruff for more than one line, as ``rel:line why``.

    A ``# mypy:`` line may only tighten settings, except ``disable-error-code``, the
    module-level form of ``type: ignore[code]``, which needs a reason on the comment
    line just before it. ``no_type_check`` and blanket file-level ``noqa`` comments
    silence whole functions or files with no code, so they always count.
    """
    problems: list[str] = []
    lines = source.split("\n")
    for number, line in enumerate(lines, start=1):
        if not line.startswith(MYPY_DIRECTIVE):
            continue
        for name, value in _mypy_options(line[len(MYPY_DIRECTIVE) :]):
            if name == "enable_error_code" or (
                MYPY_STRICTER.match(name) and value.lower() in ("true", "1", "yes", "on")
            ):
                continue
            if name == "disable_error_code":
                if number >= 2 and REASON_LINE.match(lines[number - 2]):
                    continue
                problems.append(f"{rel}:{number} disable-error-code without a reason before it")
            else:
                shown = name.replace("_", "-")
                problems.append(f"{rel}:{number} '# mypy: {shown}' relaxes --strict")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    for node in ast.walk(tree) if tree is not None else ():
        if (
            (isinstance(node, ast.Name) and node.id in NO_TYPE_CHECK)
            or (isinstance(node, ast.Attribute) and node.attr in NO_TYPE_CHECK)
            or (
                isinstance(node, ast.ImportFrom)
                and any(a.name in NO_TYPE_CHECK for a in node.names)
            )
        ):
            problems.append(f"{rel}:{node.lineno} no_type_check skips type checking")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        tokens = []
    for token in tokens:
        if token.type != tokenize.COMMENT or token.line[: token.start[1]].strip():
            continue
        noqa = FILE_NOQA.match(token.string)
        if noqa and not noqa.group("rest").lstrip().startswith(":"):
            problems.append(f"{rel}:{token.start[0]} file-level noqa silences ruff for the file")
    return problems


def ruff_config_file(root: Path) -> Path:
    """The configuration ruff reads for the repository root (its own precedence order)."""
    for name in (".ruff.toml", "ruff.toml"):
        if (root / name).is_file():
            return root / name
    return root / "pyproject.toml"


def _ruff_settings(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if path.name == "pyproject.toml":
        data = data.get("tool", {}).get("ruff", {})
    return data if isinstance(data, dict) else {}


def _ruff_glob(pattern: str, rel: str, config_dir: Path, root: Path) -> bool:
    """Whether a ruff per-file-ignores pattern selects ``rel`` (path or file name match)."""
    negated = pattern.startswith("!")
    glob = pattern[1:] if negated else pattern
    absolute = glob if Path(glob).is_absolute() else str(config_dir / glob)
    hit = fnmatch.fnmatchcase(str(root / rel), posixpath.normpath(absolute)) or (
        fnmatch.fnmatchcase(posixpath.basename(rel), glob)
    )
    return hit != negated


def ruff_blanket_ignores(root: Path, package: Sequence[str]) -> list[str]:
    """Package files a per-file-ignores entry of ``ALL`` silences (root config and extends)."""
    problems: list[str] = []
    base = Path(os.path.realpath(root))
    config: Path | None = ruff_config_file(base)
    seen: set[Path] = set()
    while config is not None and config.is_file() and config not in seen:
        seen.add(config)
        settings = _ruff_settings(config)
        lint = settings.get("lint")
        for table in (settings, lint if isinstance(lint, dict) else {}):
            for key in ("per-file-ignores", "extend-per-file-ignores"):
                entries = table.get(key)
                for pattern, codes in (entries if isinstance(entries, dict) else {}).items():
                    if "ALL" not in [str(code) for code in (codes or [])]:
                        continue
                    hits = [
                        rel for rel in package if _ruff_glob(str(pattern), rel, config.parent, base)
                    ]
                    if hits:
                        problems.append(f"ruff {key} {pattern!r} = ALL silences {hits[0]}")
        extend = settings.get("extend")
        config = (config.parent / str(extend)).resolve() if isinstance(extend, str) else None
    return problems


def write_mypy_config(ctx: Context) -> Path:
    """Harness-owned mypy settings: ``strict``, the project's search path and Python
    version, and only ``ignore_missing_imports`` overrides for modules outside receipts."""
    pyproject = tomllib.loads((ctx.clone / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("tool", {}).get("mypy", {})
    project = project if isinstance(project, dict) else {}
    paths = project.get("mypy_path", ["src"])
    paths = re.split(r"[,:]", paths) if isinstance(paths, str) else [str(p) for p in paths]
    lines = [
        "[mypy]",
        f"python_version = {project.get('python_version', '3.11')}",
        "strict = True",
        "explicit_package_bases = True",
        "mypy_path = " + ",".join(str(ctx.clone / p.strip()) for p in paths if p.strip()),
        f"cache_dir = {ctx.logs / 'g2_mypy_cache'}",
    ]
    for override in project.get("overrides", []):
        if not isinstance(override, dict) or override.get("ignore_missing_imports") is not True:
            continue
        modules = override.get("module", [])
        modules = [modules] if isinstance(modules, str) else [str(m) for m in modules]
        if modules and not any(m == "receipts" or m.startswith("receipts.") for m in modules):
            lines += ["", f"[mypy-{','.join(modules)}]", "ignore_missing_imports = True"]
    path = ctx.logs / "g2_mypy.ini"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# Benchmark task content (task repositories, variants, hidden checks, reference
# solutions): third-party code to the project (brief section 8), frozen by the task
# hashes, so G2's type-ignore rule does not cover it (DECISIONS D51).
TASK_CONTENT = "bench/tasks/"


def g2(ctx: Context) -> str:
    """Static quality on the package: ruff check, ruff format --check, mypy --strict,
    and a code and reason on every ``type: ignore`` in project code, which is every
    tracked Python file outside :data:`TASK_CONTENT` (none of them narrowed by config)."""
    ctx.make("setup", 900)
    lint = ctx.make("lint", 600)
    require(lint.ok, "ruff check or ruff format --check failed")
    types = ctx.make("typecheck", 900)
    require(types.ok, "mypy --strict failed")
    bad: list[str] = []
    for rel in tracked(ctx.clone, "*.py", "*.pyi"):
        if rel.startswith(TASK_CONTENT):
            continue
        source = (ctx.clone / rel).read_text(encoding="utf-8")
        bad.extend(f"{rel}:{line}" for line in unexplained_type_ignores(source))
    require(not bad, "type: ignore without code and reason at " + ", ".join(bad[:3]))
    package = tracked(ctx.clone, "src/receipts/*.py", "src/receipts/*.pyi")
    require(bool(package), "no tracked package files under src/receipts")
    suppressed: list[str] = []
    for rel in package:
        suppressed += suppression_problems(rel, (ctx.clone / rel).read_text(encoding="utf-8"))
    suppressed += ruff_blanket_ignores(ctx.clone, package)
    require(not suppressed, "suppression without code and reason: " + "; ".join(suppressed[:2]))
    # The package itself under the root config: explicit paths defeat every exclude,
    # --no-force-exclude defeats force-exclude, and --config skips nested configs.
    config = str(ruff_config_file(ctx.clone))
    ruff = ["uv", "run", "--no-sync", "ruff"]
    scope = ["--config", config, "--no-force-exclude", "--no-cache", *package]
    check = ctx.run("g2-ruff-check", [*ruff, "check", "--output-format", "concise", *scope], 600)
    require(check.ok, "ruff check on every package file: " + check.first_line()[:90])
    fmt = ctx.run("g2-ruff-format", [*ruff, "format", "--check", *scope], 600)
    require(fmt.ok, "ruff format --check on every package file: " + fmt.first_line()[:90])
    stubs = {rel[:-1] for rel in package if rel.endswith(".pyi")}
    modules = [rel for rel in package if rel not in stubs]  # mypy prefers the stub
    mypy_cfg = write_mypy_config(ctx)
    strict = ctx.run(
        "g2-mypy",
        ["uv", "run", "--no-sync", "mypy", "--strict", "--config-file", str(mypy_cfg), *modules],
        900,
    )
    require(strict.ok, "mypy --strict on every package file: " + strict.first_line()[:90])
    return (
        "ruff check, ruff format --check, mypy --strict clean on every package file;"
        " every type: ignore in project code has a code and reason (D51)"
    )


# ---------------------------------------------------------------- G3

CI_PARTS = ("lint", "typecheck", "test", "demo")
MATRIX_PY = re.compile(r"^\$\{\{\s*matrix\.python-version\s*\}\}$")
SETUP_WITH_PY = re.compile(
    r"""^make\s+setup\s+(["']?)PY=(["']?)\$\{\{\s*matrix\.python-version\s*\}\}\2\1$"""
)
RULE_LINE = re.compile(r"^([^\s:#=][^:#=]*?):(?![:=])\s*(.*)$")


class WorkflowError(ValueError):
    """The workflow uses YAML that the harness's small parser does not read."""


def strip_hash_comment(line: str) -> str:
    """Drop a ``#`` comment that starts ``line`` or follows whitespace, outside quotes."""
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'" and (index == 0 or line[index - 1] in " \t:[{,-"):
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
    return line.rstrip()


def _split_key(content: str) -> tuple[str, str] | None:
    """Split ``key: value`` (the key may be quoted); None if ``content`` is no such entry."""
    if content[:1] in "\"'":
        end = content.find(content[0], 1)
        if (
            end > 0
            and content[end + 1 : end + 2] == ":"
            and content[end + 2 : end + 3] in ("", " ")
        ):
            return content[1:end], content[end + 2 :]
        return None
    if content[:1] in "[{|>&*!%@`":
        return None
    for index, char in enumerate(content):
        if char == ":" and content[index + 1 : index + 2] in ("", " "):
            key = content[:index].strip()
            return (key, content[index + 1 :]) if key else None
    return None


def _is_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _scalar(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        inner = text[1:-1]
        return inner.replace("''", "'") if text[0] == "'" else inner.replace('\\"', '"')
    return text


def _flow(text: str, index: int) -> tuple[Any, int]:
    """Parse a flow collection or scalar at ``index``; return it and the next index."""
    while index < len(text) and text[index] == " ":
        index += 1
    if index >= len(text):
        raise WorkflowError("unexpected end of a flow collection")
    if text[index] in "[{":
        closer = "]" if text[index] == "[" else "}"
        items: list[Any] = []
        mapping: dict[str, Any] = {}
        index += 1
        while True:
            while index < len(text) and text[index] == " ":
                index += 1
            if text[index : index + 1] == closer:
                return (items if closer == "]" else mapping), index + 1
            value, index = _flow(text, index)
            if closer == "}":
                rest = text[index:].lstrip()
                index = len(text) - len(rest)
                if rest[:1] == ":":
                    entry, index = _flow(text, index + 1)
                    mapping[str(value)] = entry
                else:
                    mapping[str(value)] = None
            else:
                items.append(value)
            rest = text[index:].lstrip()
            index = len(text) - len(rest)
            if rest[:1] == ",":
                index += 1
            elif rest[:1] != closer:
                raise WorkflowError(f"cannot read flow collection {text!r}")
    if text[index] in "\"'":
        end = text.find(text[index], index + 1)
        if end < 0:
            raise WorkflowError("unterminated quote")
        return text[index + 1 : end], end + 1
    end = index
    while end < len(text):
        if text.startswith("${{", end):
            close = text.find("}}", end)
            end = close + 2 if close >= 0 else len(text)
            continue
        if text[end] in ",]}" or (text[end] == ":" and text[end + 1 : end + 2] in ("", " ")):
            break
        end += 1
    return text[index:end].strip(), end


class MiniYaml:
    """The block-style YAML subset GitHub workflows use: mappings, sequences, plain,
    quoted, flow, and block scalars. Anything else raises WorkflowError."""

    def __init__(self, text: str) -> None:
        self.lines = text.replace("\t", "    ").split("\n")
        self.pos = 0

    def peek(self) -> tuple[int, str] | None:
        """``(indent, content)`` of the next line with content, comments removed."""
        while self.pos < len(self.lines):
            content = strip_hash_comment(self.lines[self.pos])
            body = content.strip()
            if body and body not in ("---", "..."):
                return len(content) - len(content.lstrip(" ")), body
            self.pos += 1
        return None

    def node(self, indent: int) -> Any:
        """The node whose first line is the next line, indented at least ``indent``."""
        head = self.peek()
        if head is None or head[0] < indent:
            return None
        if _is_item(head[1]):
            return self.sequence(head[0])
        if _split_key(head[1]) is None:
            parts: list[str] = []
            while (line := self.peek()) is not None and line[0] >= head[0]:
                parts.append(line[1])
                self.pos += 1
            return _scalar(" ".join(parts))
        return self.mapping(head[0])

    def mapping(self, indent: int) -> dict[str, Any]:
        """A block mapping whose keys sit at ``indent``."""
        out: dict[str, Any] = {}
        while (head := self.peek()) is not None and head[0] == indent and not _is_item(head[1]):
            pair = _split_key(head[1])
            if pair is None:
                raise WorkflowError(f"line {self.pos + 1}: expected 'key: value'")
            self.pos += 1
            out[pair[0]] = self.value(pair[1], indent)
        if head is not None and head[0] > indent:
            raise WorkflowError(f"line {self.pos + 1}: unexpected indentation")
        return out

    def sequence(self, indent: int) -> list[Any]:
        """A block sequence whose dashes sit at ``indent``."""
        out: list[Any] = []
        while (head := self.peek()) is not None and head[0] == indent and _is_item(head[1]):
            item = head[1][1:].lstrip()
            if not item:
                self.pos += 1
                child = self.peek()
                out.append(self.node(child[0]) if child is not None and child[0] > indent else None)
            elif _is_item(item) or (item[0] not in "[{" and _split_key(item) is not None):
                column = indent + len(head[1]) - len(item)
                self.lines[self.pos] = " " * column + item
                out.append(self.node(column))
            else:
                self.pos += 1
                out.append(self.value(item, indent))
        return out

    def value(self, rest: str, indent: int) -> Any:
        """The value after ``key:`` (or ``-``) on a line indented ``indent``."""
        rest = rest.strip()
        if not rest:
            head = self.peek()
            if head is not None and head[0] > indent:
                return self.node(head[0])
            if head is not None and head[0] == indent and _is_item(head[1]):
                return self.sequence(indent)
            return None
        if rest[0] in "|>":
            return self.block_scalar(rest[0], indent)
        if rest[0] in "[{":
            text = rest
            while text.count("[") + text.count("{") > text.count("]") + text.count("}"):
                if self.pos >= len(self.lines):
                    raise WorkflowError("unclosed flow collection")
                text += " " + strip_hash_comment(self.lines[self.pos]).strip()
                self.pos += 1
            value, end = _flow(text, 0)
            if text[end:].strip():
                raise WorkflowError(f"text after a flow collection: {text[end:]!r}")
            return value
        parts = [rest]  # a plain or quoted scalar may continue on more-indented lines
        while (head := self.peek()) is not None and head[0] > indent:
            parts.append(head[1])
            self.pos += 1
        return _scalar(" ".join(parts))

    def block_scalar(self, style: str, indent: int) -> str:
        """A literal (``|``) or folded (``>``) block scalar, read verbatim."""
        body: list[str] = []
        width: int | None = None
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            if raw.strip():
                current = len(raw) - len(raw.lstrip(" "))
                if current <= indent or (width is not None and current < width):
                    break
                width = current if width is None else width
                body.append(raw[width:])
            else:
                body.append("")
            self.pos += 1
        while body and not body[-1]:
            body.pop()
        if style == ">":
            return " ".join(line.strip() for line in body if line.strip())
        return "\n".join(body) + ("\n" if body else "")


def shell_commands(script: str) -> list[str]:
    """Command lines of a ``run:`` script: comments dropped, continuations joined."""
    commands: list[str] = []
    pending = ""
    for raw in script.split("\n"):
        line = (pending + " " + strip_hash_comment(raw).strip()).strip()
        if line.endswith("\\"):
            pending = line[:-1]
            continue
        pending = ""
        if line:
            commands.append(" ".join(line.split()))
    if pending.strip():
        commands.append(" ".join(pending.split()))
    return commands


def _truthy(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in ("", "false", "0", "no", "off")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _run_shell(node: Mapping[str, Any]) -> str | None:
    shell = _mapping(_mapping(node.get("defaults")).get("run")).get("shell")
    return str(shell) if shell else None


def _leg_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True) if isinstance(value, dict | list) else str(value)


def matrix_pythons(job: Mapping[str, Any]) -> set[str]:
    """The ``python-version`` values a job's matrix runs, after exclude and include."""
    matrix = _mapping(_mapping(job.get("strategy")).get("matrix"))
    dims = [(str(k), v) for k, v in matrix.items() if k not in ("include", "exclude")]
    legs: list[dict[str, str]] = [{}] if dims else []
    for key, values in dims:
        options = values if isinstance(values, list) else [values]
        legs = [{**leg, key: _leg_value(value)} for leg in legs for value in options]
    excludes = [e for e in matrix.get("exclude") or [] if isinstance(e, dict)]
    legs = [
        leg
        for leg in legs
        if not any(all(leg.get(str(k)) == _leg_value(v) for k, v in ex.items()) for ex in excludes)
    ]
    versions = {leg.get("python-version", "") for leg in legs}
    for row in matrix.get("include") or []:
        if isinstance(row, dict) and "python-version" in row:
            versions.add(_leg_value(row["python-version"]))
    return {v for v in versions if v}


def _job_problem(
    name: str, job: Mapping[str, Any], top_env: Mapping[str, Any], top_shell: str | None
) -> tuple[int, str]:
    """``(stage, reason)`` for one job; stage 4 (reason empty) means the job qualifies."""
    commands: list[tuple[int, int, str, dict[str, Any]]] = []
    steps = job.get("steps")
    for s_index, step in enumerate(steps if isinstance(steps, list) else []):
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            for c_index, command in enumerate(shell_commands(step["run"])):
                commands.append((s_index, c_index, command, step))
    ci_runs = [entry for entry in commands if entry[2] == "make ci"]
    if not ci_runs:
        return 0, "ci.yml has no step that runs make ci"
    if not {"3.11", "3.12"} <= matrix_pythons(job):
        return 1, "ci.yml matrix lacks Python 3.11 and 3.12"
    env = {**top_env, **_mapping(job.get("env"))}
    setups = [
        (s_index, c_index)
        for s_index, c_index, command, step in commands
        if SETUP_WITH_PY.match(command)
        or (
            command == "make setup"
            and MATRIX_PY.match(str({**env, **_mapping(step.get("env"))}.get("PY", "")).strip())
        )
    ]
    if not setups:
        return 2, f"ci.yml job {name} does not pass the matrix Python to make setup"
    if "if" in job:
        return 3, f"ci.yml job {name} runs only if {job['if']}"
    if _truthy(job.get("continue-on-error")):
        return 3, f"ci.yml job {name} continues on error"
    default_shell = _run_shell(job) or top_shell
    for s_index, c_index, _, step in ci_runs:
        shell = str(step.get("shell") or default_shell or "bash")
        last = c_index == len(shell_commands(step["run"])) - 1
        if (
            any(setup < (s_index, c_index) for setup in setups)
            and "if" not in step
            and not _truthy(step.get("continue-on-error"))
            and (shell in ("bash", "sh") or last)
        ):
            return 4, ""
    return 3, (
        f"ci.yml job {name} runs make ci before make setup, conditionally,"
        " or with its failure ignored"
    )


def workflow_problem(text: str) -> str | None:
    """Why ci.yml does not run ``make ci`` after ``make setup`` with the matrix Python on
    3.11 and 3.12 in one unconditional job, or None when it does."""
    try:
        data = MiniYaml(text).node(0)
    except (WorkflowError, IndexError, RecursionError) as exc:
        return f"ci.yml is YAML the harness cannot read ({exc})"
    jobs = _mapping(data).get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return "ci.yml has no jobs"
    top = _mapping(data)
    found: list[tuple[int, str]] = []
    for name, job in jobs.items():
        if isinstance(job, dict):
            found.append(_job_problem(str(name), job, _mapping(top.get("env")), _run_shell(top)))
    best = max(found) if found else (0, "ci.yml has no jobs")
    return None if best[0] == 4 else best[1]


def make_dry_run(ctx: Context, target: str) -> list[str]:
    """The recipe lines ``make -n <target>`` prints (knobs pinned), whitespace collapsed."""
    result = ctx.run(
        f"dry-{target}", ["make", "--no-print-directory", "-n", target, *MAKE_PINS], 120
    )
    require(result.ok, f"make -n {target} failed (exit {result.returncode})")
    return [" ".join(line.split()) for line in result.stdout.splitlines() if line.strip()]


def make_rules(database: str) -> dict[str, tuple[list[str], list[str]]]:
    """``target: (prerequisites, raw recipe lines)`` from ``make -p`` output."""
    rules: dict[str, tuple[list[str], list[str]]] = {}
    recipe: list[str] | None = None
    for line in database.splitlines():
        if line.startswith("\t"):
            if recipe is not None and recipe and recipe[-1].endswith("\\"):
                recipe[-1] += "\n" + line[1:]  # a backslash continues the same command
            elif recipe is not None:
                recipe.append(line[1:])
        elif line.startswith("#"):
            continue
        elif (rule := RULE_LINE.match(line)) is not None:
            recipe = []
            prerequisites = [p for p in rule.group(2).split() if p != "|"]
            for target in rule.group(1).split():
                rules.setdefault(target, (prerequisites, recipe))
        else:
            recipe = None
    return rules


def _ignores_errors(recipe_line: str) -> bool:
    """True if a raw recipe line carries make's ``-`` (ignore errors) prefix."""
    prefix = recipe_line[: len(recipe_line) - len(recipe_line.lstrip("@+- \t"))]
    return "-" in prefix


def ignored_errors(ctx: Context, targets: Sequence[str]) -> list[str]:
    """Targets reachable from ``targets`` whose recipe ignores errors (``-`` or ``.IGNORE``)."""
    result = ctx.run(
        "make-database",
        ["make", "--no-print-directory", "-pnq", targets[0], *MAKE_PINS],
        120,
    )
    require(result.returncode in (0, 1), f"make -p failed (exit {result.returncode})")
    rules = make_rules(result.stdout)
    closure: list[str] = []
    todo = list(targets)
    while todo:
        name = todo.pop()
        if name in closure or name not in rules:
            continue
        closure.append(name)
        todo.extend(rules[name][0])
    ignore = rules.get(".IGNORE")
    if ignore is not None:
        return sorted(closure) if not ignore[0] else sorted(set(closure) & set(ignore[0]))
    return sorted(name for name in closure if any(map(_ignores_errors, rules[name][1])))


def g3(ctx: Context, gate_ok: Mapping[int, bool]) -> str:
    """CI parity: ci.yml runs make ci on 3.11 and 3.12, make ci runs lint, typecheck,
    test, and the offline demo, and make ci passes locally."""
    workflow = ctx.clone / ".github" / "workflows" / "ci.yml"
    require(workflow.is_file(), ".github/workflows/ci.yml missing")
    problem = workflow_problem(workflow.read_text(encoding="utf-8"))
    if problem is not None:
        raise GateError(problem)
    ci_lines = set(make_dry_run(ctx, "ci"))
    missing = [part for part in CI_PARTS if not set(make_dry_run(ctx, part)) <= ci_lines]
    require(not missing, "make ci does not run: " + ", ".join(missing))
    ignoring = ignored_errors(ctx, ["ci", *CI_PARTS])
    require(not ignoring, "make ci ignores errors in: " + ", ".join(ignoring))
    if ctx.fast:
        require(
            gate_ok.get(1, False) and gate_ok.get(2, False) and gate_ok.get(4, False),
            "fast: make ci parts (lint, typecheck, test, demo) do not all pass",
        )
        return "workflow ok; fast: make ci not re-run, its parts pass in G1, G2, G4"
    ci = ctx.make("ci", 3600)
    require(ci.ok, f"make ci failed (exit {ci.returncode})")
    return f"workflow runs make ci on 3.11 and 3.12; make ci passed in {ci.seconds:.0f}s"


# ---------------------------------------------------------------- G4

GOLDEN = "tests/golden/demo_output.txt"


def committed_text(ctx: Context, rel: str) -> str | None:
    """The text of ``rel`` as committed at ``ctx.sha`` (not as the working tree has it)."""
    blob = subprocess.run(
        ["git", "-C", str(ctx.clone), "cat-file", "blob", f"{ctx.sha}:{rel}"],
        capture_output=True,
        check=False,
        env=git_env(),
    )
    if blob.returncode != 0:
        return None
    return io.TextIOWrapper(io.BytesIO(blob.stdout), encoding="utf-8").read()


def g4(ctx: Context) -> str:
    """Offline demo: under 3 minutes, no network, no model calls, matches golden output."""
    ctx.make("setup", 900)
    expected = committed_text(ctx, GOLDEN)
    require(expected is not None, f"{GOLDEN} is not committed at HEAD")
    usage = ctx.clone / "artifacts" / "usage" / "ledger.jsonl"
    usage_before = sha256_file(usage) if usage.is_file() else ""
    isolation = ctx.isolation()
    require(
        isolation is not None,
        "cannot isolate the network for make demo (no working unshare -rn, bwrap, sandbox-exec)",
    )
    assert isolation is not None
    method, prefix = isolation
    demo = ctx.run(
        "demo-check",
        [*prefix, "make", "--no-print-directory", "demo", *MAKE_PINS],
        DEMO_LIMIT_S + 30,
        OFFLINE_ENV,
    )
    require(demo.ok, f"make demo failed offline (exit {demo.returncode}, {method})")
    require(demo.seconds < DEMO_LIMIT_S, f"make demo took {demo.seconds:.0f}s >= 180s")
    raw = ctx.run(
        "demo-raw",
        [*prefix, "uv", "run", "--no-sync", "python", "tools/demo.py"],
        DEMO_LIMIT_S + 30,
        OFFLINE_ENV,
    )
    require(raw.ok, "tools/demo.py failed when run without --check")
    require(raw.stdout == expected, f"demo output differs from the committed {GOLDEN}")
    after = sha256_file(usage) if usage.is_file() else ""
    require(after == usage_before, "demo logged a model call in the usage ledger")
    return f"make demo {demo.seconds:.0f}s offline ({method}); matches golden; no model calls"


# ---------------------------------------------------------------- G5

SMOKE_RUNS = "artifacts/bench/smoke_runs.json"
E0_COUNTS = "artifacts/e0/claim_type_counts.json"
E0_EVAL = "artifacts/e0/seeded_eval.json"
# The verifier mode the held-out evaluation must record (prereg 0001 section 5, Instrument
# version; DECISIONS D54; receipts.evaluation.e0.VERIFIER_MODE): each seeded report
# verified with the requirement texts of the task its ledger's run_start names. An
# evaluation in another mode did not evaluate the instrument the studies use.
E0_VERIFIER_MODE = "task_requirements"
E0_MANIFEST = "artifacts/e0/heldout_manifest.json"
E0_HELDOUT = "artifacts/e0/seeded/heldout"
E0_COMPLETENESS = "artifacts/e0/ledger_completeness.json"
# One line per scoring of the held-out half (receipts.evaluation.e0.log_attempt), so every
# attempt stays visible once committed (DECISIONS D38, D66).
E0_ATTEMPTS = "artifacts/e0/heldout_attempts.jsonl"
# The per-type counts an attempt-log line keeps for each top-five type.
ATTEMPT_COUNTS = ("correct", "predicted", "gold")
# The claim types are counted from blind labels of the real smoke reports, by labelers
# who never saw the instrument, so a common type the extractor misses still counts.
COUNT_METHOD = "blind-labels"
# The E0 scoring step, which turns a seeded report into scoring items, starts from these
# modules: the extractor and the verifier (which the E0 module imports inside its
# predict step) and the E0 module (whose scoring reads each ledger with receipts.ledger
# and matches claims with receipts.evaluation.seeded). Every file they load is part of
# the instrument (instrument_files), and HEAD must hold each unchanged since the
# evaluated commit.
INSTRUMENT_ROOTS = ("receipts.claims", "receipts.verify", "receipts.evaluation.e0")
# The E0 module's function-level imports serve its other steps (claim counting, ledger
# completeness), so only its module-level imports are followed; every other module's
# imports are followed wherever they are.
INSTRUMENT_STEP = "receipts.evaluation.e0"
Ignorable = dict[tuple[str, str], tuple[frozenset[str], tuple[int, int]]]


def require_verifier_mode(seeded: Mapping[str, Any]) -> None:
    """The held-out evaluation records that it verified every seeded report in the
    preregistered verifier mode (:data:`E0_VERIFIER_MODE`). G5 and, where they read the
    evaluation, G7 and G9 require it."""
    mode = seeded.get("verifier_mode")
    require(
        mode == E0_VERIFIER_MODE,
        f"{E0_EVAL} was not made in the preregistered verifier mode: it records "
        f"verifier_mode {mode!r}, not {E0_VERIFIER_MODE!r} (each seeded report verified "
        "with the requirement texts of its ledger's task; prereg 0001 section 5)",
    )


def is_real_agent(agent: object) -> bool:
    """True for a smoke-run agent label that names an agent: a string with a word in
    it and no word that marks a non-agent (:data:`NON_AGENT_WORDS`)."""
    if not isinstance(agent, str):
        return False
    words = set(re.findall(r"[a-z0-9]+", agent.lower()))
    return bool(words) and not words & NON_AGENT_WORDS


def real_smoke_runs(smoke: object) -> list[dict[str, Any]]:
    """The smoke-run rows that count as real agent runs, for G5 and G6 alike: marked
    ``synthetic: false``, with a real agent label and non-empty run and task ids."""
    runs = smoke.get("runs") if isinstance(smoke, dict) else None
    require(
        isinstance(runs, list) and all(isinstance(r, dict) for r in runs),
        f"{SMOKE_RUNS} runs malformed",
    )
    assert isinstance(runs, list)
    return [
        r
        for r in runs
        if r.get("synthetic") is False
        and is_real_agent(r.get("agent"))
        and is_text(r.get("run_id"))
        and is_text(r.get("task_id"))
    ]


GENESIS = "0" * 64


def ledger_events(root: Path, rel: str) -> list[dict[str, Any]]:
    """The events of a banked ledger after checking its hash chain the way
    receipts.ledger does: ``seq`` counts from 0, each ``prev`` is the hash before it
    (64 zeros first), and each ``hash`` is the SHA-256 of the canonical JSON (sorted
    keys, compact separators, UTF-8) of seq, ts, kind, data, and prev."""
    events = load_jsonl(root, rel)
    prev = GENESIS
    for index, event in enumerate(events):
        require(
            isinstance(event, dict) and isinstance(event.get("data"), dict),
            f"{rel}: event {index} is malformed",
        )
        body = {key: event.get(key) for key in ("seq", "ts", "kind", "data", "prev")}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        require(
            event.get("seq") == index and event.get("prev") == prev and event.get("hash") == digest,
            f"{rel}: hash chain broken at event {index}",
        )
        prev = digest
    return events


def payload_count(value: object) -> int:
    """A count in a ledger payload as the verifier reads it
    (``receipts.verify.facts.as_int``): a bool, an int, or a float as an int, a text of
    digits (after stripping white space, with an optional minus sign) as its value, and
    anything else as 0."""
    if isinstance(value, bool | int):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return 0


def ledger_ground_truth(events: Sequence[Mapping[str, Any]]) -> bool | None:
    """Whether every hidden check of a banked ledger passed, read as the verifier reads it
    (``receipts.verify.facts.LedgerFacts.ground_truth_success``, which banking copies into
    a row's ``ground_truth_success``): over the ``hidden_check`` events, oldest first,
    each listed check counts by its name as text, a later result for a name replacing an
    earlier one, and only ``passed: true`` is a pass. When no event lists a check, every
    event must count no failure (``failed``), and the ledger holds no result (None) when
    no event counts a check (``total``)."""
    hidden = [event["data"] for event in events if event.get("kind") == "hidden_check"]
    passed: dict[str, bool] = {}
    for data in hidden:
        checks = data.get("checks")
        for check in checks if isinstance(checks, list) else []:
            if isinstance(check, dict):
                name = check.get("name")
                passed["" if name is None else str(name)] = check.get("passed") is True
    if passed:
        return all(passed.values())
    if not any(payload_count(data.get("total")) for data in hidden):
        return None
    return all(payload_count(data.get("failed")) == 0 for data in hidden)


@dataclass(frozen=True)
class BankedRun:
    """A summary row tied to its banked run: ``run.json`` and the verified ledger."""

    row: Mapping[str, Any]
    record: Mapping[str, Any]
    events: Sequence[Mapping[str, Any]]

    @property
    def report(self) -> str:
        """The run's final report ("" when it ended without one)."""
        return str(self.record.get("report") or "")

    @property
    def driver(self) -> str:
        """The agent driver the ledger's run_start names (minimal-agent, claude-code)."""
        return str(self.events[0]["data"]["agent"])

    @property
    def model(self) -> str:
        """The model run.json and the ledger's run_start both record."""
        return str(self.record["model"])

    @property
    def agent(self) -> str:
        """``<driver>/<model>``: the agent that made the run."""
        return f"{self.driver}/{self.model}"


def banked_run(root: Path, study: str, row: Mapping[str, Any]) -> BankedRun:
    """The banked run under artifacts/studies/<study>/runs/ that a summary row names.

    Its run.json records the same run and task, its ledger's hash chain is intact and
    opens with that run's run_start, neither marks the run synthetic, and a real agent
    made it: the run_start names the driver, run.json and the run_start record the same
    model, and ``<driver>/<model>`` has no word that marks a mock, a script, a replay,
    or a fixture (:func:`is_real_agent`). So a row's ``synthetic: false`` is not taken
    on its word alone.
    """
    run_id = str(row.get("run_id"))
    require(SAFE_ID.fullmatch(run_id) is not None, f"run id {run_id!r} is not a plain name")
    base = f"artifacts/studies/{study}/runs/{run_id}"
    record = load_json(root, f"{base}/run.json")
    require(
        isinstance(record, dict)
        and record.get("run_id") == run_id
        and record.get("task_id") == row.get("task_id"),
        f"{base}/run.json does not record run {run_id} on task {row.get('task_id')}",
    )
    events = ledger_events(root, f"{base}/ledger.jsonl")
    start = dig(events[0], "data") if events else None
    require(
        bool(events)
        and events[0].get("kind") == "run_start"
        and isinstance(start, dict)
        and start.get("run_id") == run_id
        and start.get("task_id") == record.get("task_id"),
        f"{base}/ledger.jsonl does not open with the run_start of {run_id}",
    )
    assert isinstance(start, dict)
    require(
        record.get("synthetic") is not True and start.get("synthetic") is not True,
        f"{base} is marked synthetic",
    )
    driver, model = start.get("agent"), record.get("model")
    require(
        is_text(driver) and is_text(model) and start.get("model") == model,
        f"{base} does not record the driver and model that made it "
        "(the run_start's agent and model, and the same model in run.json)",
    )
    run = BankedRun(row, record, events)
    require(is_real_agent(run.agent), f"{base} was made by {run.agent!r}, which is not an agent")
    return run


def verified_smoke_runs(root: Path, smoke: object) -> list[BankedRun]:
    """The real smoke runs (:func:`real_smoke_runs`), each tied to its banked run: the
    row's agent is the run's driver and model (as the ledger's run_start and run.json
    record them) and its transcript holds an agent turn. A row that claims a real run
    the repository does not bank fails."""
    out: list[BankedRun] = []
    for row in real_smoke_runs(smoke):
        run = banked_run(root, "smoke", row)
        require(
            row.get("agent") == run.agent,
            f"smoke run {row['run_id']}: agent {row.get('agent')!r} is not the banked "
            f"{run.agent!r}",
        )
        transcript = load_json(
            root, f"artifacts/studies/smoke/runs/{row['run_id']}/transcript.json"
        )
        messages = dig(transcript, "messages")
        require(
            isinstance(messages, list)
            and any(isinstance(m, dict) and m.get("role") == "assistant" for m in messages),
            f"smoke run {row['run_id']} has no agent turn in its transcript",
        )
        out.append(run)
    return out


def blind_top_types(root: Path, reports: Mapping[str, str]) -> list[str]:
    """The five most common claim types, recounted from the blind labels of every real
    smoke run's report (never from the extractor under test). ``reports`` maps each real
    smoke run to its banked final report; every labeled claim quotes it verbatim."""
    real = set(reports)
    counts = load_json(root, E0_COUNTS)
    require_provenance(E0_COUNTS, counts)
    require(
        counts.get("method") == COUNT_METHOD,
        "claim type counts are not blind labels of the smoke reports "
        f"(method {counts.get('method')!r}, not {COUNT_METHOD!r})",
    )
    sources = counts.get("source_runs")
    require(
        isinstance(sources, list) and bool(sources) and {str(s) for s in sources} <= real,
        "claim type counts do not come from real G6 smoke runs",
    )
    labels = counts.get("labels")
    require(
        isinstance(labels, list) and all(isinstance(entry, dict) for entry in labels),
        "claim type counts have no blind labels",
    )
    ids = [entry.get("run_id") for entry in labels]
    require(
        all(is_text(i) for i in ids) and len(set(ids)) == len(ids),
        "blind labels repeat a run or lack its run_id",
    )
    labeled = {str(i) for i in ids}
    extra = sorted(labeled - real)
    require(
        not extra, "blind labels name runs that are not real smoke runs: " + ", ".join(extra[:3])
    )
    require(
        labeled == real,
        f"blind labels cover {len(labeled & real)} of the {len(real)} real smoke runs",
    )
    recount: Counter[str] = Counter()
    for entry in labels:
        claims = entry.get("claims")
        require(
            isinstance(claims, list)
            and all(isinstance(c, dict) and is_text(c.get("type")) for c in claims),
            f"blind labels of {entry.get('run_id')} lack claim types",
        )
        report = reports[str(entry["run_id"])]
        require(
            all(is_text(c.get("text")) and str(c["text"]) in report for c in claims),
            f"blind labels of {entry['run_id']} quote text that is not in its banked report",
        )
        recount.update(str(c["type"]) for c in claims)
    banked = counts.get("counts")
    require(
        isinstance(banked, dict) and all(is_count(v) for v in banked.values()),
        "claim type counts malformed",
    )
    require(
        {str(k): v for k, v in banked.items() if v} == dict(recount),
        "claim type counts do not recompute from the blind labels",
    )
    ranked = sorted(recount.items(), key=lambda kv: (-kv[1], kv[0]))
    require(len(ranked) >= 5, "fewer than five claim types counted")
    return [name for name, _ in ranked[:5]]


def module_file(root: Path, module: str) -> str | None:
    """The file under src/ that defines ``module`` (its __init__.py for a package)."""
    stem = "src/" + module.replace(".", "/")
    candidates = (f"{stem}/__init__.py", f"{stem}.py")
    return next((rel for rel in candidates if (root / rel).is_file()), None)


def imported_modules(source: str, module: str, *, package: bool, nested: bool = False) -> set[str]:
    """The receipts modules that the source of ``module`` imports, absolute or relative.

    Imports at module level count, also inside top-level ``if``, ``try``, ``with``, and
    class blocks (they run when the module loads); with ``nested``, imports inside
    functions count too. ``from m import a`` names ``m`` and ``m.a`` (``a`` may be a
    module). ``package`` says that ``module`` is a package's ``__init__.py``.
    """
    found: set[str] = set()
    todo: list[ast.AST] = list(ast.parse(source).body)
    while todo:
        node = todo.pop()
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = module.split(".") if package else module.split(".")[:-1]
                parts = parts[: len(parts) - node.level + 1]
                base = ".".join([*parts, *([node.module] if node.module else [])])
            found.add(base)
            found |= {f"{base}.{alias.name}" for alias in node.names}
        if nested or not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            todo.extend(ast.iter_child_nodes(node))
    return {name for name in found if name.split(".")[0] == "receipts"}


def instrument_files(root: Path) -> list[str]:
    """The files the E0 scoring step loads (G5): :data:`INSTRUMENT_ROOTS` and every
    receipts module they import, with the packages that hold them, followed
    transitively (:func:`imported_modules`). The ``receipts`` package's own
    ``__init__.py``, which holds only the version, is left out."""
    files: dict[str, str] = {}
    todo = list(INSTRUMENT_ROOTS)
    while todo:
        parts = todo.pop().split(".")
        for depth in range(2, len(parts) + 1):
            module = ".".join(parts[:depth])
            rel = None if module in files else module_file(root, module)
            if rel is None:
                continue
            files[module] = rel
            try:
                source = (root / rel).read_text(encoding="utf-8")
                found = imported_modules(
                    source,
                    module,
                    package=rel.endswith("/__init__.py"),
                    nested=module != INSTRUMENT_STEP,
                )
            except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
                raise GateError(f"cannot read the instrument module {rel} ({exc})") from exc
            todo.extend(found)
    missing = [module for module in INSTRUMENT_ROOTS if module not in files]
    require(not missing, "the E0 instrument is missing: " + ", ".join(missing))
    return sorted(set(files.values()))


def evaluated_instrument(root: Path, seeded: Mapping[str, Any]) -> str:
    """The commit whose instrument the held-out evaluation scored, after checking that
    HEAD holds the same instrument (every file of :func:`instrument_files` unchanged
    since that commit) and that the evaluation ran it without uncommitted changes: it
    found none in its recorded ``paths``, and those cover every instrument file."""
    instrument = seeded.get("instrument")
    require(
        isinstance(instrument, dict), "seeded_eval.json does not record the instrument it evaluated"
    )
    assert isinstance(instrument, dict)
    sha = instrument.get("commit")
    require(
        is_commit(root, sha), f"the evaluated instrument {sha!r} is not a commit of this repository"
    )
    assert isinstance(sha, str)
    require(
        instrument.get("dirty") is False and not instrument.get("uncommitted"),
        "the G5 evaluation ran on an instrument with uncommitted changes",
    )
    head = git(root, "rev-parse", "HEAD").strip()
    require(
        sha == head or strictly_before(root, sha, head),
        f"the evaluated instrument commit {sha[:12]} is not in HEAD's history",
    )
    files = instrument_files(root)
    checked = instrument.get("paths")
    prefixes = [p.rstrip("/") for p in checked if is_text(p)] if isinstance(checked, list) else []
    unchecked = [
        rel for rel in files if not any(rel == p or rel.startswith(p + "/") for p in prefixes)
    ]
    require(
        not unchecked,
        "the G5 evaluation did not check the instrument for uncommitted changes in "
        + ", ".join(unchecked[:3]),
    )
    blobs = {rev: blob_ids(root, rev, files) for rev in (sha, "HEAD")}
    changed = [rel for rel in files if blobs[sha].get(rel) != blobs["HEAD"].get(rel)]
    require(
        not changed,
        f"the instrument changed after the G5 evaluation at {sha[:12]}: " + ", ".join(changed[:5]),
    )
    return sha


def blob_ids(root: Path, rev: str, paths: Sequence[str]) -> dict[str, str]:
    """The git blob id of each of ``paths`` that exists at ``rev``."""
    out: dict[str, str] = {}
    listing = git(root, "ls-tree", "-r", "-z", "--full-tree", rev, "--", *paths)
    for entry in listing.split("\0"):
        meta, tab, rel = entry.partition("\t")
        if tab and len(meta.split()) == 3:
            out[rel] = meta.split()[2]
    return out


def frozen_heldout(root: Path) -> dict[str, str]:
    """The held-out reports as the manifest's first commit froze them, each checked
    against its file in the clone. That commit must come strictly before the
    evaluation's first commit, and no later commit may touch the manifest."""
    m_first = first_exact_add(root, E0_MANIFEST)
    e_first = first_added(root, [E0_EVAL])[E0_EVAL]
    require(
        m_first is not None and e_first is not None and strictly_before(root, m_first, e_first),
        "held-out manifest was not committed before the G5 evaluation",
    )
    assert m_first is not None
    require(
        not commits_after(root, m_first, E0_MANIFEST),
        "held-out manifest changed after its freeze commit",
    )
    try:
        frozen = json.loads(git(root, "show", f"{m_first}:{E0_MANIFEST}"))
    except json.JSONDecodeError as exc:
        raise GateError(f"{E0_MANIFEST} was not valid JSON when frozen") from exc
    reports = frozen.get("reports") if isinstance(frozen, dict) else None
    require(
        isinstance(reports, dict)
        and bool(reports)
        and all(
            isinstance(k, str) and SAFE_ID.fullmatch(k) and isinstance(v, str)
            for k, v in reports.items()
        ),
        "held-out manifest listed no reports, or a malformed one, when it was frozen",
    )
    assert isinstance(reports, dict)
    for report_id, digest in reports.items():
        path = root / E0_HELDOUT / f"{report_id}.json"
        require(
            path.is_file() and sha256_file(path) == digest,
            f"held-out report {report_id} missing or changed",
        )
    return dict(reports)


def is_span(value: object) -> TypeGuard[list[int]]:
    """A ``[start, end]`` pair of character offsets."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(is_count(v) for v in value)
        and value[0] <= value[1]
    )


def heldout_claims(
    root: Path, reports: Mapping[str, str]
) -> tuple[Counter[tuple[str, str, str]], Ignorable]:
    """The frozen gold claims of the held-out reports as a multiset of (report, type,
    verdict), and their ignored claims (dropped in adjudication) by (report, claim id)."""
    gold: Counter[tuple[str, str, str]] = Counter()
    ignorable: Ignorable = {}
    for report_id in sorted(reports):
        path = root / E0_HELDOUT / f"{report_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateError(f"held-out report {report_id} is not valid JSON") from exc
        claims = data.get("gold") if isinstance(data, dict) else None
        require(isinstance(claims, list), f"held-out report {report_id} has no gold list")
        assert isinstance(claims, list)
        for claim in claims:
            require(
                isinstance(claim, dict)
                and is_text(claim.get("claim_type"))
                and claim.get("verdict") in VERDICTS,
                f"held-out report {report_id}: a gold claim lacks a type or a known verdict",
            )
            gold[(report_id, str(claim["claim_type"]), str(claim["verdict"]))] += 1
        ignored = data.get("ignored", [])
        require(isinstance(ignored, list), f"held-out report {report_id}: ignored claims malformed")
        for claim in ignored:
            types = claim.get("claim_types") if isinstance(claim, dict) else None
            require(
                isinstance(claim, dict)
                and is_text(claim.get("claim_id"))
                and isinstance(types, list)
                and bool(types)
                and all(is_text(t) for t in types)
                and is_span(claim.get("span")),
                f"held-out report {report_id}: an ignored claim lacks an id, types, or a span",
            )
            key = (report_id, str(claim["claim_id"]))
            require(key not in ignorable, f"held-out report {report_id}: ignored claim ids repeat")
            start, end = claim["span"]
            ignorable[key] = (frozenset(str(t) for t in claim["claim_types"]), (start, end))
    return gold, ignorable


def check_ignored_item(
    report_id: str, item: Mapping[str, Any], ignorable: Ignorable, used: set[tuple[str, str]]
) -> None:
    """An item left out of scoring stands for one frozen ignored claim of its report, used
    once, with any prediction on that claim's span and of one of its types."""
    key = (report_id, str(item.get("ignored_claim_id")))
    claim = ignorable.get(key)
    require(
        claim is not None and key not in used,
        f"held-out report {report_id}: an ignored item names no frozen ignored claim, "
        "or one already used",
    )
    assert claim is not None
    used.add(key)
    require(
        item.get("gold_verdict") is None,
        f"held-out report {report_id}: an ignored item carries a gold verdict",
    )
    if item.get("pred_verdict") is None:
        return
    types, (start, end) = claim
    span = item.get("pred_span")
    on_claim = is_span(span) and min(end, span[1]) > max(start, span[0])
    require(
        str(item.get("claim_type")) in types and on_claim,
        f"held-out report {report_id}: an ignored item's prediction is not on its ignored claim",
    )


def scored_items(
    seeded: Mapping[str, Any],
    reports: Mapping[str, str],
    gold: Counter[tuple[str, str, str]],
    ignorable: Ignorable,
) -> list[dict[str, Any]]:
    """The items precision and recall are computed from. Their gold claims must be the
    frozen gold of every held-out report, none left out, added, or relabeled. An item
    marked ``ignored`` (a prediction on a claim adjudication dropped) is left out only
    when it stands for a frozen ignored claim (:func:`check_ignored_item`)."""
    items = seeded.get("items")
    require(
        isinstance(items, list) and all(isinstance(i, dict) for i in items),
        "seeded_eval.json items malformed",
    )
    assert isinstance(items, list)
    scored: list[dict[str, Any]] = []
    banked: Counter[tuple[str, str, str]] = Counter()
    used: set[tuple[str, str]] = set()
    for item in items:
        report_id = str(item.get("report_id"))
        require(
            report_id in reports, "seeded_eval items include reports outside the held-out manifest"
        )
        require(
            item.get("pred_verdict") is None or item.get("pred_verdict") in VERDICTS,
            f"held-out report {report_id}: an item has an unknown pred_verdict",
        )
        if item.get("ignored") is True:
            check_ignored_item(report_id, item, ignorable, used)
            continue
        if item.get("gold_verdict") is not None:
            banked[(report_id, str(item.get("claim_type")), str(item.get("gold_verdict")))] += 1
        scored.append(item)
    require(
        banked == gold,
        "seeded_eval gold items differ from the frozen held-out gold "
        "(gold claims left out, added, or relabeled)",
    )
    return scored


def same_json(first: object, second: object) -> bool:
    """True when two JSON values are the same value, compared as canonical JSON: a
    ``true`` is not a ``1`` and a ``1.0`` is not a ``1``, though Python's ``==`` takes
    both pairs as equal."""
    return json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def well_formed_attempt(entry: object) -> bool:
    """True for a line of the held-out attempt log as
    ``receipts.evaluation.e0.log_attempt`` writes it: a JSON object with a positive
    integer ``attempt``; ``created``, ``command``, and ``commit`` texts; ``trees``, a
    non-empty object of instrument path to git tree id (a text, or null for a path the
    commit lacks); ``passes``, an object of booleans; a boolean ``all_top5_pass``; and
    ``per_type``, an object whose entries count ``correct``, ``predicted``, and ``gold``."""
    if not isinstance(entry, dict):
        return False
    attempt, trees = entry.get("attempt"), entry.get("trees")
    passes, per_type = entry.get("passes"), entry.get("per_type")
    return (
        is_count(attempt)
        and attempt >= 1
        and all(is_text(entry.get(key)) for key in ("created", "command", "commit"))
        and isinstance(trees, dict)
        and bool(trees)
        and all(tree is None or is_text(tree) for tree in trees.values())
        and isinstance(passes, dict)
        and all(isinstance(flag, bool) for flag in passes.values())
        and isinstance(entry.get("all_top5_pass"), bool)
        and isinstance(per_type, dict)
        and all(
            isinstance(counts, dict) and all(is_count(counts.get(key)) for key in ATTEMPT_COUNTS)
            for counts in per_type.values()
        )
    )


def committed_attempts(root: Path) -> list[dict[str, Any]]:
    """The entries of the held-out attempt log as HEAD commits it (review B6, DECISIONS
    D66). The log must be committed, and no commit may have deleted it or removed or
    rewritten a line that an earlier commit holds: every committed version of the log is
    the start of the one at HEAD, so a scoring of the held-out half stays in the log once
    it is committed (D38 makes evaluate refuse to score again before the last line is
    committed). Every line must be a well-formed attempt (:func:`well_formed_attempt`)."""
    text = git_or_none(root, "show", f"HEAD:{E0_ATTEMPTS}")
    require(
        text is not None,
        f"{E0_ATTEMPTS} is not committed, so the scorings of the held-out half cannot be "
        "checked (D66)",
    )
    assert text is not None
    for sha in git(root, "log", "--full-history", "--format=%H", "--", E0_ATTEMPTS).split():
        earlier = git_or_none(root, "show", f"{sha}:{E0_ATTEMPTS}")
        require(
            earlier is not None,
            f"commit {sha[:12]} deleted {E0_ATTEMPTS}; every scoring of the held-out half "
            "stays in the log once committed (D66)",
        )
        assert earlier is not None
        require(
            text.startswith(earlier),
            f"the {E0_ATTEMPTS} committed in {sha[:12]} is not the start of the one at HEAD: "
            "a later commit removed or rewrote an attempt it logged, and every scoring of "
            "the held-out half stays in the log once committed (D66)",
        )
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            entry = None
        require(
            well_formed_attempt(entry),
            f"{E0_ATTEMPTS} line {number} is not a well-formed attempt (an object with a "
            "positive attempt, created, command, commit, trees, passes, all_top5_pass, and "
            "per_type counts, as tools/e0.py evaluate writes it)",
        )
        entries.append(entry)
    require(bool(entries), f"{E0_ATTEMPTS} logs no held-out attempt")
    return entries


def logged_fields(seeded: Mapping[str, Any]) -> dict[str, object]:
    """What ``receipts.evaluation.e0.log_attempt`` logs of the held-out evaluation: its
    instrument's ``commit`` and ``trees``, the ``correct``, ``predicted``, and ``gold``
    counts of each ``top5`` type in its ``per_type``, its ``passes``, and its
    ``all_top5_pass`` (None for what the evaluation lacks)."""
    instrument = seeded.get("instrument")
    record: Mapping[str, Any] = instrument if isinstance(instrument, dict) else {}
    per_type, top5 = seeded.get("per_type"), seeded.get("top5")
    counts: dict[str, dict[str, object]] | None = None
    if (
        isinstance(per_type, dict)
        and isinstance(top5, list)
        and all(isinstance(name, str) and isinstance(per_type.get(name), dict) for name in top5)
    ):
        counts = {name: {key: per_type[name].get(key) for key in ATTEMPT_COUNTS} for name in top5}
    return {
        "commit": record.get("commit"),
        "trees": record.get("trees"),
        "per_type": counts,
        "passes": seeded.get("passes"),
        "all_top5_pass": seeded.get("all_top5_pass"),
    }


def heldout_attempt(root: Path, seeded: Mapping[str, Any]) -> int:
    """The attempt number of the held-out evaluation, after checking it against the
    committed attempt log (review B6, DECISIONS D66): the evaluation cites the log; the
    log (:func:`committed_attempts`) numbers its attempts 1 to n in order; the evaluation
    is attempt n, and attempt n logged the evaluation's instrument commit and trees,
    per-type counts, passes, and ``all_top5_pass`` (:func:`logged_fields`, compared as
    JSON); attempt n's trees name exactly the paths the evaluation checked for
    uncommitted changes (``instrument.paths``, which :func:`evaluated_instrument` holds
    to cover every instrument file), so trees that leave a path out cannot hide a change
    to it; every attempt's trees are git's trees of those paths at its commit, so the log
    says what each attempt scored; and when n is above 1, every earlier attempt scored
    the same instrument trees as attempt n. A held-out half scored again after the
    instrument changed is no longer untouched (prereg 0001: the held-out half is scored
    once), so G5 fails on it rather than reporting it as a deviation."""
    require(
        seeded.get("attempts_log") == E0_ATTEMPTS,
        f"seeded_eval.json does not cite {E0_ATTEMPTS}, the log of every scoring of the "
        "held-out half",
    )
    entries = committed_attempts(root)
    n = len(entries)
    for number, entry in enumerate(entries, start=1):
        require(
            entry["attempt"] == number,
            f"{E0_ATTEMPTS} is not numbered 1 to {n} in order: line {number} logs attempt "
            f"{entry['attempt']}",
        )
    attempt = seeded.get("attempt")
    require(
        is_count(attempt) and attempt == n,
        f"the held-out evaluation is attempt {attempt!r}, not attempt {n}, the last one in "
        f"{E0_ATTEMPTS}: G5 reads only the latest scoring of the held-out half",
    )
    last = entries[-1]
    logged = logged_fields(seeded)
    differ = [name for name, value in logged.items() if not same_json(last.get(name), value)]
    require(
        not differ,
        f"attempt {n} of {E0_ATTEMPTS} does not log the held-out evaluation: they differ in "
        + ", ".join(differ),
    )
    instrument = seeded.get("instrument")
    checked = instrument.get("paths") if isinstance(instrument, dict) else None
    paths = {str(rel) for rel in checked} if isinstance(checked, list) else set()
    off = sorted(set(last["trees"]) ^ paths)
    require(
        bool(paths) and not off,
        f"attempt {n} of {E0_ATTEMPTS} records trees for other paths than the evaluation "
        f"checked ({', '.join(off[:3]) or 'no paths checked'}), so it does not show which "
        "instrument the held-out half was scored with",
    )
    for entry in entries:
        sha, trees = entry["commit"], entry["trees"]
        require(
            is_commit(root, sha) and git_trees(root, sha, trees) == trees,
            f"attempt {entry['attempt']} of {E0_ATTEMPTS} records instrument trees that git "
            f"does not hold at its commit {str(sha)[:12]}",
        )
    for entry in entries[:-1]:
        before, after = entry["trees"], last["trees"]
        changed = sorted(
            rel
            for rel in set(before) | set(after)
            if rel not in before or rel not in after or before[rel] != after[rel]
        )
        require(
            not changed,
            f"attempt {entry['attempt']} of {E0_ATTEMPTS} scored other instrument trees than "
            f"attempt {n} ({', '.join(changed[:3])}): the held-out half was scored again "
            "after the instrument changed, so it is no longer untouched (D66)",
        )
    return n


def rescored_heldout(ctx: Context) -> None:
    """The held-out evaluation is what the instrument at HEAD scores now (review B6,
    DECISIONS D66). ``tools/e0.py recheck``, run in the clone after ``make setup``,
    scores every report of the frozen held-out manifest again with the code
    ``tools/e0.py evaluate`` runs (``receipts.evaluation.e0.score_split``): no model
    call, no attempt logged, no file written. It exits non-zero unless the evaluation's
    items, requirement digests (``report_requirements``, D54), per-type results, top
    five, passes, ``all_top5_pass``, verifier mode, and report count are the new ones, so
    a prediction or a per-type value typed into the file, or a requirement text edited
    after the scoring, fails. Scoring needs the extractor and the verifier, which this
    stdlib-only file cannot run and must not copy; :func:`evaluated_instrument` holds the
    clone's instrument files to the evaluated ones, and the tool itself refuses to report
    a scoring made with code other than the evaluated commit's. The FAIL line quotes the
    tool's own reason from stderr (D64)."""
    setup = ctx.make("setup", 900)
    require(
        setup.ok,
        f"make setup failed in the clone (exit {setup.returncode}), so the held-out scoring "
        "was not re-run",
    )
    check = ctx.python("e0-recheck", ["tools/e0.py", "recheck"], 1800)
    said = [line.strip() for line in check.stderr.splitlines() if line.strip()]
    detail = next(
        (line for line in said if line.startswith("e0 recheck: ")),
        said[-1] if said else check.last_line(),
    )
    require(
        check.ok,
        "the held-out scoring was not reproduced in the clone (tools/e0.py recheck, exit "
        f"{check.returncode}): {detail}",
    )


# A runs directory the completeness re-derivation may read: a study's banked runs.
STUDY_RUNS_DIR = re.compile(r"artifacts/studies/[A-Za-z0-9][A-Za-z0-9._-]*/runs")


def committed_runs_dir(ctx: Context, rel: str) -> bool:
    """True if ``rel`` is a relative path, ``artifacts/studies/<study>/runs`` (so not
    absolute and without ``..``), to a directory of the clone that is committed at the
    checked commit and reached through no symlink, so it cannot point at a doctored copy."""
    if STUDY_RUNS_DIR.fullmatch(rel) is None:
        return False
    root = ctx.clone.resolve()
    path = root / rel
    return (
        path.is_dir()
        and path.resolve() == path
        and git_or_none(root, "cat-file", "-t", f"{ctx.sha}:{rel}") == "tree\n"
    )


def rederived_completeness(ctx: Context, data: Mapping[str, Any]) -> dict[str, Any]:
    """Each run's completeness row as ``tools/e0.py completeness`` derives it again, on
    the clone, from the committed transcripts and ledgers of the runs directories the
    artifact records (review N5): the gate never takes a row's transcript side from the
    artifact, where a hand edit could hide a command the ledger missed. Each recorded
    directory must be a committed study runs directory of the clone
    (:func:`committed_runs_dir`), and the tool gets one ``--runs`` with all of them (its
    ``--runs`` takes several values, and a repeated flag would keep only the last)."""
    dirs = data.get("runs_dirs")
    require(
        isinstance(dirs, list) and bool(dirs) and all(is_text(d) for d in dirs),
        f"{E0_COMPLETENESS} does not record the runs_dirs it was derived from",
    )
    assert isinstance(dirs, list)
    for entry in dirs:
        require(
            committed_runs_dir(ctx, str(entry)),
            f"{E0_COMPLETENESS} runs_dirs entry {str(entry)[:60]!r} is not a relative path to "
            "a committed artifacts/studies/<study>/runs directory in the clone",
        )
    ctx.make("setup", 900)
    out = ctx.logs / "e0-completeness.json"
    result = ctx.python(
        "e0-completeness",
        ["tools/e0.py", "completeness", "--runs", *map(str, dirs), "--out", str(out)],
        900,
    )
    require(
        result.ok and out.is_file(),
        f"tools/e0.py completeness did not re-derive {E0_COMPLETENESS}: "
        + result.last_output_line()[:80],
    )
    fresh = json.loads(out.read_text(encoding="utf-8")).get("runs")
    require(
        isinstance(fresh, list) and all(isinstance(r, dict) for r in fresh),
        "the re-derived ledger completeness has no rows",
    )
    assert isinstance(fresh, list)
    return {str(r.get("run_id")): r for r in fresh}


def ledger_completeness(
    root: Path, banked: Mapping[str, BankedRun], fresh: Mapping[str, Any]
) -> tuple[int, int, int, int]:
    """``(runs, commands compared, commands missing, unparsed actions)`` of the
    completeness artifact. It must cover every validation run (each real smoke run in
    ``banked``) and compare some command; each validation run's ``ledger_commands`` must
    be the agent commands its banked ledger records; and every row must equal its
    re-derivation in ``fresh`` (:func:`rederived_completeness`), its transcript commands
    and ``unparsed_actions`` included, with no re-derived row left out."""
    real = set(banked)
    data = load_json(root, E0_COMPLETENESS)
    require_provenance(E0_COMPLETENESS, data)
    runs = data.get("runs")
    require(
        isinstance(runs, list) and bool(runs) and all(isinstance(r, dict) for r in runs),
        "no ledger completeness validation runs",
    )
    assert isinstance(runs, list)
    ids = [r.get("run_id") for r in runs]
    require(all(is_text(i) for i in ids), "a ledger completeness row has no run_id")
    require(len(set(ids)) == len(ids), "ledger completeness lists a run more than once")
    absent = sorted(real - {str(i) for i in ids})
    require(
        not absent,
        f"ledger completeness misses {len(absent)} of the {len(real)} validation runs "
        "(the real smoke runs): " + ", ".join(absent[:3]),
    )
    extra = sorted(set(fresh) - {str(i) for i in ids})
    require(
        not extra,
        f"ledger completeness leaves out {len(extra)} run(s) that its re-derivation covers: "
        + ", ".join(extra[:3]),
    )
    compared = missing = unparsed = 0
    for run in runs:
        said, done = run.get("transcript_commands"), run.get("ledger_commands")
        require(
            isinstance(said, list) and isinstance(done, list),
            f"ledger completeness row {run['run_id']} lacks transcript_commands or ledger_commands",
        )
        assert isinstance(said, list) and isinstance(done, list)
        run_id = str(run["run_id"])
        require(
            is_count(run.get("unparsed_actions")),
            f"ledger completeness row {run_id} does not count its unparsed_actions",
        )
        require(
            dict(run) == dict(fresh.get(run_id) or {}),
            f"ledger completeness row {run_id} differs from its re-derivation from the "
            "committed transcript and ledger",
        )
        unparsed += int(run["unparsed_actions"])
        if run_id in banked:
            recorded = [
                str(e["data"].get("cmd", ""))
                for e in banked[run_id].events
                if e.get("kind") == "command" and e["data"].get("source") == "agent"
            ]
            require(
                [str(c) for c in done] == recorded,
                f"ledger completeness row {run_id}: ledger_commands are not the agent "
                "commands its banked ledger records",
            )
        compared += len(said)
        missing += sum((Counter(map(str, said)) - Counter(map(str, done))).values())
    require(compared > 0, "ledger completeness compares no commands")
    return len(runs), compared, missing, unparsed


def g5(ctx: Context) -> str:
    """Instrument validity on the held-out seeded set, plus ledger completeness. The
    recorded scoring is checked against the attempt log (:func:`heldout_attempt`) and
    re-run in the clone (:func:`rescored_heldout`), so neither the predictions nor the
    attempt history is taken on trust (review B6, DECISIONS D66)."""
    root = ctx.clone
    banked = {
        str(r.row["run_id"]): r for r in verified_smoke_runs(root, load_json(root, SMOKE_RUNS))
    }
    require(bool(banked), f"{SMOKE_RUNS} has no real agent smoke runs")
    top5 = blind_top_types(root, {run_id: run.report for run_id, run in banked.items()})
    seeded = load_json(root, E0_EVAL)
    require_provenance(E0_EVAL, seeded)
    require(seeded.get("split") == "heldout", "seeded_eval.json is not the held-out split")
    require_verifier_mode(seeded)
    require(
        seeded.get("heldout_manifest") == E0_MANIFEST,
        f"seeded_eval.json does not cite {E0_MANIFEST}",
    )
    instrument = evaluated_instrument(root, seeded)
    reports = frozen_heldout(root)
    gold, ignorable = heldout_claims(root, reports)
    items = scored_items(seeded, reports, gold, ignorable)
    attempt = heldout_attempt(root, seeded)
    rescored_heldout(ctx)
    parts: list[str] = []
    failing: list[str] = []
    for ctype in top5:
        mine = [i for i in items if i.get("claim_type") == ctype]
        golden = [i for i in mine if i.get("gold_verdict") in VERDICTS]
        pred = [i for i in mine if i.get("pred_verdict") in VERDICTS]
        correct = sum(1 for i in golden if i.get("pred_verdict") == i.get("gold_verdict"))
        if not golden or not pred:
            failing.append(f"{ctype}: no seeded claims")
            continue
        p, r = correct / len(pred), correct / len(golden)
        parts.append(f"{ctype} P={fmt_ci(correct, len(pred))} R={fmt_ci(correct, len(golden))}")
        if p < G5_PRECISION_MIN or r < G5_RECALL_MIN:
            failing.append(ctype)
    fresh = rederived_completeness(ctx, load_json(root, E0_COMPLETENESS))
    runs, compared, gaps, unparsed = ledger_completeness(root, banked, fresh)
    require(not failing, "below P>=0.95/R>=0.90: " + "; ".join(failing) + " | " + "; ".join(parts))
    require(gaps == 0, f"ledger completeness gap: {gaps} command(s) missing from ledgers")
    earlier = (
        f" ({attempt - 1} earlier attempt{'s' if attempt > 2 else ''} on the same instrument trees)"
        if attempt > 1
        else ""
    )
    return (
        "; ".join(parts)
        + f"; held-out attempt {attempt}{earlier}, its scoring re-run in the clone with the "
        "same results"
        + f"; instrument at {instrument[:12]} unchanged at HEAD"
        + f"; ledger completeness 100% on {runs} runs ({compared} commands, re-derived; "
        f"{unparsed} unparsed actions)"
    )


def g6(ctx: Context) -> str:
    """Benchmark complete: >= 30 tasks, each with hidden checks, reference, manifest, smoke run."""
    root = ctx.clone
    tasks_dir = root / "bench" / "tasks"
    tasks = sorted(p for p in tasks_dir.glob("*") if (p / "task.toml").is_file())
    require(len(tasks) >= G6_MIN_TASKS, f"{len(tasks)} tasks < {G6_MIN_TASKS}")
    validation = load_json(root, "artifacts/bench/reference_validation.json")
    require_provenance("artifacts/bench/reference_validation.json", validation)
    smoke = load_json(root, SMOKE_RUNS)
    require_provenance(SMOKE_RUNS, smoke)
    smoked = {str(run.row["task_id"]) for run in verified_smoke_runs(root, smoke)}
    checked = dict(validation.get("tasks", {}))
    problems: list[str] = []
    for task in tasks:
        tid = task.name
        hidden, reference = task / "hidden", task / "reference"
        if not hidden.is_dir() or not any(p.is_file() for p in hidden.rglob("*")):
            problems.append(f"{tid}: no hidden checks")
        if not reference.is_dir() or not any(p.is_file() for p in reference.rglob("*")):
            problems.append(f"{tid}: no reference solution")
        manifest = task / "manifest.json"
        if not manifest.is_file() or not json.loads(manifest.read_text()).get("manipulations"):
            problems.append(f"{tid}: no manipulation manifest")
        entry = checked.get(tid, {})
        if entry.get("hidden_passed") is not True or entry.get("tree_sha256") != tree_sha256(task):
            problems.append(f"{tid}: reference not validated against current task files")
        if tid not in smoked:
            problems.append(f"{tid}: no real agent smoke run")
    require(not problems, f"{len(problems)} problem(s): " + "; ".join(problems[:3]))
    return f"{len(tasks)} tasks; references pass hidden checks; manifests; smoke runs for all"


# ---------------------------------------------------------------- G7

E1_RESULTS = "artifacts/e1/results.json"
E1_RUNS = "artifacts/e1/runs.jsonl"
E1_PLAN = "artifacts/studies/e1/plan.json"
# E1's confirmatory data, first committed after the freeze (the roots tools/prereg.py uses).
E1_DATA = ("artifacts/e1", "artifacts/studies/e1/runs")
# The preregistrations' machine-readable lines (prereg 0001 and 0002 section 3): the value
# on the same line as its name, the digest in lowercase hex; the first match counts.
PLANNED_RUNS = re.compile(r"planned_runs_per_config:[ \t]*(\d+)\b")
PLAN_SHA = re.compile(r"plan_sha256:[ \t]*([0-9a-f]{64})\b")


def check_plan_digest(prereg: str, text: str, rel: str, raw: bytes) -> None:
    """The first ``plan_sha256:`` line of the frozen ``prereg`` records the SHA-256 of
    the bytes of the plan file ``rel`` (``raw``). The canonical content hash
    (``Plan.sha256()``) is not accepted, and a prereg without the line does not fix
    the plan."""
    recorded = PLAN_SHA.search(text)
    require(
        recorded is not None,
        f"{prereg} has no plan_sha256: line (the SHA-256 of the bytes of {rel}, recorded at "
        "freeze), so the plan is not shown to be the preregistered one",
    )
    assert recorded is not None
    require(
        recorded.group(1) == hashlib.sha256(raw).hexdigest(),
        f"{prereg} records a plan_sha256 that is not the SHA-256 of the bytes of {rel}",
    )


def _e1_runs(root: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(root, E1_RUNS)
    require(all(isinstance(r, dict) for r in rows), f"{E1_RUNS} has rows that are not objects")
    return [r for r in rows if isinstance(r, dict)]


def frozen_prereg(root: Path, prereg: object, cited_sha: object) -> tuple[str, str, str]:
    """``(path, text, freeze commit)`` of the preregistration an artifact cites, after
    checking that it is frozen, unchanged since, and cited with its locked SHA-256."""
    rel = repo_path(prereg)
    require(rel is not None and rel == prereg, f"the results cite no preregistration ({prereg!r})")
    assert rel is not None
    locked = frozen_preregs(root).get(rel)
    require(locked is not None, f"{rel} is not frozen in {LOCK_REL}")
    path = root / rel
    require(path.is_file(), f"{rel} missing")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == locked, f"{rel} changed after it was frozen")
    require(cited_sha == locked, f"the results cite {rel} with a SHA-256 other than its frozen one")
    fz = freeze_commit(root, rel)
    require(fz is not None, f"{rel} is in {LOCK_REL}, but no commit froze it")
    assert fz is not None
    return rel, raw.decode("utf-8", errors="replace"), fz


def committed_after_freeze(
    root: Path, prereg: str, fz: str, roots: Sequence[str], required: Sequence[str]
) -> None:
    """Every file under ``roots`` (``required`` among them) is committed, and first after
    the freeze commit ``fz``: data that predate the preregistration are not confirmatory."""
    files = tracked(root, *roots)
    absent = [rel for rel in required if rel not in files]
    require(not absent, ", ".join(absent) + " not committed")
    firsts = first_added(root, files, roots)
    after: dict[str, bool] = {}
    early: list[str] = []
    for rel in files:
        sha = firsts[rel]
        if sha is not None and sha not in after:
            after[sha] = strictly_before(root, fz, sha)
        if sha is None or not after[sha]:
            early.append(rel)
    require(
        not early,
        f"{len(early)} E1 data file(s) first committed at or before {prereg} was frozen: "
        + ", ".join(sorted(early)[:3]),
    )


Arms = dict[str, dict[str, str]]


def plan_arms(rel: str, arms: object) -> Arms:
    """A study plan's arms by config id: each arm's ``driver``, ``model``, and
    ``family`` (the agent configuration its runs must be made by)."""
    require(isinstance(arms, list), f"{rel} has no arms")
    assert isinstance(arms, list)
    out: Arms = {}
    for arm in arms:
        keys = ("config_id", "driver", "model")
        require(
            isinstance(arm, dict) and all(is_text(arm.get(k)) for k in keys),
            f"{rel} has an arm without a config_id, driver, or model",
        )
        out[str(arm["config_id"])] = {
            key: str(arm.get(key) or "") for key in ("driver", "model", "family")
        }
    return out


def check_planned_agent(run: BankedRun, arms: Arms, config: str) -> None:
    """The banked run was made by its planned arm's agent: the arm's driver and model."""
    arm = arms[config]
    planned = f"{arm['driver']}/{arm['model']}"
    require(
        run.agent == planned,
        f"{run.row['run_id']} was made by {run.agent}, not by its planned agent {planned} "
        f"({config})",
    )


def e1_plan(root: Path, prereg: str, text: str) -> tuple[dict[str, dict[str, Any]], Arms]:
    """The planned E1 runs by run id, and the arms by config id (driver, model, and
    family), from the plan the frozen preregistration fixes: its first ``plan_sha256:``
    line is the SHA-256 of the bytes of plan.json (:func:`check_plan_digest`). Every arm
    is planned for ``planned_runs_per_config`` runs, the number its first such line
    states."""
    path = root / E1_PLAN
    require(path.is_file(), f"{E1_PLAN} missing")
    raw = path.read_bytes()
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{E1_PLAN} is not valid JSON") from exc
    check_plan_digest(prereg, text, E1_PLAN, raw)
    runs = plan.get("runs") if isinstance(plan, dict) else None
    require(isinstance(runs, list), f"{E1_PLAN} has no runs")
    assert isinstance(runs, list)
    arms = plan_arms(E1_PLAN, plan.get("arms"))
    require(all(arm["family"] for arm in arms.values()), f"{E1_PLAN} has an arm without a family")
    planned: dict[str, dict[str, Any]] = {}
    for spec in runs:
        require(
            isinstance(spec, dict)
            and is_text(spec.get("run_id"))
            and is_text(spec.get("config_id"))
            and spec["config_id"] in arms,
            f"{E1_PLAN} has a run without a run_id or a planned arm",
        )
        require(str(spec["run_id"]) not in planned, f"{E1_PLAN} repeats run id {spec['run_id']}")
        planned[str(spec["run_id"])] = spec
    stated = PLANNED_RUNS.search(text)
    require(stated is not None, f"{prereg} does not state planned_runs_per_config as a number")
    assert stated is not None
    want = int(stated.group(1))
    per = Counter(str(spec["config_id"]) for spec in planned.values())
    off = [f"{c}={n}" for c, n in sorted(per.items()) if n != want]
    require(
        not off,
        f"{E1_PLAN} runs per configuration differ from planned_runs_per_config = {want}: "
        + ", ".join(off),
    )
    return planned, arms


def check_e1_rows(
    runs: Sequence[Mapping[str, Any]], planned: Mapping[str, Mapping[str, Any]], arms: Arms
) -> None:
    """Every row is a distinct planned run with its planned task, arm, conditions, and
    seed, and the model family of its planned arm. Its hidden-check result
    (``ground_truth_success``) is true, false, or null, never absent, so no run leaves
    Y1 silently, ``false_success`` is a boolean that is true only when a hidden check
    failed, and ``success_reported`` (the report's success claim) is a boolean."""
    for index, row in enumerate(runs, start=1):
        fields = ("run_id", "config_id", "model_family", "task_id")
        require(
            all(is_text(row.get(name)) for name in fields),
            f"{E1_RUNS} row {index} lacks run_id, config_id, model_family, or task_id",
        )
        claims = row.get("claims")
        require(
            isinstance(row.get("included"), bool)
            and isinstance(claims, list)
            and all(isinstance(c, dict) for c in claims),
            f"{E1_RUNS} row {index} has no included flag or claims list",
        )
        truth = row.get("ground_truth_success", "absent")
        require(
            isinstance(row.get("false_success"), bool)
            and (truth is None or isinstance(truth, bool))
            and (row["false_success"] is False or truth is False),
            f"{E1_RUNS} row {index} lacks a ground_truth_success of true, false, or null, or "
            f"a false_success flag that is true only when a hidden check failed "
            f"(ground_truth_success {truth!r}, false_success {row.get('false_success')!r})",
        )
        require(
            isinstance(row.get("success_reported"), bool),
            f"{E1_RUNS} row {index} lacks a success_reported flag (true or false), which its "
            "false_success follows from",
        )
    counts = Counter(str(row["run_id"]) for row in runs)
    repeated = sorted(rid for rid, n in counts.items() if n > 1)
    require(
        not repeated, f"{len(repeated)} run_id(s) repeat in {E1_RUNS}: " + ", ".join(repeated[:3])
    )
    for row in runs:
        rid = str(row["run_id"])
        spec = planned.get(rid)
        require(spec is not None, f"{rid} is not a planned E1 run")
        assert spec is not None
        diffs = [name for name in ("config_id", "task_id") if row.get(name) != spec.get(name)]
        if not (is_count(row.get("seed")) and row.get("seed") == spec.get("seed")):
            diffs.append("seed")
        if row.get("conditions") != spec.get("conditions"):
            diffs.append("conditions")
        require(not diffs, f"{rid} differs from its planned run in " + ", ".join(diffs))
        config, named = str(row["config_id"]), row["model_family"]
        family = arms[config]["family"]
        require(
            named == family,
            f"{rid}: model_family {named!r} is not the planned family {family!r} of {config}",
        )


def check_coverage(root: Path, study: str, rel: str, ids: Iterable[str]) -> int:
    """The rows of ``rel`` (their run ids are ``ids``) cover every run banked under
    artifacts/studies/<study>/runs/ (DECISIONS D57): each directory there that holds a
    committed file is a banked run, and each has a row. With the checks that no run id
    repeats and that every row is a banked run, the rows are one row per banked run
    (prereg 0001 section 11), so a run banked without a row never counts as a missing
    run. No committed file of a banked run may have been modified or deleted in any later
    commit (D62), so a run cannot leave the analysis by being removed or replaced after it
    was banked. Returns the number of banked runs."""
    base = f"artifacts/studies/{study}/runs/"
    # A banked run is never changed or removed afterwards: a run banked after the freeze
    # and then deleted, rewritten, or replaced by another attempt would otherwise vanish
    # from both the rows and the missing-run count.
    changed = [
        line.split("\t", 1)[1]
        for line in git(
            root,
            "log",
            "--format=",
            "--name-status",
            "--no-renames",
            "--diff-filter=MD",
            "--",
            base,
        ).splitlines()
        if "\t" in line
    ]
    require(
        not changed,
        f"{len(changed)} committed file(s) of runs banked under {base} were later changed or "
        "deleted, and a banked run is never changed or removed: "
        + ", ".join(sorted(set(changed))[:3]),
    )
    banked = {path[len(base) :].split("/", 1)[0] for path in tracked(root, base)}
    unrowed = sorted(banked - set(ids))
    require(
        not unrowed,
        f"{len(unrowed)} run(s) banked under {base} have no row in {rel}, which holds one row "
        "per banked run, so the analysis left them out: " + ", ".join(unrowed[:3]),
    )
    return len(banked)


def check_ledger_outcomes(
    rel: str, row: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> None:
    """A row of ``rel`` shows the outcomes its banked ledger ``events`` show (DECISIONS
    D57): its ``ground_truth_success`` is the ledger's hidden-check result
    (:func:`ledger_ground_truth`), and its ``false_success`` is a success claim
    (``success_reported``) with a failed hidden check, as ``receipts.study.aggregate``
    takes it from the verifier. The claims and the success claim need the instrument,
    so :func:`check_rederived` checks those."""
    rid = str(row.get("run_id"))
    try:
        truth = ledger_ground_truth(events)
    except (ValueError, OverflowError) as exc:
        raise GateError(f"{rid}: its banked ledger's hidden-check counts are unreadable") from exc
    differ = []
    if row.get("ground_truth_success") is not truth:
        differ.append("ground_truth_success")
    if row.get("false_success") is not (row.get("success_reported") is True and truth is False):
        differ.append("false_success")
    require(
        not differ,
        f"{rid} in {rel} differs from its banked ledger in {', '.join(differ)}: the ledger's "
        f"hidden checks give ground_truth_success {json.dumps(truth)}, and a false success is "
        "a success claim with a failed hidden check",
    )


def check_launch(root: Path, run: BankedRun, prereg: str, fz: str, seen: dict[str, bool]) -> str:
    """The commit a banked run was launched from (``provenance.git_sha`` in its run.json:
    the commit it ran, or the commit of its code snapshot) is a commit of this repository
    and the freeze commit ``fz`` of ``prereg`` or a later one. ``seen`` caches the
    answer for each commit. Returns the commit."""
    sha = dig(run.record, "provenance", "git_sha")
    if isinstance(sha, str) and sha not in seen:
        seen[sha] = is_commit(root, sha) and (sha == fz or strictly_before(root, fz, sha))
    require(
        isinstance(sha, str) and seen[sha],
        f"{run.row['run_id']} was launched from {str(sha)[:12]}, not from the freeze commit "
        f"of {prereg} or a later one",
    )
    assert isinstance(sha, str)
    return sha


def check_rederived(ctx: Context, study: str, rel: str) -> None:
    """The rows of ``rel`` are the rows banking writes now from the banked runs of
    ``study`` (DECISIONS D57): ``tools/bank_study.py <study> --check``, run in the clone
    after ``make setup``, re-extracts and re-verifies every banked run as banking does,
    writes nothing, and requires the committed rows to be exactly those rows, field for
    field, except the banking commit. Claims, verdicts, and success claims need the
    extractor and the verifier, which this stdlib-only file cannot run. The instrument
    trees are compared too, so the clone must hold the instrument the rows were banked
    with, which :func:`check_instruments` requires to be the evaluated one."""
    setup = ctx.make("setup", 900)
    require(
        setup.ok,
        f"make setup failed in the clone (exit {setup.returncode}), so the rows of {rel} were "
        "not re-derived from the banked runs",
    )
    check = ctx.python(f"bank-check-{study}", ["tools/bank_study.py", study, "--check"], 1800)
    # The tool's own first problem, else the last line of stderr (an error's message).
    said = [line.strip() for line in check.stderr.splitlines() if line.strip()]
    detail = next(
        (line for line in said if line.startswith("bank_study ")),
        said[-1] if said else check.last_line(),
    )
    require(
        check.ok,
        f"{rel} is not what banking writes from the banked runs (tools/bank_study.py {study} "
        f"--check, exit {check.returncode}): {detail}",
    )


def check_e1_banked(
    root: Path, runs: Sequence[Mapping[str, Any]], arms: Arms, prereg: str, fz: str
) -> int:
    """Every row is a banked E1 run (:func:`banked_run`) made by its planned arm's agent,
    with the row's arm, family, conditions, seed, inclusion (a non-empty final report),
    and ``report_sha256`` (the report the row was rescored from), launched from the
    freeze commit of ``prereg`` or a later one (:func:`check_launch`), and showing the
    ground truth and false success of its banked ledger (:func:`check_ledger_outcomes`);
    and every banked E1 run has a row (:func:`check_coverage`). Returns the number of
    banked runs."""
    after: dict[str, bool] = {}
    for row in runs:
        run = banked_run(root, "e1", row)
        check_planned_agent(run, arms, str(row["config_id"]))
        record = run.record
        diffs = [
            name
            for name in ("config_id", "seed", "conditions")
            if record.get(name) != row.get(name)
        ]
        if record.get("family") != row.get("model_family"):
            diffs.append("family")
        if bool(run.report.strip()) is not row.get("included"):
            diffs.append("included")
        if row.get("report_sha256") != text_sha256(run.report):
            diffs.append("report_sha256")
        require(
            not diffs, f"{row['run_id']} differs from its banked run.json in " + ", ".join(diffs)
        )
        check_launch(root, run, prereg, fz, after)
        check_ledger_outcomes(E1_RUNS, row, run.events)
    return check_coverage(root, "e1", E1_RUNS, (str(row["run_id"]) for row in runs))


#: A UTF-16 surrogate on its own, which the ledger stores as U+FFFD
#: (``receipts.ledger.events.stored_text``).
LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def text_sha256(text: str) -> str:
    """SHA-256 of a report's UTF-8 text as the ledger stores it (a lone surrogate as
    U+FFFD), as banking hashes the rescored report into a row's ``report_sha256``."""
    return hashlib.sha256(LONE_SURROGATE.sub("\ufffd", text).encode("utf-8")).hexdigest()


Evaluated = tuple[str, dict[str, str]]
#: The paths a banked row's instrument record binds: exactly the code re-verification
#: runs, the extractor, the verifier, and the ledger reader
#: (``receipts.study.rescore.INSTRUMENT_RECORD_PATHS``, DECISIONS D47). The held-out
#: evaluation records them among its paths.
ROW_INSTRUMENT_PATHS = ("src/receipts/claims", "src/receipts/verify", "src/receipts/ledger")


def evaluated_trees(root: Path) -> Evaluated:
    """``(commit, trees)`` of the instrument the held-out G5 evaluation scored
    (``instrument`` in artifacts/e0/seeded_eval.json), after checking that the file is
    the held-out split, made in the preregistered verifier mode
    (:func:`require_verifier_mode`), that it ran a clean instrument (``dirty`` false,
    nothing uncommitted), at a commit of this repository, and that it records a git tree
    for every path it covers, :data:`ROW_INSTRUMENT_PATHS` among them (prereg 0001
    section 5, Instrument version). ``trees`` holds the trees of
    :data:`ROW_INSTRUMENT_PATHS` only, the ones a row's instrument record must equal.
    It is the one place G7 and G9 read the evaluation's fields."""
    seeded = load_json(root, E0_EVAL)
    require(
        isinstance(seeded, dict) and seeded.get("split") == "heldout",
        f"{E0_EVAL} is not the held-out G5 evaluation (split: heldout)",
    )
    require_verifier_mode(seeded)
    instrument = seeded.get("instrument")
    require(isinstance(instrument, dict), f"{E0_EVAL} does not record the instrument it evaluated")
    assert isinstance(instrument, dict)
    sha, paths, trees = instrument.get("commit"), instrument.get("paths"), instrument.get("trees")
    require(
        is_commit(root, sha), f"the evaluated instrument {sha!r} is not a commit of this repository"
    )
    require(
        isinstance(paths, list)
        and bool(paths)
        and all(is_text(p) for p in paths)
        and isinstance(trees, dict)
        and set(trees) == set(paths)
        and all(is_text(t) for t in trees.values()),
        f"{E0_EVAL} does not record a git tree for each instrument path it covers",
    )
    require(
        instrument.get("dirty") is False and not instrument.get("uncommitted"),
        "the G5 evaluation ran on an instrument with uncommitted changes",
    )
    assert isinstance(sha, str) and isinstance(trees, dict)
    unbound = [rel for rel in ROW_INSTRUMENT_PATHS if rel not in trees]
    require(
        not unbound,
        f"{E0_EVAL} records no git tree for " + ", ".join(unbound) + ", which banked rows bind",
    )
    return sha, {rel: trees[rel] for rel in ROW_INSTRUMENT_PATHS}


def git_trees(root: Path, sha: str, paths: Iterable[str]) -> dict[str, str | None]:
    """The git object id of each of ``paths`` at commit ``sha`` (None when absent)."""
    out: dict[str, str | None] = {}
    for rel in paths:
        found = git_or_none(root, "rev-parse", "--verify", "-q", f"{sha}:{rel}")
        out[rel] = found.strip() if found else None
    return out


def check_instruments(
    root: Path, rel: str, rows: Sequence[Mapping[str, Any]], evaluated: Evaluated
) -> None:
    """Every row of ``rel`` comes from the evaluated instrument (DECISIONS D42 item 1).

    Its ``instrument`` record (``receipts.study.rescore.instrument_record`` of the
    banking checkout) has ``trees`` equal to the evaluated ones of
    :data:`ROW_INSTRUMENT_PATHS` (``evaluated``, from :func:`evaluated_trees`) and shows no
    uncommitted change, the row is not ``instrument_dirty``, and git holds the same
    trees of the instrument paths at its banking commit (``instrument.commit``) as at
    the evaluated commit. So a recorded tree that git does not hold at the recorded
    commit, in a row or in the evaluation, cannot make two instruments look equal.
    """
    sha, trees = evaluated
    paths = sorted(trees)
    want = git_trees(root, sha, paths)
    holds: dict[str, bool] = {}
    for row in rows:
        rid = str(row.get("run_id"))
        record = row.get("instrument")
        require(
            isinstance(record, dict) and record.get("trees") == trees,
            f"{rid} in {rel} was rescored by an instrument whose git trees differ from those of "
            f"the held-out G5 evaluation (instrument.commit {sha[:12]})",
        )
        assert isinstance(record, dict)
        require(
            row.get("instrument_dirty") is False
            and record.get("dirty") is False
            and record.get("uncommitted") == [],
            f"{rid} in {rel} was banked from code with uncommitted changes (instrument_dirty, "
            "or an instrument record that is dirty), so it is exploratory",
        )
        banking = record.get("commit")
        require(
            is_commit(root, banking),
            f"{rid} in {rel} records the banking commit {banking!r}, which is not a commit of "
            "this repository",
        )
        assert isinstance(banking, str)
        if banking not in holds:
            holds[banking] = git_trees(root, banking, paths) == want
        require(
            holds[banking],
            f"{rid} in {rel} was banked at {banking[:12]}, which does not hold the instrument "
            f"of the evaluated commit {sha[:12]} (git trees of {', '.join(paths)})",
        )


def check_inputs(root: Path, rel: str, artifact: Mapping[str, Any], inputs: Sequence[str]) -> None:
    """The artifact ``rel`` was computed from the committed ``inputs``: its
    ``provenance.inputs`` records the SHA-256 of each of these files, as the analyses
    record every input they read."""
    recorded = dig(artifact, "provenance", "inputs")
    for name in inputs:
        path = root / name
        require(
            isinstance(recorded, dict)
            and path.is_file()
            and recorded.get(name) == sha256_file(path),
            f"{rel} was not computed from the committed {name} (its provenance.inputs does "
            "not record that file's SHA-256)",
        )


def check_wilson(label: str, stat: object, successes: int, n: int) -> None:
    """``stat`` reports ``successes / n`` (0 with no trials) and its Wilson 95% interval."""
    require(isinstance(stat, dict), f"{label} missing")
    assert isinstance(stat, dict)
    require(
        close(stat.get("estimate"), successes / n if n else 0.0),
        f"{label} does not recompute from runs.jsonl",
    )
    low, high = wilson(successes, n)
    require(
        close(stat.get("ci_low"), low) and close(stat.get("ci_high"), high),
        f"{label} interval is not the Wilson 95% interval of {successes}/{n}",
    )


def g7(ctx: Context) -> str:
    """Main study: as preregistered, >= 3 configs, >= 2 families, >= 60 runs each, intervals."""
    root = ctx.clone
    results = load_json(root, E1_RESULTS)
    require_provenance(E1_RESULTS, results)
    require(
        results.get("confirmatory") is True and bool(results.get("prereg")),
        "E1 results are not marked confirmatory with a preregistration",
    )
    prereg, text, fz = frozen_prereg(root, results.get("prereg"), results.get("prereg_sha256"))
    committed_after_freeze(root, prereg, fz, E1_DATA, (E1_RESULTS, E1_RUNS))
    planned, arms = e1_plan(root, prereg, text)
    runs = _e1_runs(root)
    check_e1_rows(runs, planned, arms)
    n_banked = check_e1_banked(root, runs, arms, prereg, fz)
    evaluated = evaluated_trees(root)
    check_inputs(root, E1_RESULTS, results, (E1_RUNS, E0_EVAL))
    check_instruments(root, E1_RUNS, runs, evaluated)
    missing = sorted(set(planned) - {str(r["run_id"]) for r in runs})
    accounting = results.get("runs")
    reported = accounting.get("missing_run_ids", []) if isinstance(accounting, dict) else []
    require(
        isinstance(reported, list) and sorted(str(r) for r in reported) == missing,
        f"results.json does not report the {len(missing)} planned run(s) missing from "
        f"{E1_RUNS} (runs.missing_run_ids)",
    )
    require(all(r.get("synthetic") is False for r in runs), "E1 contains synthetic runs")
    banked = Counter(str(r["config_id"]) for r in runs)
    families = {arms[c]["family"] for c in banked}
    require(len(banked) >= G7_MIN_CONFIGS, f"{len(banked)} agent configurations < 3")
    require(len(families) >= G7_MIN_FAMILIES, f"{len(families)} model families < 2")
    short = [f"{c}={n}" for c, n in sorted(banked.items()) if n < G7_MIN_RUNS]
    require(not short, f"configs below {G7_MIN_RUNS} runs: " + ", ".join(short))
    included: dict[str, list[Mapping[str, Any]]] = {}
    for run in runs:
        if run["included"] is True:
            included.setdefault(str(run["config_id"]), []).append(run)
    reported_configs = results.get("configs")
    require(
        isinstance(reported_configs, dict) and set(reported_configs) == set(included),
        "results.json configs differ from runs.jsonl",
    )
    for config, rows in sorted(included.items()):
        entry = reported_configs[config]
        require(isinstance(entry, dict), f"{config}: results missing")
        require(
            is_count(entry.get("n_runs")) and entry.get("n_runs") == len(rows),
            f"{config}: n_runs mismatch",
        )
        claims = [c for r in rows for c in r["claims"]]
        # Y1 (prereg 0001 section 5): the included runs with a hidden-check result.
        judged = [r for r in rows if r.get("ground_truth_success") is not None]
        stats = (
            (
                "false_success_rate",
                sum(1 for r in judged if r.get("false_success") is True),
                len(judged),
            ),
            (
                "contradicted_claim_rate",
                sum(1 for c in claims if c.get("verdict") == "contradicted"),
                len(claims),
            ),
        )
        for metric, successes, n in stats:
            check_wilson(f"{config}.{metric}", entry.get(metric), successes, n)
    check_rederived(ctx, "e1", E1_RUNS)
    sizes = ", ".join(f"{c}={n}" for c, n in sorted(banked.items()))
    return (
        f"{len(banked)} configs, {len(families)} families, runs {sizes}; "
        f"plan and freeze of {prereg} hold; rows from the evaluated instrument at "
        f"{evaluated[0][:12]}, re-derived from the {n_banked} banked runs; rates and "
        "Wilson intervals recompute"
    )


# ---------------------------------------------------------------- G8

E2_HEADING = re.compile(r"\be2\b|\bmechanisms?\b")
E3_HEADING = re.compile(r"\be3\b|\bjudges?\b")
# The numbers registry ``make report`` writes; each entry names its source artifact.
REGISTRY_REL = "artifacts/report/numbers.json"


def registry_sources(root: Path) -> dict[str, str]:
    """Each registry key with the artifact its number is derived from."""
    numbers = load_json(root, REGISTRY_REL).get("numbers")
    require(isinstance(numbers, dict), f"{REGISTRY_REL} has no numbers object")
    assert isinstance(numbers, dict)
    return {
        str(key): str(entry.get("source"))
        for key, entry in numbers.items()
        if isinstance(entry, dict)
    }


def reported_from(
    text: str, title: re.Pattern[str], sources: Mapping[str, str], artifact: str
) -> str:
    """The visible text (:func:`visible_text`) of every section of ``text`` whose heading
    matches ``title`` and that binds a number derived from ``artifact`` (a claimcheck
    marker whose registry entry names it as its source), joined; empty when no section
    does. Design text without results binds no such number, so it is not a report of
    them (review B3), and a marker in a comment or in fenced code binds nothing a
    reader sees."""
    return "\n\n".join(
        body
        for head, body in md_sections(visible_text(text))
        if title.search(head)
        and any(sources.get(key) == artifact for key, _ in MARKER.findall(body))
    )


E3_JUDGES = "artifacts/e3/judges.json"
# The E3 sample takes K // 4 runs from each of the four E1 arms (prereg 0003 section 3).
E3_ARMS = 4
#: The attempts after which an unservable E3 call excludes its run (prereg 0003
#: section 7; ``receipts.evaluation.e3.MAX_ATTEMPTS``).
E3_MAX_ATTEMPTS = 3


def e3_sample(rows: Sequence[Mapping[str, Any]], k: int, seed: int) -> list[str]:
    """The run ids prereg 0003 section 3 samples from the E1 rows, sorted: one
    ``random.Random(seed)``; for each arm in sorted ``config_id`` order, its eligible
    run ids (included, with at least one claim), sorted, are sampled with
    ``rng.sample(ids, K // 4)``, or all taken when the arm has at most K // 4 (then
    nothing is drawn). Arms without eligible runs draw nothing, so listing the E1 arms
    that have no row changes nothing."""
    per_arm = k // E3_ARMS
    eligible: dict[str, list[str]] = {}
    for row in rows:
        ids = eligible.setdefault(str(row.get("config_id")), [])
        claims = row.get("claims")
        if row.get("included") is True and isinstance(claims, list) and claims:
            ids.append(str(row.get("run_id")))
    rng = random.Random(seed)
    sampled: list[str] = []
    for arm in sorted(eligible):
        ids = sorted(eligible[arm])
        sampled += ids if len(ids) <= per_arm else rng.sample(ids, per_arm)
    return sorted(sampled)


def check_e3_exclusions(judges: Mapping[str, Any], excluded: set[str]) -> None:
    """Every excluded E3 run carries the record prereg 0003 section 7 gives it, and no
    other run does: an ``exclusions`` entry with a call of at least
    :data:`E3_MAX_ATTEMPTS` logged attempts, each logged error listed, and an
    ``excluded_unservable`` deviation. So ``runs.excluded`` cannot drop a sampled run
    from the judgment without the failed attempts that justify it."""
    entries = judges.get("exclusions", [])
    require(
        isinstance(entries, list) and all(isinstance(e, dict) for e in entries),
        "E3 exclusions malformed",
    )
    assert isinstance(entries, list)
    shown: set[str] = set()
    for entry in entries:
        rid, calls = str(entry.get("run_id")), entry.get("calls")
        require(rid in excluded, f"E3 records an exclusion of {rid}, which runs.excluded omits")
        require(
            isinstance(calls, list)
            and any(
                isinstance(c, dict)
                and is_count(c.get("attempts"))
                and c["attempts"] >= E3_MAX_ATTEMPTS
                and isinstance(c.get("errors"), list)
                and len(c["errors"]) >= c["attempts"]
                for c in calls
            ),
            f"E3 excludes {rid} without a call that failed {E3_MAX_ATTEMPTS} logged attempts "
            "(prereg 0003 section 7)",
        )
        shown.add(rid)
    unshown = sorted(excluded - shown)
    require(
        not unshown,
        f"E3 excludes {len(unshown)} run(s) with no exclusions record of their failed "
        "attempts: " + ", ".join(unshown[:3]),
    )
    deviations = judges.get("deviations", [])
    noted = {
        str(d.get("run_id"))
        for d in (deviations if isinstance(deviations, list) else [])
        if isinstance(d, dict) and d.get("kind") == "excluded_unservable"
    }
    require(
        noted == excluded,
        "E3 excluded_unservable deviations do not name exactly the excluded runs",
    )


def check_e3_sample(
    root: Path, judges: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], judge_ids: list[str]
) -> tuple[int, int, int]:
    """E3 judged its whole recorded sample (prereg 0003 sections 3, 7, and 8), counted
    again here instead of taken from ``runs.complete`` alone.

    ``runs.complete`` is true; the artifact was computed from the committed E1 rows;
    its recorded sample is the section 3 draw (:func:`e3_sample`) from them with its
    recorded K (a positive multiple of 4) and seed; ``runs.excluded`` names sampled
    runs only, each with the record of section 7 (:func:`check_e3_exclusions`); the
    scored items are every claim of exactly the other
    sampled runs, each scored against the verdict of its row; and every judge has a
    served call for each of those runs. Returns ``(sampled, judged, excluded)``.
    """
    require(
        dig(judges, "runs", "complete") is True,
        "E3 did not judge its whole sample (runs.complete is not true)",
    )
    check_inputs(root, E3_JUDGES, judges, (E1_RUNS,))
    k, seed = dig(judges, "sample", "sample_runs"), dig(judges, "sample", "seed")
    require(
        is_count(k) and k > 0 and k % E3_ARMS == 0 and is_count(seed),
        f"E3 records no sample size K (a positive multiple of {E3_ARMS}) and seed",
    )
    assert isinstance(k, int) and isinstance(seed, int)
    recorded = dig(judges, "sample", "sampled_run_ids")
    require(
        isinstance(recorded, list)
        and bool(recorded)
        and all(is_text(r) for r in recorded)
        and len(set(recorded)) == len(recorded),
        "E3 records no sample of run ids",
    )
    assert isinstance(recorded, list)
    require(
        sorted(recorded) == e3_sample(rows, k, seed),
        f"the E3 sample is not the prereg 0003 section 3 draw of K = {k} with seed {seed} "
        f"from {E1_RUNS}",
    )
    excluded = dig(judges, "runs", "excluded")
    require(
        isinstance(excluded, list)
        and len(set(map(str, excluded))) == len(excluded)
        and set(map(str, excluded)) <= set(recorded),
        "E3 excludes runs that are not in its sample",
    )
    assert isinstance(excluded, list)
    check_e3_exclusions(judges, {str(r) for r in excluded})
    judged = set(recorded) - set(map(str, excluded))
    items, calls = judges.get("items"), judges.get("calls")
    require(
        isinstance(items, list)
        and all(isinstance(i, dict) for i in items)
        and isinstance(calls, list)
        and all(isinstance(c, dict) for c in calls),
        "E3 items or calls malformed",
    )
    assert isinstance(items, list) and isinstance(calls, list)
    require(
        {str(i.get("run_id")) for i in items} == judged,
        "E3 items do not cover exactly the sampled runs that were not excluded",
    )
    truth = {
        (str(row.get("run_id")), str(c.get("claim_id"))): c.get("verdict")
        for row in rows
        if str(row.get("run_id")) in judged and isinstance(row.get("claims"), list)
        for c in row["claims"]
        if isinstance(c, dict)
    }
    scored = [(str(i.get("run_id")), str(i.get("claim_id"))) for i in items]
    require(
        len(set(scored)) == len(scored) and set(scored) == set(truth),
        "E3 items are not every claim of the judged runs, once each",
    )
    wrong = sorted(
        f"{r}/{c}"
        for (r, c), i in zip(scored, items, strict=True)
        if i.get("truth") != truth[(r, c)]
    )
    require(
        not wrong,
        f"E3 ground truth is not the verdict of the row in {E1_RUNS} for " + ", ".join(wrong[:3]),
    )
    for judge_id in judge_ids:
        served = {
            str(c.get("run_id"))
            for c in calls
            if c.get("judge_id") == judge_id and c.get("served") is True
        }
        missing = sorted(judged - served)
        require(
            not missing,
            f"judge {judge_id} did not judge {len(missing)} sampled run(s): "
            + ", ".join(missing[:3]),
        )
    return len(recorded), len(judged), len(excluded)


def g8(ctx: Context) -> str:
    """Mechanisms (E2) and judges (E3) ran and are reported, including null results; E3
    judged its whole recorded sample (:func:`check_e3_sample`)."""
    root = ctx.clone
    contradicted = set()
    e1_rows = _e1_runs(root)
    for run in e1_rows:
        claims = run.get("claims")
        if run.get("included") is True and isinstance(claims, list):
            contradicted |= {
                (str(run.get("run_id")), str(c.get("claim_id")))
                for c in claims
                if isinstance(c, dict) and c.get("verdict") == "contradicted"
            }
    mech_rel = "artifacts/e2/mechanism.json"
    mech = load_json(root, mech_rel)
    require_provenance(mech_rel, mech)
    rows = mech.get("claims")
    require(
        isinstance(rows, list) and all(isinstance(m, dict) for m in rows),
        "E2 mechanism claims malformed",
    )
    assert isinstance(rows, list)
    keys = [(str(m.get("run_id")), str(m.get("claim_id"))) for m in rows]
    repeated = len(keys) - len(set(keys))
    require(not repeated, f"E2 classifies {repeated} claim(s) more than once")
    require(set(keys) == contradicted, "E2 does not classify exactly the E1 contradicted claims")
    require(all(m.get("class") in MECHANISM_CLASSES for m in rows), "E2 has unknown classes")
    judges = load_json(root, E3_JUDGES)
    require_provenance(E3_JUDGES, judges)
    configs = judges.get("judges")
    require(
        isinstance(configs, list) and all(isinstance(j, dict) for j in configs),
        "E3 judges malformed",
    )
    assert isinstance(configs, list)
    ids = [j.get("judge_id") for j in configs]
    require(all(is_text(i) for i in ids), "an E3 judge has no judge_id")
    require(len(set(ids)) == len(ids), "E3 lists a judge configuration more than once")
    require(len(configs) >= 2, f"E3 has {len(configs)} judge configuration(s) < 2")
    for judge in configs:
        name = judge["judge_id"]
        per_type = judge.get("per_type")
        require(
            isinstance(per_type, dict) and bool(per_type), f"judge {name} has no per-type results"
        )
        assert isinstance(per_type, dict)
        total = 0
        for counts in per_type.values():
            require(
                isinstance(counts, dict)
                and all(is_count(counts.get(k)) for k in ("tp", "fp", "fn"))
                and (counts.get("tn") is None or is_count(counts.get("tn"))),
                f"judge {name} lacks tp/fp/fn counts (non-negative integers)",
            )
            total += sum(int(counts[k]) for k in ("tp", "fp", "fn")) + int(counts.get("tn") or 0)
        require(total > 0, f"judge {name} judged no claims (every count is 0)")
    sampled, judged, excluded = check_e3_sample(root, judges, e1_rows, [str(i) for i in ids])
    report = root / "docs" / "REPORT.md"
    require(report.is_file(), "docs/REPORT.md missing")
    text = report.read_text(encoding="utf-8")
    require(has_section(text, E2_HEADING), "REPORT.md has no E2 section")
    require(has_section(text, E3_HEADING), "REPORT.md has no E3 section")
    # Reported means the results are in the report, bound to the artifacts (G10 checks
    # that each bound value is current), and every judge's result is there, a null
    # result included.
    sources = registry_sources(root)
    require(
        bool(reported_from(text, E2_HEADING, sources, mech_rel)),
        f"REPORT.md has no E2 section that binds a number from {mech_rel}: the mechanism "
        "results, null results included, are not reported",
    )
    e3_text = reported_from(text, E3_HEADING, sources, E3_JUDGES)
    require(
        bool(e3_text),
        f"REPORT.md has no E3 section that binds a number from {E3_JUDGES}: the judge "
        "results, null results included, are not reported",
    )
    # Named means in the prose a reader sees: a marker's value, not its key.
    shown = MARKER.sub(r"\2", e3_text)
    unnamed = [str(i) for i in ids if not names_word(shown, str(i))]
    require(
        not unnamed,
        f"REPORT.md's E3 results do not name judge configuration(s) {', '.join(unnamed)}",
    )
    mix = Counter(str(m.get("class")) for m in rows)
    return (
        f"E2 classified {len(rows)} claims {dict(mix)}; E3 {len(configs)} judges, sample of "
        f"{sampled} runs, {judged} judged by every judge, {excluded} excluded; reported"
    )


# ---------------------------------------------------------------- G9

E4_RESULTS = "artifacts/e4/results.json"
E4_RUNS = "artifacts/e4/runs.jsonl"
E4_PLAN = "artifacts/studies/e4/plan.json"
E4_PREREG = "prereg/0002-e4-mitigation.md"
PLANNED_PER_CELL = re.compile(r"planned_runs_per_cell:[ \t]*(\d+)\b")
HOOK_TRANSCRIPT = "artifacts/hook/demo_transcript.txt"
INSTALL_HEADING = re.compile(r"\binstall(?:ation|ing)?\b")
ENTRY_POINT = re.compile(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):([A-Za-z_]\w*)(?:\.[A-Za-z_]\w*)*")


def dig(data: object, *keys: str) -> object:
    """``data[k1][k2]...``, or None when a key is missing or a level is not an object."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def plan_notes(plan: object, key: str) -> list[str] | None:
    """A task list a study plan records in its JSON ``notes``, or None."""
    notes = dig(plan, "notes")
    try:
        data = json.loads(notes) if isinstance(notes, str) else None
    except json.JSONDecodeError:
        return None
    value = dig(data, key)
    return [str(v) for v in value] if isinstance(value, list) else None


def e1_task_ids(root: Path) -> set[str]:
    """Every task E1 used or planned: its rows, its plan's runs, and its plan's E1 split."""
    tasks = {str(r.get("task_id")) for r in _e1_runs(root)}
    path = root / E1_PLAN
    if path.is_file():
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateError(f"{E1_PLAN} is not valid JSON") from exc
        runs = dig(plan, "runs")
        if isinstance(runs, list):
            tasks |= {str(r.get("task_id")) for r in runs if isinstance(r, dict)}
        tasks |= set(plan_notes(plan, "e1_tasks") or [])
    return tasks


def held_out_lists(root: Path) -> tuple[set[str], set[str]]:
    """``(E1 task ids, held-out split)``: every task E1 used or planned
    (:func:`e1_task_ids`) and the ``e4_tasks`` list the E1 plan records in its notes
    (prereg 0002 section 3). Both must be known and non-empty, or the checks that the
    E4 tasks are held out would compare nothing."""
    path = root / E1_PLAN
    require(path.is_file(), f"{E1_PLAN} missing, so the held-out E4 split it records is unknown")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{E1_PLAN} is not valid JSON") from exc
    split = plan_notes(plan, "e4_tasks")
    require(
        bool(split),
        f"{E1_PLAN} records no held-out E4 split (a non-empty e4_tasks list in its notes)",
    )
    e1 = e1_task_ids(root)
    require(
        bool(e1),
        "E1's task ids are unknown or empty (no E1 row, planned E1 run, or e1_tasks list), "
        "so the E4 tasks are not shown to be disjoint from them",
    )
    return e1, set(split or [])


#: The E4 design of prereg 0002 section 3: these two configurations, each with every
#: mitigation (``receipts.study.results_e4.CONFIGURATIONS`` and
#: ``receipts.study.spec.MITIGATIONS``).
E4_CONFIGURATIONS = ("ma-qwen7b", "ma-granite8b")
E4_MITIGATIONS = ("none", "honesty", "evidence", "hook")


def check_e4_cells(
    prereg: str, text: str, planned: Mapping[str, Mapping[str, Any]], arms: Iterable[str]
) -> int:
    """The E4 plan is the design of prereg 0002 section 3: its arms are
    :data:`E4_CONFIGURATIONS`, its (configuration, mitigation) cells are exactly those
    arms times :data:`E4_MITIGATIONS`, and every cell has the ``planned_runs_per_cell``
    runs that the first such line of ``prereg`` states, on the identical list of (task,
    conditions, seed) triples (the conditions differ only in M1). Returns that number."""
    stated = PLANNED_PER_CELL.search(text)
    require(stated is not None, f"{prereg} does not state planned_runs_per_cell as a number")
    assert stated is not None
    want = int(stated.group(1))
    require(
        sorted(arms) == sorted(E4_CONFIGURATIONS),
        f"{E4_PLAN} plans the arms {', '.join(sorted(arms))}, not the configurations of "
        f"{prereg} section 3 ({', '.join(E4_CONFIGURATIONS)})",
    )
    cells: dict[str, list[str]] = {}
    for spec in planned.values():
        cell = f"{spec.get('config_id')}/{spec.get('mitigation', 'none')}"
        work = [spec.get("task_id"), spec.get("conditions"), spec.get("seed")]
        cells.setdefault(cell, []).append(json.dumps(work, sort_keys=True))
    design = {f"{c}/{m}" for c in E4_CONFIGURATIONS for m in E4_MITIGATIONS}
    absent, extra = sorted(design - set(cells)), sorted(set(cells) - design)
    require(
        not absent and not extra,
        f"{E4_PLAN} is not the 2 x 4 design of {prereg} section 3: "
        + "; ".join(
            part
            for part in (
                "no runs in cell(s) " + ", ".join(absent) if absent else "",
                "cell(s) outside it " + ", ".join(extra) if extra else "",
            )
            if part
        ),
    )
    off = [f"{cell}={len(work)}" for cell, work in sorted(cells.items()) if len(work) != want]
    require(
        not off, f"{E4_PLAN} cells differ from planned_runs_per_cell = {want}: " + ", ".join(off)
    )
    lists = {cell: sorted(work) for cell, work in cells.items()}
    first = min(lists)
    differ = sorted(cell for cell, work in lists.items() if work != lists[first])
    require(
        not differ,
        f"{E4_PLAN} cells do not share one identical list of (task, M1, seed) triples: "
        + ", ".join(differ[:3])
        + f" differ from {first}",
    )
    return want


def ran_committed_code(provenance: object) -> bool:
    """The code a run ran is the commit its run.json records (``git_sha``), as
    ``tools/run_study.py`` records the code and ``receipts.study.results_e4`` reads it: a
    code snapshot whose ``snapshot_of`` is that commit, or a working tree whose
    ``uncommitted_at_start`` (``git status`` paths, a rename as ``old -> new``) lists no
    path under ``src/``."""
    if not isinstance(provenance, dict):
        return False
    if provenance.get("code") == "snapshot" and provenance.get("snapshot_of"):
        return bool(provenance.get("snapshot_of") == provenance.get("git_sha"))
    dirty = provenance.get("uncommitted_at_start")
    return (
        provenance.get("code") == "working tree"
        and isinstance(dirty, list)
        and all(isinstance(entry, str) for entry in dirty)
        and not any(
            part.strip().strip('"').startswith("src/")
            for entry in dirty
            for part in entry.split(" -> ")
        )
    )


#: The outcome fields of an E4 results row and the banked-row field each is taken from
#: (``outcome_row`` in ``receipts.study.results_e4``): Z1's analysis set is the runs with
#: a report, and Z1 is a contradicted claim of a valid type, which banking records as
#: ``any_contradicted`` with the same valid-types rule (``receipts.study.rescore``).
E4_OUTCOME_FIELDS = (
    ("has_report", "included"),
    ("z1_false_claim", "any_contradicted"),
    ("ground_truth_success", "ground_truth_success"),
    ("z3_task_success", "ground_truth_success"),
    ("success_reported", "success_reported"),
    ("z2_false_success", "false_success"),
)


def check_e4_rows_file(
    root: Path,
    rows: Sequence[Mapping[str, Any]],
    evaluated: Evaluated,
    runs: Mapping[str, BankedRun],
) -> None:
    """The banked rows (artifacts/e4/runs.jsonl) are the rows of exactly the runs the E4
    results hold and of every banked E4 run (:func:`check_coverage`); each shows the
    ground truth and false success of its banked ledger (:func:`check_ledger_outcomes`;
    ``runs`` holds the banked run of each results row); each results row is the outcome
    row of its banked row (:data:`E4_OUTCOME_FIELDS`); and each banked row comes from the
    evaluated instrument (:func:`check_instruments`)."""
    banked = load_jsonl(root, E4_RUNS)
    require(all(isinstance(r, dict) for r in banked), f"{E4_RUNS} has rows that are not objects")
    ids = [str(r.get("run_id")) for r in banked]
    require(
        len(set(ids)) == len(ids) and sorted(ids) == sorted(str(r.get("run_id")) for r in rows),
        f"the E4 results' rows are not the runs of {E4_RUNS}",
    )
    check_coverage(root, "e4", E4_RUNS, ids)
    by_id = dict(zip(ids, banked, strict=True))
    for row in rows:
        rid = str(row.get("run_id"))
        mine = by_id[rid]
        check_ledger_outcomes(E4_RUNS, mine, runs[rid].events)
        differ = [
            name
            for name, key in E4_OUTCOME_FIELDS
            if name not in row or json.dumps(row[name]) != json.dumps(mine.get(key))
        ]
        require(
            not differ,
            f"{rid} in {E4_RESULTS} is not the outcome row of its banked row in "
            f"{', '.join(differ)} (prereg 0002 section 4: every outcome comes from the row "
            "banking writes)",
        )
    check_instruments(root, E4_RUNS, banked, evaluated)


def check_e4_rate(
    e4: Mapping[str, Any], mitigation: str, rows: Sequence[Mapping[str, Any]]
) -> None:
    """The Z1 rate of one mitigation (runs with a report) recomputes from the rows."""
    subset = [r for r in rows if r.get("mitigation") == mitigation and r["has_report"] is True]
    k, n = sum(1 for r in subset if r["z1_false_claim"] is True), len(subset)
    stat = dig(e4, "outcomes", "Z1", "descriptive", "by_mitigation", mitigation, "wilson")
    require(isinstance(stat, dict), f"E4 results do not report the Z1 rate of {mitigation}")
    assert isinstance(stat, dict)
    counted = stat.get("successes"), stat.get("n")
    ok = all(is_count(v) for v in counted) and counted == (k, n)
    if n:
        low, high = wilson(k, n)
        ok = ok and close(stat.get("estimate"), k / n)
        ok = ok and close(stat.get("ci_low"), low) and close(stat.get("ci_high"), high)
    require(ok, f"E4 Z1 rate of {mitigation} does not recompute from its runs ({k}/{n})")


def check_e4(root: Path, e4: Mapping[str, Any]) -> tuple[int, int]:
    """E4 ran as preregistered on held-out tasks (prereg 0002 sections 3, 4, and 7).

    The results are confirmatory and cite a frozen preregistration (with its locked
    SHA-256) whose first ``plan_sha256:`` line is the SHA-256 of the E4 plan's bytes
    and whose first ``planned_runs_per_cell:`` line gives every (configuration,
    mitigation) cell of the plan that many runs on one identical list of triples
    (:func:`check_e4_cells`), which also requires the plan to be the 2 x 4 design of
    prereg 0002 section 3. The plan compares at least one mitigation with the
    no-mitigation arm (``none``), and every planned mitigation ran. The rows are
    distinct, planned E4 runs, each banked and made by its planned arm's agent, with the
    report it was rescored from. Each run ran the evaluated instrument from the freeze
    on (prereg 0002 section 3, Execution; DECISIONS D47 and D57): the commit its run.json
    records is the freeze commit or a later one (:func:`check_launch`), the code that
    ran is that commit (:func:`ran_committed_code`), and git's trees of the row
    instrument paths at that commit equal the evaluation's recorded trees and git's
    trees at the evaluated commit. The task list is their tasks, each a benchmark task
    that is no pilot; the banked and the planned tasks are outside every task E1 used or
    planned and inside the held-out split the E1 plan records, both lists known and
    non-empty (:func:`held_out_lists`). The Z1 rates recompute. Every row comes from
    the evaluated instrument: the results' rows carry the evaluated git trees and are
    not ``instrument_dirty``, and the banked rows of artifacts/e4/runs.jsonl are the
    same runs, one per banked run, with the outcomes of their banked ledgers and of the
    results' rows, and pass :func:`check_instruments` (:func:`check_e4_rows_file`); the
    results were computed from those rows and the held-out evaluation. Returns
    ``(tasks, runs)``."""
    require(
        e4.get("confirmatory") is True and bool(e4.get("prereg")),
        f"the E4 results are not marked confirmatory with a frozen preregistration ({E4_PREREG})",
    )
    prereg, text, fz = frozen_prereg(root, e4.get("prereg"), e4.get("prereg_sha256"))
    tasks = e4.get("tasks")
    require(
        isinstance(tasks, list) and bool(tasks) and all(isinstance(t, str) for t in tasks),
        "E4 tasks are not a list of task ids",
    )
    assert isinstance(tasks, list)
    rows = e4.get("rows")
    require(
        isinstance(rows, list) and bool(rows) and all(isinstance(r, dict) for r in rows),
        "E4 results carry no per-run rows",
    )
    assert isinstance(rows, list)
    require(all(r.get("synthetic") is False for r in rows), "E4 contains synthetic runs")
    path = root / E4_PLAN
    require(path.is_file(), f"{E4_PLAN} missing")
    raw = path.read_bytes()
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{E4_PLAN} is not valid JSON") from exc
    check_plan_digest(prereg, text, E4_PLAN, raw)
    specs = dig(plan, "runs")
    planned = {
        str(s.get("run_id")): s
        for s in (specs if isinstance(specs, list) else [])
        if isinstance(s, dict)
    }
    require(bool(planned), f"{E4_PLAN} has no runs")
    arms = plan_arms(E4_PLAN, dig(plan, "arms"))
    unarmed = sorted(rid for rid, s in planned.items() if str(s.get("config_id")) not in arms)
    require(not unarmed, f"{E4_PLAN} has runs without a planned arm: " + ", ".join(unarmed[:3]))
    mitigations = sorted({str(s.get("mitigation", "none")) for s in planned.values()})
    require(
        "none" in mitigations and len(mitigations) > 1,
        f"{E4_PLAN} compares no mitigation with the no-mitigation arm (none): it plans "
        + ", ".join(mitigations),
    )
    check_e4_cells(prereg, text, planned, arms)
    evaluated = evaluated_trees(root)
    counts = Counter(str(r.get("run_id")) for r in rows)
    repeated = sorted(rid for rid, n in counts.items() if n > 1)
    require(not repeated, f"{len(repeated)} E4 run id(s) repeat: " + ", ".join(repeated[:3]))
    paths = sorted(evaluated[1])
    want = git_trees(root, evaluated[0], paths)
    launched: dict[str, bool] = {}
    holds: dict[str, bool] = {}
    runs: dict[str, BankedRun] = {}
    for row in rows:
        rid = str(row.get("run_id"))
        spec = planned.get(rid)
        require(spec is not None, f"{rid} is not a planned E4 run")
        assert spec is not None
        diffs = [
            k for k in ("task_id", "config_id", "seed", "conditions") if row.get(k) != spec.get(k)
        ]
        if row.get("mitigation") != spec.get("mitigation", "none"):
            diffs.append("mitigation")
        require(not diffs, f"{rid} differs from its planned run in " + ", ".join(diffs))
        require(
            isinstance(row.get("has_report"), bool) and isinstance(row.get("z1_false_claim"), bool),
            f"{rid} lacks has_report or z1_false_claim",
        )
        require(
            dig(row, "instrument", "trees") == evaluated[1]
            and row.get("instrument_dirty") is False,
            f"{rid} does not come from the evaluated instrument (its instrument.trees differ "
            "from those of the held-out G5 evaluation, or it is instrument_dirty)",
        )
        run = banked_run(root, "e4", row)
        check_planned_agent(run, arms, str(spec.get("config_id")))
        drift = [k for k in ("config_id", "seed", "conditions") if run.record.get(k) != row.get(k)]
        if run.record.get("mitigation", "none") != row.get("mitigation"):
            drift.append("mitigation")
        if bool(run.report.strip()) is not row.get("has_report"):
            drift.append("has_report")
        if row.get("report_sha256") != text_sha256(run.report):
            drift.append("report_sha256")
        require(not drift, f"{rid} differs from its banked run.json in " + ", ".join(drift))
        sha = check_launch(root, run, prereg, fz, launched)
        require(
            ran_committed_code(dig(run.record, "provenance")),
            f"{rid} did not run the code of the commit it records: its run.json shows neither "
            "a code snapshot of that commit nor a working tree without uncommitted changes "
            "under src/ (prereg 0002 section 3, Execution)",
        )
        if sha not in holds:
            found = git_trees(root, sha, paths)
            holds[sha] = found == want and found == evaluated[1]
        require(
            holds[sha],
            f"{rid} ran code whose instrument is not the evaluated one: its commit {sha[:12]} "
            f"holds other git trees of {', '.join(paths)} than the held-out G5 evaluation of "
            f"{evaluated[0][:12]} (prereg 0002 section 3; DECISIONS D47)",
        )
        runs[rid] = run
    ran = {str(r["task_id"]) for r in rows}
    require(set(tasks) == ran, "E4 tasks differ from the tasks of its runs")
    bad = sorted(
        t
        for t in ran
        if not SAFE_ID.fullmatch(t)
        or t.startswith("pilot-")
        or not (root / "bench" / "tasks" / t / "task.toml").is_file()
    )
    require(not bad, "E4 tasks are not held-out benchmark tasks: " + ", ".join(bad[:3]))
    e1_tasks, split = held_out_lists(root)
    used = ran | {str(s.get("task_id")) for s in planned.values()}
    overlap = sorted(used & e1_tasks)
    require(not overlap, "E4 tasks overlap E1 tasks (not held out): " + ", ".join(overlap[:3]))
    listed = plan_notes(plan, "e4_tasks")
    held_out = (
        set(listed) if listed is not None else {str(s.get("task_id")) for s in planned.values()}
    )
    require(ran <= held_out, "E4 ran tasks outside its planned held-out set")
    outside = sorted(used - split)
    require(
        not outside,
        "E4 tasks are not in the held-out split the E1 plan records: " + ", ".join(outside[:3]),
    )
    empty = [m for m in mitigations if not any(r.get("mitigation") == m for r in rows)]
    require(not empty, "E4 has no runs for mitigation(s): " + ", ".join(empty))
    for mitigation in mitigations:
        check_e4_rate(e4, mitigation, rows)
    check_e4_rows_file(root, rows, evaluated, runs)
    check_inputs(root, E4_RESULTS, e4, (E4_RUNS, E0_EVAL))
    return len(ran), len(rows)


def top_level_names(source: str) -> set[str]:
    """The names a module binds at its top level, including in ``if``, ``try``, and
    ``with`` blocks there."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    todo: list[ast.stmt] = list(tree.body)
    while todo:
        node = todo.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.If | ast.With):
            todo.extend(node.body)
            todo.extend(node.orelse if isinstance(node, ast.If) else [])
        elif isinstance(node, ast.Try):
            todo.extend(node.body + node.orelse + node.finalbody)
            for handler in node.handlers:
                todo.extend(handler.body)
    return names


def entry_point_problem(root: Path, target: object) -> str | None:
    """Why a console script's ``module:function`` target does not resolve to a name the
    committed package source defines, or None when it does."""
    match = ENTRY_POINT.fullmatch(target.strip()) if isinstance(target, str) else None
    if match is None:
        return f"is not module:function ({target!r})"
    module, attr = match.group(1), match.group(2)
    stem = module.replace(".", "/")
    candidates = [f"{base}{stem}{end}" for base in ("src/", "") for end in (".py", "/__init__.py")]
    present = set(tracked(root, *candidates))
    found = next((c for c in candidates if c in present), None)
    if found is None:
        return f"names module {module}, which is not in the committed source"
    if attr not in top_level_names((root / found).read_text(encoding="utf-8")):
        return f"names {attr}, which {found} does not define"
    return None


def demo_script(root: Path, header: str) -> str | None:
    """The tracked script under tools/ or src/ that a transcript's first line names."""
    found = re.search(r"generated by (\S+)", header)
    rel = repo_path(found.group(1)) if found else None
    if rel is None or not rel.startswith(("tools/", "src/")) or not rel.endswith(".py"):
        return None
    return rel if rel in tracked(root, rel) and (root / rel).is_file() else None


def check_demo_transcript(ctx: Context) -> tuple[str, float]:
    """The committed demo transcript is what its generating script prints, run offline in
    the clone within 30 seconds; returns the script and its run time."""
    text = committed_text(ctx, HOOK_TRANSCRIPT)
    require(text is not None, f"{HOOK_TRANSCRIPT} missing")
    assert text is not None
    header, _, body = text.partition("\n")
    script = demo_script(ctx.clone, header)
    require(
        script is not None,
        "demo transcript does not name a tracked generating script under tools/ or src/",
    )
    assert script is not None
    ctx.make("setup", 900)
    isolation = ctx.isolation()
    require(
        isolation is not None,
        "cannot isolate the network for the hook demo "
        "(no working unshare -rn, bwrap, sandbox-exec)",
    )
    assert isolation is not None
    method, prefix = isolation
    demo = ctx.run(
        "hook-demo",
        [*prefix, "uv", "run", "--no-sync", "python", script],
        HOOK_DEMO_LIMIT_S + 60,
        OFFLINE_ENV,
    )
    require(demo.ok, f"{script} failed offline (exit {demo.returncode}, {method})")
    require(
        demo.seconds <= HOOK_DEMO_LIMIT_S,
        f"{script} took {demo.seconds:.1f}s > {HOOK_DEMO_LIMIT_S:.0f}s",
    )
    require(
        demo.stdout in (text, body), f"{script} output differs from the committed demo transcript"
    )
    return script, demo.seconds


def g9(ctx: Context) -> str:
    """Mitigation: E4 ran as preregistered on held-out tasks with rows from the evaluated
    instrument (:func:`check_e4`) that banking re-derives from the banked runs
    (:func:`check_rederived`); receipts-hook is packaged with install instructions,
    measured latency, and a scripted 30-second demo transcript."""
    root = ctx.clone
    e4 = load_json(root, E4_RESULTS)
    require_provenance(E4_RESULTS, e4)
    n_tasks, n_runs = check_e4(root, e4)
    check_rederived(ctx, "e4", E4_RUNS)
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject.get("project", {}).get("scripts", {})
    require("receipts-hook" in scripts, "pyproject has no receipts-hook entry point")
    problem = entry_point_problem(root, scripts["receipts-hook"])
    require(problem is None, f"the receipts-hook entry point {problem}")
    hook_doc = root / "docs" / "HOOK.md"
    require(
        hook_doc.is_file()
        and has_section(hook_doc.read_text(encoding="utf-8"), INSTALL_HEADING, code=True),
        "docs/HOOK.md with install instructions missing",
    )
    latency = load_json(root, "artifacts/hook/latency.json")
    require_provenance("artifacts/hook/latency.json", latency)
    samples = [float(s) for s in latency.get("samples_s", [])]
    require(len(samples) >= 20, f"{len(samples)} latency samples < 20")
    median = statistics.median(samples)
    require(median < HOOK_MEDIAN_MAX_S, f"median hook latency {median:.2f}s >= 5s")
    script, seconds = check_demo_transcript(ctx)
    return (
        f"E4 on {n_tasks} held-out tasks ({n_runs} runs) as preregistered, rows from the "
        f"evaluated instrument, re-derived from the {n_runs} banked runs; hook packaged; "
        f"median latency {median:.2f}s; demo transcript reproduces ({script}, "
        f"{seconds:.1f}s offline)"
    )


def g10(ctx: Context) -> str:
    """Claim integrity: make claimcheck and make freshness pass on README.md and REPORT.md."""
    ctx.make("setup", 900)
    claim = ctx.make("claimcheck", 600)
    fresh = ctx.make("freshness", 1200)
    for result, label in ((claim, "claimcheck"), (fresh, "freshness")):
        covered = all(f"{doc}:" in result.stdout for doc in ("README.md", "docs/REPORT.md"))
        require(result.ok, f"make {label} failed: {result.last_line()[:80]}")
        require(covered, f"make {label} did not check both README.md and docs/REPORT.md")
    return "make claimcheck and make freshness pass on README.md and docs/REPORT.md"


def g11(ctx: Context) -> str:
    """Preregistration integrity, refusing a vacuous pass with no confirmatory artifacts."""
    ctx.make("setup", 900)
    verify = ctx.make("prereg-verify", 600)
    require(verify.ok, f"make prereg-verify failed: {verify.last_line()[:80]}")
    detail = ctx.python("prereg-json", ["tools/prereg.py", "verify", "--json"], 600)
    try:
        data = json.loads(detail.stdout)
    except json.JSONDecodeError:
        data = {}
    n = len(data.get("confirmatory_artifacts", []))
    require(data.get("ok") is True and n >= 1, "no confirmatory artifacts cite a preregistration")
    return (
        f"chain intact; {data.get('frozen')} frozen; {n} confirmatory artifact(s) postdate prereg"
    )


def g12(ctx: Context) -> str:
    """Independent review: latest review is SHIP for the current code, zero blocking."""
    ctx.make("setup", 900)
    review = ctx.python("review", ["tools/review.py", "--validate-only"], 600)
    require(
        review.ok and review.last_line() == "REVIEW: SHIP",
        "latest review is not a valid SHIP for HEAD: " + review.last_line()[:60],
    )
    return "artifacts/review/latest.json: REVIEW: SHIP for HEAD, 0 blocking"


def _first_screen(text: str) -> str:
    return "\n".join(text.splitlines()[:60])


# ---------------------------------------------------------------- G13

MANIFEST_REL = "artifacts/report/manifest.json"
MARKER = re.compile(r"<!--n:([A-Za-z0-9_.:-]+)-->(.*?)<!--/n-->", re.S)
# A displayed interval, as the registry formats it ("[0.18, 0.29]") or in prose.
INTERVAL_VALUE = re.compile(
    r"[\[(]\s*[-+]?\d[\d.]*%?\s*[,;]\s*[-+]?\d[\d.]*%?\s*[\])]"
    r"|[-+]?\d[\d.]*%?\s+to\s+[-+]?\d[\d.]*%?"
)
INTERVAL_KEY = re.compile(r"(?i)(?:^|[._-])(?:ci|interval)$")
LOW_KEY = re.compile(r"(?i)(?:^|[._-])(?:ci[._-]?)?(?:low|lo|lower)$")
HIGH_KEY = re.compile(r"(?i)(?:^|[._-])(?:ci[._-]?)?(?:high|hi|upper)$")
IMAGE_MD = re.compile(
    r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
IMAGE_HTML = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*([\"']?)([^\"'\s>]+)\1", re.I)
LINK_MD = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
MERMAID = re.compile(r"(?im)^ {0,3}(?:`{3,}|~{3,})[ \t]*mermaid\b")


def text_blocks(text: str, *, rows: bool) -> list[str]:
    """Paragraphs of the visible Markdown (no code, comments, or headings).

    Tables are not paragraphs; with ``rows`` each table row is a block of its own.
    """
    out: list[str] = []
    current: list[str] = []
    for line, kind in md_lines(text):
        table = line.lstrip().startswith("|")
        if kind != "text" or not line.strip() or table or _heading(line) is not None:
            if current:
                out.append("\n".join(current))
                current = []
            if kind == "text" and table and rows:
                out.append(line)
            continue
        current.append(line)
    if current:
        out.append("\n".join(current))
    return out


def states_interval(block: str) -> bool:
    """True if ``block`` binds an estimate and its interval to the numbers registry.

    The interval is a bound number whose displayed value is an interval, a bound
    number keyed as an interval (``...ci``), or a pair of bounds (``...ci_low`` and
    ``...ci_high``); the estimate is any other bound number.
    """
    estimate = interval = low = high = False
    for key, shown in MARKER.findall(block):
        if INTERVAL_VALUE.search(shown):
            interval = True
            estimate = estimate or re.search(r"\d", INTERVAL_VALUE.sub("", shown)) is not None
        elif INTERVAL_KEY.search(key):
            interval = True
        elif LOW_KEY.search(key):
            low = True
        elif HIGH_KEY.search(key):
            high = True
        else:
            estimate = True
    return estimate and (interval or (low and high))


def resolve_link(target: str, base: str) -> str | None:
    """A link target as a repository path, resolved from directory ``base``; None for
    URLs, anchors, and paths outside the repository."""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith(("//", "#")):
        return None
    target = urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    joined = target.lstrip("/") if target.startswith("/") else posixpath.join(base, target)
    path = posixpath.normpath(joined)
    return None if path == ".." or path.startswith("../") else path


def image_paths(text: str, base: str) -> list[str]:
    """Repository paths of the local images in ``text`` (Markdown images and ``<img>``)."""
    targets = [m.group(1) for m in IMAGE_MD.finditer(text)]
    targets += [m.group(2) for m in IMAGE_HTML.finditer(text)]
    return [path for path in (resolve_link(t, base) for t in targets) if path is not None]


# A top-level list item: a marker at column 0 or 1 (nested items are indented further and
# stay part of their parent item).
TOP_LIST_ITEM = re.compile(r"^ ?(?:[-*+]|\d{1,9}[.)])[ \t]")


def result_items(text: str) -> list[str]:
    """The paragraphs, top-level list items, and tables of the Markdown ``text`` outside
    code, multi-line comments, and headings; each list item, with its continuation lines
    and nested items, and each table is one item. One-line comments and inline code stay
    in their item: G13 passes :func:`visible_text` here and reads links from
    :func:`visible_prose` of each item."""
    out: list[str] = []
    current: list[str] = []
    in_table = False
    for line, kind in md_lines(text):
        if kind != "text" or not line.strip() or _heading(line) is not None:
            if current:
                out.append("\n".join(current))
            current, in_table = [], False
            continue
        table = line.lstrip().startswith("|")
        if current and (table != in_table or (not table and TOP_LIST_ITEM.match(line))):
            out.append("\n".join(current))
            current = []
        in_table = table
        current.append(line)
    if current:
        out.append("\n".join(current))
    return out


# A preregistration: a numbered Markdown file directly under prereg/.
PREREG_FILE = re.compile(r"prereg/[0-9]{4}-[^/]*\.md")


def file_within(root: Path, rel: str, top: str) -> bool:
    """True if ``rel`` is an existing file inside directory ``top`` of ``root``, symlinks
    resolved."""
    path = (root / rel).resolve()
    return path.is_file() and path.is_relative_to((root / top).resolve())


def links_artifact(root: Path, paths: Sequence[str]) -> bool:
    """True if one of the repository ``paths`` is an existing file under artifacts/."""
    return any(p.startswith("artifacts/") and file_within(root, p, "artifacts") for p in paths)


def links_prereg(root: Path, paths: Sequence[str]) -> bool:
    """True if one of the repository ``paths`` is an existing ``prereg/NNNN-*.md`` file."""
    return any(
        PREREG_FILE.fullmatch(p) is not None and file_within(root, p, "prereg") for p in paths
    )


def link_paths(text: str, base: str) -> list[str]:
    """Repository paths of the local links in ``text`` (an image inside a link counts as
    the link's text)."""
    plain = IMAGE_MD.sub("image", text)
    found = (resolve_link(m.group(1), base) for m in LINK_MD.finditer(plain))
    return [path for path in found if path is not None]


def manifest_figures(root: Path) -> set[str]:
    """The figures ``make report`` generated, as listed in its committed manifest."""
    if not (root / MANIFEST_REL).is_file():
        return set()
    data = load_json(root, MANIFEST_REL)
    figures = data.get("figures", []) if isinstance(data, dict) else []
    return {posixpath.normpath(str(f)) for f in figures} if isinstance(figures, list) else set()


def quickstart_code(readme: str, screen: int = 60) -> str | None:
    """The first fenced block under a Quickstart heading on the first screen, or None."""
    lines = md_lines(readme)
    start = None
    for index, (line, kind) in enumerate(lines[:screen]):
        head = _heading(line) if kind == "text" else None
        if head is not None and "quickstart" in head[1]:
            start = index
            break
    if start is None:
        return None
    for index in range(start + 1, min(len(lines), screen)):
        line, kind = lines[index]
        if kind == "text" and _heading(line) is not None:
            return None
        if kind == "code":
            block: list[str] = []
            for code_line, code_kind in lines[index:]:
                if code_kind != "code":
                    break
                block.append(code_line)
            return "\n".join(block)
    return None


def g13(ctx: Context) -> str:
    """Documentation: README follows section 11, REPORT.md complete, citecheck passes."""
    root = ctx.clone
    readme = (root / "README.md").read_text(encoding="utf-8")
    brief = (root / "docs" / "BUILD_BRIEF.md").read_text(encoding="utf-8")
    require(readme != brief, "README.md is still the build brief")
    screen = _first_screen(readme)
    titles = [_heading(line) for line, kind in md_lines(screen) if kind == "text"]
    require(
        any(
            head is not None and head[0] == 1 and re.match(r"receipts\b", head[1])
            for head in titles
        ),
        "no title",
    )
    require(
        any(states_interval(block) for block in text_blocks(screen, rows=False)),
        "first screen lacks a bound finding with its interval",
    )
    figures = manifest_figures(root)
    headline = [
        p for p in image_paths(strip_code(screen), "") if p in figures and (root / p).is_file()
    ]
    require(bool(headline), "headline SVG missing or not generated by make report")
    require(
        re.search(r"^\|.*\|\s*\n\|\s*:?-{3,}", strip_code(screen), re.M) is not None,
        "no headline table",
    )
    quickstart = quickstart_code(readme)
    require(quickstart is not None, "no quickstart on the first screen")
    require(
        re.search(r"\bmake\s+demo\b|\btools/demo\.py\b", quickstart or "") is not None,
        "quickstart does not run make demo (the offline demo)",
    )
    heads = headings(readme)
    missing = [s for s in README_SECTIONS if not any(s in h for h in heads)]
    require(not missing, "README lacks sections: " + ", ".join(missing))
    # A link counts only in visible prose (not in a comment or inline code), and only to
    # an existing artifact file and an existing prereg/NNNN-*.md preregistration.
    results_text = section_text(visible_text(readme), "result")
    results = link_paths(visible_prose(results_text), "")
    require(
        links_artifact(root, results), "README key results link to no artifact under artifacts/"
    )
    require(
        links_prereg(root, results), "README key results link to no preregistration under prereg/"
    )
    # Section 11: key results, each linked to its artifact and preregistration. A key
    # result is an item of the results section that binds a number.
    for item in result_items(results_text):
        if MARKER.search(item) is None:
            continue
        paths = link_paths(visible_prose(item), "")
        start = " ".join(MARKER.sub(r"\2", item).split())[:60]
        require(
            links_artifact(root, paths),
            f"README key result links to no artifact under artifacts/: {start!r}",
        )
        require(
            links_prereg(root, paths),
            f"README key result links to no preregistration under prereg/: {start!r}",
        )
    how = section_text(readme, "how it works")
    require(
        any((root / p).is_file() for p in image_paths(strip_code(how), ""))
        or MERMAID.search(how) is not None,
        "README how it works has no diagram",
    )
    report_path = root / "docs" / "REPORT.md"
    require(report_path.is_file(), "docs/REPORT.md missing")
    report = report_path.read_text(encoding="utf-8")
    missing = [s for s in REPORT_SECTIONS if not any(s in h for h in headings(report))]
    require(not missing, "REPORT.md lacks sections: " + ", ".join(missing))
    words = len(re.findall(r"\b\w+\b", strip_code(report)))
    require(REPORT_WORDS[0] <= words <= REPORT_WORDS[1], f"REPORT.md has {words} words")
    require(
        any(states_interval(b) for b in text_blocks(section_text(report, "result"), rows=True)),
        "REPORT.md results state no interval bound to an artifact",
    )
    shown = [
        p for p in image_paths(strip_code(report), "docs") if p in figures and (root / p).is_file()
    ]
    require(bool(shown), "REPORT.md shows no figure generated by make report")
    for name, text in (("README.md", readme), ("docs/REPORT.md", report)):
        require(
            EM_DASH not in text and EM_DASH_ENTITY.search(text) is None,
            f"{name} contains an em dash",
        )
        require(HYPE.search(text) is None, f"{name} uses a hype word")
    ctx.make("setup", 900)
    rebuilt = ctx.make("reproduce", 600)
    require(
        rebuilt.ok and rebuilt.last_line() == "REPRODUCE: PASS",
        f"make reproduce (figures and numbers rebuilt from artifacts): {rebuilt.last_line()[:60]}",
    )
    cite = ctx.make("citecheck", 600)
    require(cite.ok, f"make citecheck failed: {cite.last_line()[:80]}")
    return (
        f"README follows section 11; REPORT.md {words} words; figures reproduce;"
        " every reference verified"
    )


def g14(ctx: Context) -> str:
    """Hygiene: secrets scan, budget, private/ untracked, required files, clean tree."""
    require(not ctx.pre, "original checkout: " + "; ".join(ctx.pre.values()))
    ctx.make("setup", 900)
    scan = ctx.make("secrets-scan", 600)
    require(scan.ok, f"make secrets-scan: {scan.last_line()[:80]}")
    spend = ctx.make("budget", 600)
    require(
        spend.ok and re.search(r"^cash_usd = 0$", spend.output, re.M) is not None,
        f"make budget: {spend.last_line()[:80]}",
    )
    absent = [f for f in REQUIRED_FILES if not (ctx.clone / f).is_file()]
    require(not absent, "missing " + ", ".join(absent))
    return "secrets clean; cash_usd = 0, caps respected; private/ untracked; files present; clean"


# ---------------------------------------------------------------- driver


def run_gates(ctx: Context) -> list[tuple[int, bool, str]]:
    """Run G1 to G14 in order and return ``(n, ok, evidence)`` for each."""
    simple: dict[int, Callable[[Context], str]] = {
        1: g1,
        2: g2,
        4: g4,
        5: g5,
        6: g6,
        7: g7,
        8: g8,
        9: g9,
        10: g10,
        11: g11,
        12: g12,
        13: g13,
        14: g14,
    }
    outcome: dict[int, tuple[bool, str]] = {}
    for n in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 3):
        try:
            gate_ok = {k: v[0] for k, v in outcome.items()}
            evidence = g3(ctx, gate_ok) if n == 3 else simple[n](ctx)
            outcome[n] = (True, evidence)
        except GateError as exc:
            outcome[n] = (False, str(exc))
        except Exception as exc:  # a crashing check is a FAIL, never a skip
            outcome[n] = (False, f"check error: {type(exc).__name__}: {exc}"[:160])
    return [(n, *outcome[n]) for n in range(1, 15)]


def one_line(text: str) -> str:
    """Collapse evidence to a single line."""
    return " ".join(text.split())


def main(argv: Iterable[str] | None = None) -> int:
    """Run ship-check and print the exact report format."""
    parser = argparse.ArgumentParser(description="Run the 14 ship gates on a fresh clone.")
    parser.add_argument("--fast", action="store_true", help="skip slow steps; does not count")
    parser.add_argument("--keep", action="store_true", help="keep the temporary clone")
    args = parser.parse_args(list(argv) if argv is not None else None)
    orig = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    sha = git(orig, "rev-parse", "HEAD").strip()
    pre = pre_phase(orig)
    tmp = Path(tempfile.mkdtemp(prefix="receipts-ship-check-"))
    logs = tmp / "logs"
    logs.mkdir()
    # Names only, never values: the caller variables no sub-command saw.
    _, dropped = scrub_environment(os.environ)
    (logs / "env-dropped.txt").write_text("".join(f"{n}\n" for n in dropped), encoding="utf-8")
    clone = tmp / "clone"
    subprocess.run(["git", "clone", "--quiet", str(orig), str(clone)], check=True, env=git_env())
    subprocess.run(
        ["git", "-C", str(clone), "checkout", "--quiet", "--detach", sha],
        check=True,
        env=git_env(),
    )
    ctx = Context(orig=orig, clone=clone, logs=logs, fast=args.fast, sha=sha, pre=pre)
    results = run_gates(ctx)
    print(f"HEAD {sha} fresh-clone")
    for n, ok, evidence in results:
        print(f"G{n} {'PASS' if ok else 'FAIL'} {one_line(evidence)}")
    passed = sum(1 for _, ok, _ in results if ok)
    if args.fast:
        print(f"SHIP-CHECK-FAST (does not count): {passed}/14")
    elif passed == 14:
        print("SHIP-CHECK: PASS 14/14")
    else:
        print(f"SHIP-CHECK: FAIL {passed}/14")
    if not args.keep:
        shutil.rmtree(clone, ignore_errors=True)
    print(f"ship-check logs: {logs}", file=sys.stderr)
    return 0 if passed == 14 and not args.fast else 1


if __name__ == "__main__":
    sys.exit(main())
