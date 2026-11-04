"""The M4 prior-work transcript: realistic earlier work placed before the request.

At the long level of M4 (context load) the driver puts a prior session before the
task request. The session is stored per task as ``prior_work.json`` (or shared as
``bench/prompts/<name>.json``) in a driver-neutral form::

    {
      "synthetic": true,
      "description": "what this earlier session is, and that it was hand-written",
      "episodes": [
        {
          "request": "an earlier user request about this repository",
          "steps": [
            {"thought": "...", "tool": "read", "args": {"path": "src/x.py"}, "output": "..."},
            {"thought": "...", "tool": "bash", "args": {"cmd": "grep -n y src/x.py"},
             "output": "...\\n[exit code 0]"}
          ],
          "finish": {"thought": "...", "report": "the answer the agent gave"}
        }
      ]
    }

Requests, thoughts, and answers are hand-written (hence ``synthetic: true``); every
tool ``output`` is the true output of that step on the task's starting repository,
in the exact form minimal-agent shows it (file text for ``read``; stdout, stderr,
and ``[exit code N]`` for ``bash``). :func:`capture_outputs` fills them in by
running the steps in a sandbox, and :func:`compare_outputs` checks them again
(receipts.bench.validate does this on the plain starting repository and on the
one with both overlays applied, so the transcript stays true in every condition).

Prior work only reads: tools are ``read`` and ``bash`` with read-only viewer
programs (:data:`PRIOR_WORK_PROGRAMS`), never ``git``, writes, or the test suite
(whose output M2 changes).
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from receipts.drivers.minimal_agent.loop import observation
from receipts.drivers.minimal_agent.protocol import Action
from receipts.drivers.minimal_agent.runtime import (
    MAX_READ_CHARS,
    PathError,
    format_outcome,
    resolve_inside,
)
from receipts.sandbox.api import Sandbox

PRIOR_WORK_TOOLS: Mapping[str, str] = {"read": "path", "bash": "cmd"}
PRIOR_WORK_PROGRAMS = frozenset(
    {"ls", "cat", "head", "tail", "wc", "grep", "find", "sort", "uniq", "cut", "nl", "tr"}
)
PRIOR_WORK_CHARS: tuple[int, int] = (8_000, 24_000)
FORBIDDEN_FIND_OPTIONS = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
)
STEP_TIMEOUT_S = 60.0
__all__ = [
    "MAX_READ_CHARS",
    "PRIOR_WORK_CHARS",
    "PRIOR_WORK_PROGRAMS",
    "PRIOR_WORK_TOOLS",
    "PriorEpisode",
    "PriorStep",
    "PriorWork",
    "PriorWorkError",
    "capture_outputs",
    "compare_outputs",
    "dump_prior_work",
    "load_prior_work",
    "parse_prior_work",
    "prior_work_problems",
    "prior_work_to_dict",
    "read_output",
    "render_messages",
    "rendered_chars",
    "step_problems",
]

_TOP_KEYS = frozenset({"synthetic", "description", "episodes"})
_EPISODE_KEYS = frozenset({"request", "steps", "finish"})
_STEP_KEYS = frozenset({"thought", "tool", "args", "output"})
_FINISH_KEYS = frozenset({"thought", "report"})
_SEPARATORS = frozenset({";", "&&", "||", "|"})
_LOCALE_PREFIX = re.compile(r"^(?:LC_ALL|LC_COLLATE|LANG)=C(?:\.UTF-8)?$")


class PriorWorkError(ValueError):
    """A prior-work file that breaks the format; ``problems`` lists every issue."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class PriorStep:
    """One tool step of an earlier request: the action and its true output."""

    thought: str
    tool: str
    args: Mapping[str, str]
    output: str


@dataclass(frozen=True)
class PriorEpisode:
    """One earlier request, the steps taken for it, and the final answer."""

    request: str
    steps: tuple[PriorStep, ...]
    finish_thought: str
    report: str


@dataclass(frozen=True)
class PriorWork:
    """A whole prior-work transcript (see the module docstring)."""

    description: str
    episodes: tuple[PriorEpisode, ...]
    synthetic: bool = True


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown(table: Mapping[str, Any], allowed: frozenset[str], where: str, out: list[str]) -> None:
    for key in sorted(set(table) - allowed):
        out.append(f"{where}unknown key {key!r}")


