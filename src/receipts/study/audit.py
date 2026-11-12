"""Path audit of a run's ledger: every agent action that named a path outside its workspace.

Runs made before the study sandbox hid the checkout (review N18, DECISIONS D67) ran with
the host root readable, so the checkout's hidden checks, reference solutions, and other
runs' files were within reach. Before such a run is banked, :func:`audit_ledger` reads
its ``ledger.jsonl`` (read only; a run still in progress may be audited) and reports,
with the event's ``seq``, every agent action that named something outside the run's
workspace (``run_start``'s ``workspace``):

- a file tool call (minimal-agent ``read``, ``write``, ``edit``; Claude Code ``Read``,
  ``Write``, ``Edit``, ``MultiEdit``, ``NotebookRead``, ``NotebookEdit``, ``Glob``,
  ``Grep``, ``LS``) whose path is absolute and outside the workspace, starts with
  ``~``, or has a ``..`` component, even one that stays inside (a symlink can make it
  leave). A call the tool refused is still reported, with the tool's answer;
- a shell command (minimal-agent ``bash``, Claude Code ``Bash``, and every agent
  ``command`` event, ``run_tests`` included, with its ``cwd``) that names an absolute
  path outside the workspace (after ``=``, ``:``, a quote, a redirection, a backslash,
  or a short option such as ``-C/x``), has a ``..`` path component, uses ``~`` or
  ``$HOME``, or changes directory with ``cd`` or ``pushd`` to a directory outside the
  workspace or one the audit cannot resolve (none, ``-``, or one named at run time);
- text the agent wrote into a file (minimal-agent ``write`` content and ``edit``
  replacement, Claude Code ``content``, ``new_string``, and ``new_source``) that names an
  absolute path under a top-level host directory outside the workspace, uses ``~/`` or
  ``$HOME``, or climbs with ``..`` (counted over a line) above the written file's own
  directory;
- a tool the audit does not know, an event it cannot read, a broken hash chain, and a
  ledger without a workspace: each is reported, because the audit cannot vouch for it.

It is conservative: a false alarm is acceptable, a miss is not. A few targets are not
reported because they hold no files: the character devices ``/dev/null``,
``/dev/zero``, ``/dev/random``, ``/dev/urandom``, ``/dev/stdin``, ``/dev/stdout``,
``/dev/stderr``, ``/dev/tty``, ``/dev/fd/<n>``, and network URLs (``https://...``;
``file://`` URLs are paths and are reported). In written text, an interpreter-only
shebang line (``#!/usr/bin/env python3``) and absolute paths that do not start with a
top-level host directory (a URL route such as ``/api/users``, a regular expression) are
not reported either.

What the audit cannot see: paths a program builds at run time (a script, a test the
agent wrote, or a command that computes a path from variables other than ``HOME``, from
``Path(__file__).parents``, or by joining strings), relative paths in written code that
the program resolves against its working directory without climbing above the file's
own directory, symlinks or files created by such code, and anything a command reads that
its text does not name (a tool's own configuration lookup, for example). The audit reads
only what the ledger records; it does not know what the sandbox showed.
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from receipts.ledger.events import Event, verify_chain

#: Shell tools and the input key that holds their command.
SHELL_TOOLS: Mapping[str, str] = {"bash": "cmd", "Bash": "command"}

#: File tools and the input keys that name a path they read or write. ``Grep``'s
#: ``pattern`` is a regular expression, not a path.
FILE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "read": ("path",),
    "write": ("path",),
    "edit": ("path",),
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookRead": ("notebook_path",),
    "NotebookEdit": ("notebook_path",),
    "Glob": ("path", "pattern"),
    "Grep": ("path", "glob"),
    "LS": ("path",),
}

#: For each tool that writes text into a file: the input keys holding that text.
CONTENT_KEYS: Mapping[str, tuple[str, ...]] = {
    "write": ("content",),
    "edit": ("new",),
    "Write": ("content",),
    "Edit": ("new_string",),
    "MultiEdit": ("new_string",),
    "NotebookEdit": ("new_source",),
}

#: Tools that name no path: ``run_tests`` runs the task's own test command (its command
#: event is audited), and ``finish`` ends the run with the report.
NO_PATH_TOOLS: frozenset[str] = frozenset({"run_tests", "finish"})

#: minimal-agent's tools, whose input holds the arguments under ``args``.
MINIMAL_AGENT_TOOLS: frozenset[str] = frozenset({"bash", "read", "write", "edit", *NO_PATH_TOOLS})

#: Character devices that hold no files; naming one is not reported.
DEVICES: frozenset[str] = frozenset(
    {
        "/dev/null",
        "/dev/zero",
        "/dev/random",
        "/dev/urandom",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
    }
)
_FD = re.compile(r"/dev/fd/\d+")

#: Top-level host directories: in written text, an absolute path is reported when it
#: starts with one of these (or with the first directory of the workspace path).
TOP_LEVEL: frozenset[str] = frozenset(
    {
        "Applications",
        "Library",
        "System",
        "Users",
        "Volumes",
        "app",
        "bin",
        "boot",
        "data",
        "dev",
        "etc",
        "home",
        "lib",
        "lib32",
        "lib64",
        "libx32",
        "media",
        "mnt",
        "nix",
        "opt",
        "private",
        "proc",
        "root",
        "run",
        "sbin",
        "snap",
        "srv",
        "sys",
        "tmp",
        "usr",
        "var",
        "workspace",
        "workspaces",
    }
)

# Characters after which a new shell word or a path can start, and that end a path.
_STARTS = r"\s'\"`=:;|&<>(){}\[\],\\!"
_ENDS = r"\s'\"`=:;|&<>(){}\[\],"
_ABSOLUTE = re.compile(rf"(?:^|(?<=[{_STARTS}]))(/[^{_ENDS}]*)")
_OPTION_PATH = re.compile(rf"(?:^|(?<=[\s'\"`]))-[A-Za-z]+(/[^{_ENDS}]*)")
_DOTDOT = re.compile(rf"(?<!\.)\.\.(?=$|/|[{_STARTS}])")
_TILDE = re.compile(rf"(?:^|(?<=[{_STARTS}]))~")
_HOME_VAR = re.compile(r"\$\{?HOME\b\}?")
_CD = re.compile(r"(?:^|(?<=[\s;&|(){}`!]))(cd|pushd)(?=$|[\s;&|)])")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*$")
_SHEBANG = re.compile(r"#!\s*/\S+(?:[ \t]+[^\s/]+)?[ \t]*")
_TOKEN_EDGE = re.compile(rf"[{_ENDS}]")


@dataclass(frozen=True)
class Finding:
    """One agent action that named something outside the workspace (or that the audit
    cannot vouch for).

    Attributes:
        seq: The event's ``seq``; None for a problem of the whole ledger.
        tool: The tool, ``command`` for a command event, or ``-``.
        kind: ``file_path``, ``absolute``, ``dotdot``, ``home``, ``cd``, ``cwd``,
            ``content``, ``unknown_tool``, or ``ledger``.
        detail: What was found (the path, the ``cd`` target, or the problem).
        excerpt: The command, path, or line it was found in, shortened.
    """

    seq: int | None
    tool: str
    kind: str
    detail: str
    excerpt: str = ""


@dataclass(frozen=True)
class RunAudit:
    """The audit of one run's ledger.

    Attributes:
        run_dir: The run's directory (the one holding ``ledger.jsonl``).
        banked: Whether the run has a ``run.json`` (False while it is in progress).
        workspace: ``run_start``'s workspace, or None when the ledger names none.
        tool_calls: ``tool_call`` events read.
        commands: Agent ``command`` events read.
        findings: Everything reported, in ledger order.
    """

    run_dir: Path
    banked: bool
    workspace: str | None
    tool_calls: int
    commands: int
    findings: tuple[Finding, ...]

    @property
    def clean(self) -> bool:
        """True when nothing was reported."""
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        """The audit as plain JSON types (the run directory as a string)."""
        return {
            "run_dir": str(self.run_dir),
            "banked": self.banked,
            "workspace": self.workspace,
            "tool_calls": self.tool_calls,
            "commands": self.commands,
            "clean": self.clean,
            "findings": [asdict(finding) for finding in self.findings],
        }


def _inside(path: str, workspace: str) -> bool:
    top = posixpath.normpath(workspace)
    normalized = posixpath.normpath(path)
    return normalized == top or normalized.startswith(top.rstrip("/") + "/")


def _harmless(path: str) -> bool:
    normalized = posixpath.normpath(path)
    return normalized in DEVICES or bool(_FD.fullmatch(normalized))


def _url(text: str, start: int) -> bool:
    """True when the path at ``start`` is the ``//host/...`` of a network URL."""
    if not (text.startswith("//", start) and start > 0 and text[start - 1] == ":"):
        return False
    scheme = _SCHEME.search(text[: start - 1])
    return scheme is not None and scheme.group(0).lower() != "file"


