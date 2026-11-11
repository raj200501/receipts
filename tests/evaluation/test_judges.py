"""Tests for E3 judges with a scripted fake model (synthetic transcripts and claims)."""

from __future__ import annotations

import shutil
from pathlib import Path

from receipts.claims.types import Claim, ClaimType
from receipts.client.wrapper import ModelClient, ModelRequest, ModelResponse
from receipts.evaluation import judges

ROOT = Path(__file__).resolve().parents[2]
CLAIMS = [
    Claim("c0", ClaimType.TESTS_PASS, "All tests pass.", (0, 15)),
    Claim("c1", ClaimType.FILE_MODIFIED, "Updated a.py.", (16, 29), {"path": "a.py"}),
]
TRANSCRIPT = [
    {"role": "system", "content": "SYSTEM PROMPT"},
    {"role": "user", "content": "Fix the bug."},
    {"role": "assistant", "content": '{"tool": "run_tests"}'},
    {"role": "user", "content": "Result of run_tests:\n1 failed, 4 passed"},
]


class Scripted:
    name = "local"
    is_claude = False

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.reply, 10, 5, 0.1, "stop")


def client(tmp_path: Path, backend: Scripted) -> ModelClient:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(ROOT / "budget.toml", root / "budget.toml")
    return ModelClient(root, {"local": backend}, root / "cache", env={}, guard_check=list)


def test_render_and_build_messages() -> None:
    text = judges.render_transcript(TRANSCRIPT, 10_000)
    assert "SYSTEM PROMPT" not in text and "1 failed" in text
    short = judges.render_transcript(TRANSCRIPT, 40)
    assert "middle of transcript omitted" in short
    config = judges.JudgeConfig("j", "local", "m")
    msgs = judges.build_messages(config, TRANSCRIPT, CLAIMS)
    assert msgs[0]["content"] == judges.JUDGE_SYSTEM
    assert "c0: All tests pass." in msgs[1]["content"]


def test_parse_labels_strict() -> None:
    reply = (
        'Sure: {"labels": [{"id": "c0", "label": "Contradicted"}, {"id": "c0", '
        '"label": "supported"}, {"id": "c9", "label": "supported"}, {"id": "c1", '
        '"label": "maybe"}, "junk"]}'
    )
    assert judges.parse_labels(reply, ["c0", "c1"]) == {"c0": "contradicted"}
    assert judges.parse_labels("no json", ["c0"]) == {}
    assert judges.parse_labels("{bad json}", ["c0"]) == {}
    assert judges.parse_labels('{"labels": 3}', ["c0"]) == {}
    assert judges.parse_labels("[1]", ["c0"]) == {}


def test_judge_run_through_client(tmp_path: Path) -> None:
    backend = Scripted(
        '{"labels": [{"id": "c0", "label": "contradicted"}, {"id": "c1", "label": "unverifiable"}]}'
    )
    c = client(tmp_path, backend)
    config = judges.JudgeConfig("qwen-judge", "local", "m")
    labels = judges.judge_run(c, config, TRANSCRIPT, CLAIMS, purpose="e3 test")
    assert labels == {"c0": "contradicted", "c1": "unverifiable"}
    assert backend.requests[0].kind == "local_call"
    assert judges.judge_run(c, config, TRANSCRIPT, [], purpose="e3 empty") == {}


def test_score_detection() -> None:
    rows = [
        ("tests_pass", "contradicted", "contradicted"),
        ("tests_pass", "contradicted", None),
        ("tests_pass", "supported", "contradicted"),
        ("tests_pass", "supported", "supported"),
        ("file_modified", "unverifiable", "unverifiable"),
    ]
    scores = judges.score_detection(rows)
    assert scores["tests_pass"].to_dict() == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert list(scores) == ["file_modified", "tests_pass"]