def _step(item: Any, where: str, out: list[str]) -> PriorStep | None:
    if not isinstance(item, dict):
        out.append(f"{where}: must be an object")
        return None
    _unknown(item, _STEP_KEYS, f"{where}: ", out)
    before = len(out)
    if not _text(item.get("thought")):
        out.append(f"{where}.thought must be a non-empty string")
    tool = item.get("tool")
    if tool not in PRIOR_WORK_TOOLS:
        out.append(f"{where}.tool must be one of {', '.join(PRIOR_WORK_TOOLS)} (got {tool!r})")
    else:
        arg = PRIOR_WORK_TOOLS[str(tool)]
        args = item.get("args")
        if not (isinstance(args, dict) and set(args) == {arg} and isinstance(args[arg], str)):
            out.append(f'{where}.args must be {{"{arg}": <string>}} for {tool}')
    if not isinstance(item.get("output"), str):
        out.append(f"{where}.output must be a string")
    if len(out) > before:
        return None
    return PriorStep(
        thought=str(item["thought"]),
        tool=str(item["tool"]),
        args={str(k): str(v) for k, v in item["args"].items()},
        output=str(item["output"]),
    )


def _episode(item: Any, where: str, out: list[str]) -> PriorEpisode | None:
    if not isinstance(item, dict):
        out.append(f"{where}: must be an object")
        return None
    _unknown(item, _EPISODE_KEYS, f"{where}: ", out)
    before = len(out)
    if not _text(item.get("request")):
        out.append(f"{where}.request must be a non-empty string")
    raw_steps = item.get("steps")
    steps: list[PriorStep] = []
    if not isinstance(raw_steps, list):
        out.append(f"{where}.steps must be a list (it may be empty)")
    else:
        for index, raw in enumerate(raw_steps):
            step = _step(raw, f"{where}.steps[{index}]", out)
            if step is not None:
                steps.append(step)
    finish = item.get("finish")
    if not isinstance(finish, dict):
        out.append(f"{where}.finish: missing (an object with thought and report)")
    else:
        _unknown(finish, _FINISH_KEYS, f"{where}.finish: ", out)
        for key in ("thought", "report"):
            if not _text(finish.get(key)):
                out.append(f"{where}.finish.{key} must be a non-empty string")
    if len(out) > before:
        return None
    assert isinstance(finish, dict)
    return PriorEpisode(
        request=str(item["request"]),
        steps=tuple(steps),
        finish_thought=str(finish["thought"]),
        report=str(finish["report"]),
    )


def parse_prior_work(data: Any) -> PriorWork:
    """Check the structure of a parsed prior-work file and build a :class:`PriorWork`.

    Raises:
        PriorWorkError: listing every structural problem.
    """
    if not isinstance(data, dict):
        raise PriorWorkError(["prior work must be a JSON object"])
    out: list[str] = []
    _unknown(data, _TOP_KEYS, "", out)
    if data.get("synthetic") is not True:
        out.append(
            "synthetic must be true (committed prior work is hand-written; real transcripts "
            "never enter the repository)"
        )
    if not _text(data.get("description")):
        out.append("description must be a non-empty string")
    raw = data.get("episodes")
    episodes: list[PriorEpisode] = []
    if not isinstance(raw, list) or not raw:
        out.append("episodes must be a non-empty list")
    else:
        for index, item in enumerate(raw):
            episode = _episode(item, f"episodes[{index}]", out)
            if episode is not None:
                episodes.append(episode)
    if out:
        raise PriorWorkError(out)
    return PriorWork(description=str(data["description"]), episodes=tuple(episodes))