def _token(text: str, start: int, end: int) -> str:
    """The word around ``text[start:end]``, cut at the characters that end a path."""
    left = start
    while left > 0 and not _TOKEN_EDGE.match(text[left - 1]):
        left -= 1
    right = end
    while right < len(text) and not _TOKEN_EDGE.match(text[right]):
        right += 1
    return text[left:right]


def _excerpt(text: str, start: int = 0, end: int | None = None, width: int = 60) -> str:
    stop = len(text) if end is None else end
    left, right = max(0, start - width), min(len(text), stop + width)
    piece = text[left:right].replace("\n", "\\n")
    return ("..." if left else "") + piece + ("..." if right < len(text) else "")


def _absolute_paths(text: str) -> Iterator[tuple[str, int, int]]:
    """Each absolute path in ``text`` with its span (network URLs skipped)."""
    for pattern in (_ABSOLUTE, _OPTION_PATH):
        for match in pattern.finditer(text):
            if not _url(text, match.start(1)):
                yield match.group(1), match.start(1), match.end(1)


def shell_findings(cmd: str, workspace: str) -> list[tuple[str, str]]:
    """``(kind, detail)`` for each way shell command ``cmd`` leaves ``workspace``.

    Kinds: ``absolute`` (an absolute path outside the workspace, character devices
    excepted), ``dotdot`` (a ``..`` path component, wherever it is), ``home`` (``~`` at
    the start of a word, or ``$HOME``), and ``cd`` (``cd`` or ``pushd`` to a directory
    outside the workspace, judged from the workspace root, or one the audit cannot
    resolve). Duplicates are dropped.
    """
    found: dict[tuple[str, str], None] = {}
    for path, _, _ in _absolute_paths(cmd):
        if not _inside(path, workspace) and not _harmless(path):
            found[("absolute", path)] = None
    for match in _DOTDOT.finditer(cmd):
        found[("dotdot", _token(cmd, match.start(), match.end()))] = None
    for match in _TILDE.finditer(cmd):
        found[("home", _token(cmd, match.start(), match.end()))] = None
    for match in _HOME_VAR.finditer(cmd):
        found[("home", _token(cmd, match.start(), match.end()))] = None
    for match in _CD.finditer(cmd):
        problem = _cd_problem(match.group(1), cmd[match.end() :], workspace)
        if problem is not None:
            found[("cd", problem)] = None
    return list(found)


