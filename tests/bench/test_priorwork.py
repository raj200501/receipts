"""Tests for receipts.bench.priorwork: the M4 prior-work transcript format.

The transcripts and repositories here are synthetic test data (tests/bench/factory.py).
"""

from __future__ import annotations

import copy
import itertools
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from receipts.bench import priorwork
from receipts.bench.priorwork import PriorWorkError
from receipts.drivers.minimal_agent.protocol import parse_action

from .factory import GREET, build_task, prior_work
from .fakes import SubprocessSandbox


def _parse(data: Any) -> priorwork.PriorWork:
    return priorwork.parse_prior_work(data)


def _errors(data: Any) -> str:
    with pytest.raises(PriorWorkError) as info:
        _parse(data)
    return "\n".join(info.value.problems)


def test_parse_and_round_trip() -> None:
    data = prior_work()
    parsed = _parse(data)
    assert parsed.synthetic
    assert len(parsed.episodes) == 1
    episode = parsed.episodes[0]
    assert episode.steps[0].tool == "read"
    assert episode.steps[0].args == {"path": "src/toy/greet.py"}
    assert priorwork.prior_work_to_dict(parsed) == data


def test_load_and_dump(tmp_path: Path) -> None:
    path = tmp_path / "pw.json"
    priorwork.dump_prior_work(_parse(prior_work()), path)
    assert priorwork.load_prior_work(path) == _parse(prior_work())
    assert path.read_text(encoding="utf-8").endswith("\n")
    path.write_text("{", encoding="utf-8")
    with pytest.raises(PriorWorkError, match="not valid JSON"):
        priorwork.load_prior_work(path)
    with pytest.raises(PriorWorkError, match="missing"):
        priorwork.load_prior_work(tmp_path / "absent.json")


def _mutated(path: str, value: Any) -> dict[str, Any]:
    data = copy.deepcopy(prior_work())
    target: Any = data
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[int(key)] if isinstance(target, list) else target[key]
    last = keys[-1]
    if value is KeyError:
        del target[last]
    elif isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value
    return data


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        ("synthetic", False, "synthetic must be true"),
        ("description", "", "description"),
        ("episodes", [], "episodes"),
        ("extra", 1, "unknown key 'extra'"),
        ("episodes.0.request", "", "episodes[0].request"),
        ("episodes.0.finish", KeyError, "episodes[0].finish"),
        ("episodes.0.finish.report", "", "episodes[0].finish.report"),
        ("episodes.0.steps", "nope", "episodes[0].steps"),
        ("episodes.0.steps.0.tool", "write", "episodes[0].steps[0].tool"),
        ("episodes.0.steps.0.args", {"cmd": "ls"}, "episodes[0].steps[0].args"),
        ("episodes.0.steps.0.output", 3, "episodes[0].steps[0].output"),
        ("episodes.0.steps.0.thought", "", "episodes[0].steps[0].thought"),
        ("episodes.0.steps.0.extra", 1, "unknown key 'extra'"),
    ],
)
def test_structure_errors(path: str, value: Any, expected: str) -> None:
    assert expected in _errors(_mutated(path, value))


def test_non_object_is_rejected() -> None:
    assert "must be a JSON object" in _errors([])
    data = prior_work()
    data["episodes"] = [3]
    assert "episodes[0]: must be an object" in _errors(data)
    data = prior_work()
    data["episodes"][0]["steps"] = [3]
    assert "episodes[0].steps[0]: must be an object" in _errors(data)


def test_render_messages_follow_minimal_agent_format() -> None:
    parsed = _parse(prior_work())
    messages = priorwork.render_messages(parsed)
    roles = [m["role"] for m in messages]
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    assert all(a != b for a, b in itertools.pairwise(roles))
    first_action = parse_action(messages[1]["content"])
    assert first_action.tool == "read"
    assert first_action.args == {"path": "src/toy/greet.py"}
    assert first_action.thought == "Read the module."
    assert messages[2]["content"] == "Result of read:\n" + GREET
    finish = parse_action(messages[-1]["content"])
    assert finish.tool == "finish"
    assert finish.args["report"].startswith("It returns")
    assert priorwork.rendered_chars(parsed) == sum(len(m["content"]) for m in messages)