def load_prior_work(path: Path) -> PriorWork:
    """Read and parse a prior-work file (raises :class:`PriorWorkError`)."""
    if not path.is_file():
        raise PriorWorkError([f"{path.name}: missing"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PriorWorkError([f"{path.name}: not valid JSON ({exc})"]) from exc
    return parse_prior_work(data)


def prior_work_to_dict(work: PriorWork) -> dict[str, Any]:
    """The JSON form of ``work`` (the inverse of :func:`parse_prior_work`)."""
    return {
        "synthetic": work.synthetic,
        "description": work.description,
        "episodes": [
            {
                "request": episode.request,
                "steps": [
                    {
                        "thought": step.thought,
                        "tool": step.tool,
                        "args": dict(step.args),
                        "output": step.output,
                    }
                    for step in episode.steps
                ],
                "finish": {"thought": episode.finish_thought, "report": episode.report},
            }
            for episode in work.episodes
        ],
    }


def dump_prior_work(work: PriorWork, path: Path) -> None:
    """Write ``work`` as indented JSON with a trailing newline."""
    text = json.dumps(prior_work_to_dict(work), indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _action_text(action: Action) -> str:
    payload = {"thought": action.thought, "tool": action.tool, "args": dict(action.args)}
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def render_messages(work: PriorWork) -> list[dict[str, str]]:
    """Render ``work`` as minimal-agent conversation messages.

    Each episode becomes the user request, then for every step an assistant
    message holding the JSON action and a user message holding the observation
    (exactly as minimal-agent formats them), then the assistant's ``finish``
    action. The result starts with a user message and ends with an assistant
    message, so the task request can follow it directly.
    """
    messages: list[dict[str, str]] = []
    for episode in work.episodes:
        messages.append({"role": "user", "content": episode.request})
        for step in episode.steps:
            action = Action(step.tool, dict(step.args), step.thought)
            messages.append({"role": "assistant", "content": _action_text(action)})
            messages.append({"role": "user", "content": observation(action, step.output)})
        finish = Action("finish", {"report": episode.report}, episode.finish_thought)
        messages.append({"role": "assistant", "content": _action_text(finish)})
    return messages


def rendered_chars(work: PriorWork) -> int:
    """Total characters of the rendered messages (the M4 context load)."""
    return sum(len(message["content"]) for message in render_messages(work))


def _command_problems(cmd: str) -> list[str]:
    if "\n" in cmd.strip():
        return ["must be one line"]
    if "$(" in cmd or "`" in cmd:
        return ["command substitution is not allowed"]
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return ["cannot be parsed as a shell command"]
    problems: list[str] = []
    expecting = True
    for token in tokens:
        if token in _SEPARATORS:
            expecting = True
            continue
        if set(token) <= set("();<>|&") and (">" in token or "&" in token):
            problems.append(f"redirection or background operator {token!r} is not allowed")
            continue
        if token in FORBIDDEN_FIND_OPTIONS or token.startswith("--output") or token == "-o":
            problems.append(f"option {token!r} is not allowed (it writes or runs commands)")
        if expecting and _LOCALE_PREFIX.match(token):
            continue
        if expecting:
            expecting = False
            if token not in PRIOR_WORK_PROGRAMS:
                allowed = ", ".join(sorted(PRIOR_WORK_PROGRAMS))
                problems.append(f"program {token!r} is not allowed in prior work ({allowed})")
    return problems


def _path_ok(path: str) -> bool:
    if not path or path.startswith(("/", "~")):
        return False
    parts = PurePosixPath(path).parts
    return ".." not in parts and parts[0] not in (".git", ".receipts_hidden")


def prior_work_problems(work: PriorWork) -> list[str]:
    """Content rules that need no sandbox: length, read paths, and read-only commands."""
    out: list[str] = []
    low, high = PRIOR_WORK_CHARS
    chars = rendered_chars(work)
    if not low <= chars <= high:
        out.append(f"rendered prior work has {chars} characters; M4 needs {low} to {high}")
    out.extend(step_problems(work))
    return out


def step_problems(work: PriorWork) -> list[str]:
    """The rules a step must meet before it may run: relative read paths, read-only commands."""
    out: list[str] = []
    for e_index, episode in enumerate(work.episodes):
        for s_index, step in enumerate(episode.steps):
            where = f"episodes[{e_index}].steps[{s_index}]"
            if step.tool == "read" and not _path_ok(step.args["path"]):
                out.append(
                    f"{where}.args.path {step.args['path']!r} must be a relative path inside "
                    "the repository"
                )
            elif step.tool == "bash":
                out.extend(
                    f"{where} ({step.args['cmd']!r}): {p}"
                    for p in _command_problems(step.args["cmd"])
                )
    return out


def read_output(workspace: Path, rel: str) -> str:
    """What minimal-agent's ``read`` tool returns for ``rel`` in ``workspace``."""
    try:
        path = resolve_inside(workspace, rel)
    except PathError as exc:
        return f"error: {exc}"
    if not path.is_file():
        return f"error: no such file: {rel}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n[file cut at {MAX_READ_CHARS} characters]"
    return text


def _step_output(step: PriorStep, sandbox: Sandbox, timeout_s: float) -> str:
    if step.tool == "read":
        return read_output(sandbox.workspace, step.args["path"])
    return format_outcome(sandbox.run(step.args["cmd"], timeout_s=timeout_s))


def capture_outputs(
    work: PriorWork, sandbox: Sandbox, timeout_s: float = STEP_TIMEOUT_S
) -> PriorWork:
    """Return ``work`` with every step's output replaced by a fresh run in ``sandbox``.

    The sandbox's workspace must hold the task's starting repository.
    """
    episodes = tuple(
        replace(
            episode,
            steps=tuple(
                replace(step, output=_step_output(step, sandbox, timeout_s))
                for step in episode.steps
            ),
        )
        for episode in work.episodes
    )
    return replace(work, episodes=episodes)


def compare_outputs(
    work: PriorWork, sandbox: Sandbox, timeout_s: float = STEP_TIMEOUT_S
) -> list[str]:
    """Run every step again in ``sandbox`` and list the steps whose recorded output differs."""
    problems: list[str] = []
    for e_index, episode in enumerate(work.episodes):
        for s_index, step in enumerate(episode.steps):
            actual = _step_output(step, sandbox, timeout_s)
            if actual == step.output:
                continue
            where = f"episodes[{e_index}].steps[{s_index}]"
            if step.tool == "read":
                problems.append(
                    f"{where} (read {step.args['path']}): recorded output differs from the file "
                    "in the starting repository"
                )
            else:
                problems.append(
                    f"{where} (bash {step.args['cmd']!r}): recorded output differs from a fresh run"
                )
    return problems