def _cd_problem(verb: str, rest: str, workspace: str) -> str | None:
    """Why ``verb`` (``cd`` or ``pushd``) followed by ``rest`` may leave the workspace."""
    argument = re.split(r"[;&|)\n]", rest, maxsplit=1)[0]
    try:
        words = shlex.split(argument)
    except ValueError:
        words = argument.split()
    targets = [w for w in words if not (w.startswith("-") and len(w) > 1 and w != "--")]
    targets = [w for w in targets if w != "--"]
    if not targets:
        return f"{verb} with no directory goes to $HOME"
    target = targets[0]
    if target == "-":
        return f"{verb} - returns to $OLDPWD"
    if re.fullmatch(r"[+-]\d+", target):
        return f"{verb} {target} turns to a directory on the stack"
    if any(ch in target for ch in "$`*?[") or target.startswith("~"):
        return f"{verb} {target}: a directory named at run time or at home"
    joined = target if target.startswith("/") else posixpath.join(workspace, target)
    if not _inside(joined, workspace):
        return f"{verb} {target} leaves the workspace"
    return None


def path_findings(path: str, workspace: str) -> list[tuple[str, str]]:
    """``(kind, detail)`` when a file tool's ``path`` may lie outside ``workspace``.

    A relative path is taken from the workspace root. Reported: an absolute path
    outside the workspace, a path that starts with ``~``, one with a ``..`` component
    (even if it stays inside), and one with a NUL byte.
    """
    if "\0" in path:
        return [("file_path", f"{path!r} holds a NUL byte")]
    if path.startswith("~"):
        return [("file_path", f"{path} is under a home directory")]
    if ".." in Path(path).parts:
        joined = path if path.startswith("/") else posixpath.join(workspace, path)
        where = "leaves" if not _inside(joined, workspace) else "climbs with .. inside"
        return [("file_path", f"{path} {where} the workspace")]
    if path.startswith("/") and not _inside(path, workspace):
        return [("file_path", f"{path} is outside the workspace")]
    return []