def test_content_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = _parse(prior_work())
    assert priorwork.prior_work_problems(parsed) == []
    monkeypatch.setattr(priorwork, "PRIOR_WORK_CHARS", (10**6, 2 * 10**6))
    assert any("characters" in p for p in priorwork.prior_work_problems(parsed))


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("git log --oneline", "'git'"),
        ("cat a > b", "redirect"),
        ("ls\nls", "one line"),
        ("python3 -c 'print(1)'", "'python3'"),
        ("find . -delete", "-delete"),
        ("cat $(ls)", "substitution"),
        ("grep -n x src/a.py | sort | uniq -c", None),
        ("ls src && wc -l src/toy/greet.py", None),
        ("cat 'unterminated", "cannot be parsed"),
    ],
)
def test_command_rules(cmd: str, expected: str | None) -> None:
    data = _mutated("episodes.0.steps.1.args", {"cmd": cmd})
    problems = priorwork.prior_work_problems(_parse(data))
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


@pytest.mark.parametrize("path", ["/etc/passwd", "../x", "a/../../x", ".git/config", ""])
def test_read_path_rules(path: str) -> None:
    data = _mutated("episodes.0.steps.0.args", {"path": path})
    try:
        parsed = _parse(data)
    except PriorWorkError as exc:
        assert "path" in "\n".join(exc.problems)
        return
    assert any("path" in p for p in priorwork.prior_work_problems(parsed))


def _workspace(tmp_path: Path) -> Path:
    task = build_task(tmp_path / "project")
    work = tmp_path / "work"
    shutil.copytree(task / "repo", work)
    return work


def test_capture_and_compare(tmp_path: Path) -> None:
    work = _workspace(tmp_path)
    blank = _mutated("episodes.0.steps.1.output", "")
    blank["episodes"][0]["steps"][0]["output"] = ""
    sandbox = SubprocessSandbox(work)
    captured = priorwork.capture_outputs(_parse(blank), sandbox)
    assert captured.episodes[0].steps[0].output == GREET
    assert captured.episodes[0].steps[1].output == "6 src/toy/greet.py\n[exit code 0]"
    assert priorwork.compare_outputs(captured, sandbox) == []
    stale = _mutated("episodes.0.steps.1.output", "7 src/toy/greet.py\n[exit code 0]")
    problems = priorwork.compare_outputs(_parse(stale), sandbox)
    assert len(problems) == 1
    assert "differs from a fresh run" in problems[0]
    edited = _mutated("episodes.0.steps.0.output", "changed")
    assert "differs from the file" in priorwork.compare_outputs(_parse(edited), sandbox)[0]


def test_read_output_mirrors_the_runtime(tmp_path: Path) -> None:
    work = _workspace(tmp_path)
    assert priorwork.read_output(work, "missing.py") == "error: no such file: missing.py"
    assert priorwork.read_output(work, "../escape").startswith("error: path escapes")
    big = work / "big.txt"
    big.write_text("x" * (priorwork.MAX_READ_CHARS + 5), encoding="utf-8")
    out = priorwork.read_output(work, "big.txt")
    assert out.endswith(f"[file cut at {priorwork.MAX_READ_CHARS} characters]")


def test_shipped_pilot_prior_work_files_parse() -> None:
    root = Path(__file__).resolve().parents[2] / "bench" / "tasks"
    for path in sorted(root.glob("pilot-*/prior_work.json")):
        parsed = priorwork.load_prior_work(path)
        assert parsed.synthetic
        assert priorwork.prior_work_problems(parsed) == [], path
        json.loads(path.read_text(encoding="utf-8"))