def content_findings(text: str, workspace: str, written: str) -> list[tuple[str, str]]:
    """``(kind, detail)`` for paths outside ``workspace`` named in ``text``, which the
    agent wrote into the file ``written`` (relative to the workspace root).

    Reported (kind ``content``): an absolute path under a top-level host directory
    (:data:`TOP_LEVEL` or the workspace's own first directory) that is not inside the
    workspace or a character device; ``~/`` or ``$HOME``; and a line whose ``..``
    components climb above the written file's own directory. An interpreter-only
    shebang on the first line is skipped.
    """
    tops = TOP_LEVEL | {part for part in workspace.split("/")[1:2] if part}
    skip = 0
    shebang = _SHEBANG.match(text)
    if shebang is not None and text[shebang.end() : shebang.end() + 1] in ("", "\n"):
        skip = shebang.end()
    found: dict[tuple[str, str], None] = {}
    for path, start, _ in _absolute_paths(text):
        if start < skip:
            continue
        normalized = posixpath.normpath(path)
        parts = [part for part in normalized.split("/") if part]
        if not parts or normalized.startswith("//") or parts[0] not in tops:
            continue
        if not _inside(normalized, workspace) and not _harmless(normalized):
            found[("content", f"{path} named in {written}")] = None
    for match in re.finditer(r"(?:^|(?<=[\s'\"`(=:]))~/", text):
        found[("content", f"{_token(text, match.start(), match.end())} named in {written}")] = None
    for match in _HOME_VAR.finditer(text):
        found[("content", f"{match.group(0)} named in {written}")] = None
    depth = len([part for part in posixpath.dirname(written).split("/") if part])
    for number, line in enumerate(text.splitlines(), start=1):
        climbs = len(_DOTDOT.findall(line))
        if climbs > depth:
            detail = f"line {number} of {written} climbs {climbs} levels with .. from depth {depth}"
            found[("content", detail)] = None
    return list(found)


def _relative(path: str, workspace: str) -> str:
    if path.startswith("/") and _inside(path, workspace):
        return posixpath.relpath(posixpath.normpath(path), posixpath.normpath(workspace))
    return path if not path.startswith("/") else ""


def _strings_under(value: Any, key: str) -> Iterator[str]:
    """Every string stored under ``key`` in ``value``, at any depth (MultiEdit's edits)."""
    if isinstance(value, Mapping):
        for name, item in value.items():
            if name == key and isinstance(item, str):
                yield item
            else:
                yield from _strings_under(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _strings_under(item, key)


def _arguments(tool: str, tool_input: Mapping[str, Any]) -> Mapping[str, Any]:
    args = tool_input.get("args")
    if tool in MINIMAL_AGENT_TOOLS and isinstance(args, Mapping):
        return args
    return tool_input


def _refusal(results: Mapping[int, Event], seq: int) -> str:
    result = results.get(seq)
    if result is None or not result.data.get("is_error"):
        return ""
    shown = str(result.data.get("shown", "")).strip().splitlines()
    return f" (the tool answered with an error: {shown[0][:80] if shown else ''})"


def _tool_call_findings(
    event: Event, workspace: str, results: Mapping[int, Event]
) -> list[Finding]:
    tool = str(event.data.get("tool", ""))
    tool_input = event.data.get("input")
    if not isinstance(tool_input, Mapping):
        return [Finding(event.seq, tool, "unknown_tool", "the tool input is not an object")]
    args = _arguments(tool, tool_input)
    if tool in SHELL_TOOLS:
        cmd = str(args.get(SHELL_TOOLS[tool], ""))
        return [
            Finding(event.seq, tool, kind, detail, _excerpt(cmd))
            for kind, detail in shell_findings(cmd, workspace)
        ]
    if tool in NO_PATH_TOOLS:
        return []
    if tool not in FILE_TOOLS:
        detail = "the audit does not know which of its inputs are paths"
        return [Finding(event.seq, tool, "unknown_tool", detail, _excerpt(json.dumps(args)))]
    out: list[Finding] = []
    written = ""
    for key in FILE_TOOLS[tool]:
        value = args.get(key)
        if not isinstance(value, str) or not value:
            continue
        written = written or _relative(value, workspace)
        for kind, detail in path_findings(value, workspace):
            out.append(Finding(event.seq, tool, kind, detail + _refusal(results, event.seq), value))
    for key in CONTENT_KEYS.get(tool, ()):
        for text in _strings_under(args, key):
            for kind, detail in content_findings(text, workspace, written or "the file"):
                out.append(Finding(event.seq, tool, kind, detail, _excerpt(text, 0, 0)))
    return out


def _command_findings(event: Event, workspace: str, scanned: Mapping[int, str]) -> list[Finding]:
    cmd = str(event.data.get("cmd", ""))
    call_seq = event.data.get("call_seq")
    out: list[Finding] = []
    if not (isinstance(call_seq, int) and scanned.get(call_seq) == cmd):
        out += [
            Finding(event.seq, "command", kind, detail, _excerpt(cmd))
            for kind, detail in shell_findings(cmd, workspace)
        ]
    cwd = str(event.data.get("cwd", "."))
    if cwd not in ("", "."):
        out += [
            Finding(event.seq, "command", "cwd", f"cwd {detail}", cwd)
            for _, detail in path_findings(cwd, workspace)
        ]
    return out


def _read_events(ledger: Path) -> tuple[list[Event], list[Finding]]:
    text = ledger.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    events: list[Event] = []
    problems: list[Finding] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            events.append(Event.from_json(line))
        except ValueError:  # json.JSONDecodeError is a ValueError
            last = number == len(lines) and not text.endswith("\n")
            note = " (the last line, perhaps still being written)" if last else ""
            detail = f"line {number} is not a whole event{note}: the audit cannot see it"
            problems.append(Finding(None, "-", "ledger", detail, _excerpt(line, 0, 0)))
    chain = verify_chain(events)
    if chain:
        problems.append(Finding(None, "-", "ledger", f"hash chain: {chain[0]}"))
    return events, problems


def audit_events(events: Sequence[Event], workspace: str) -> list[Finding]:
    """Every finding in ``events`` for a run whose workspace is ``workspace`` (absolute).

    Audited: every ``tool_call`` event, and every ``command`` and ``file_write`` event
    whose source is ``agent``. A command that repeats the text of the shell tool call
    it answers is reported once, at the call.
    """
    results = {
        int(e.data["call_seq"]): e
        for e in events
        if e.kind == "tool_result" and isinstance(e.data.get("call_seq"), int)
    }
    scanned: dict[int, str] = {}
    out: list[Finding] = []
    for event in events:
        if event.kind == "tool_call":
            tool = str(event.data.get("tool", ""))
            tool_input = event.data.get("input")
            if tool in SHELL_TOOLS and isinstance(tool_input, Mapping):
                args = _arguments(tool, tool_input)
                scanned[event.seq] = str(args.get(SHELL_TOOLS[tool], ""))
            out += _tool_call_findings(event, workspace, results)
        elif event.kind == "command" and event.source == "agent":
            out += _command_findings(event, workspace, scanned)
        elif event.kind == "file_write" and event.source == "agent":
            path = str(event.data.get("path", ""))
            out += [
                Finding(event.seq, "file_write", kind, detail, path)
                for kind, detail in path_findings(path, workspace)
            ]
    return out


def audit_ledger(path: Path) -> RunAudit:
    """Audit one run: ``path`` is the run's directory or its ``ledger.jsonl``.

    Nothing is written. A missing or unreadable ledger, or one whose ``run_start``
    names no absolute workspace, is reported as a ``ledger`` finding, never as clean.
    """
    ledger = path if path.name == "ledger.jsonl" else path / "ledger.jsonl"
    run_dir = ledger.parent
    banked = (run_dir / "run.json").is_file()
    if not ledger.is_file():
        missing = Finding(None, "-", "ledger", f"no ledger at {ledger}: the run cannot be audited")
        return RunAudit(run_dir, banked, None, 0, 0, (missing,))
    events, problems = _read_events(ledger)
    start = next((e for e in events if e.kind == "run_start"), None)
    workspace = None if start is None else start.data.get("workspace")
    tool_calls = sum(1 for e in events if e.kind == "tool_call")
    commands = sum(1 for e in events if e.kind == "command" and e.source == "agent")
    if not isinstance(workspace, str) or not workspace.startswith("/"):
        detail = "run_start names no absolute workspace, so the audit cannot tell what is outside"
        problems.append(Finding(None, "-", "ledger", detail))
        return RunAudit(run_dir, banked, None, tool_calls, commands, tuple(problems))
    findings = [*problems, *audit_events(events, workspace)]
    return RunAudit(run_dir, banked, workspace, tool_calls, commands, tuple(findings))


def format_audit(audit: RunAudit) -> list[str]:
    """The audit as text: a header line, then one indented line per finding."""
    state = "banked" if audit.banked else "in progress, no run.json"
    count = len(audit.findings)
    status = "CLEAN" if audit.clean else f"{count} finding{'s' if count != 1 else ''}"
    header = (
        f"{audit.run_dir} ({state}; {audit.tool_calls} tool calls, {audit.commands} agent "
        f"commands; workspace {audit.workspace}): {status}"
    )
    lines = [header]
    for finding in audit.findings:
        seq = "-" if finding.seq is None else str(finding.seq)
        tail = f" :: {finding.excerpt}" if finding.excerpt else ""
        lines.append(f"  seq {seq} {finding.tool} {finding.kind}: {finding.detail}{tail}")
    return lines
