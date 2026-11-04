"""Tests for the ledger contract: hash chain, writer, reader, queries, and stream capping."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import get_args

import pytest

from receipts.ledger import events
from receipts.ledger.events import (
    EVENT_KINDS,
    GENESIS,
    MAX_STREAM_CHARS,
    Event,
    Ledger,
    LedgerWriter,
    canonical_json,
    cap_stream,
    read_ledger,
    sha256_text,
    verify_chain,
)


class Clock:
    """A deterministic clock: 1000.0, 1000.5, 1001.0, ..."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        value = self.now
        self.now += 0.5
        return value


def _write_sample(path: Path) -> LedgerWriter:
    """A small synthetic ledger (test data, not a real run)."""
    writer = LedgerWriter(path, clock=Clock())
    writer.append("run_start", {"run_id": "r1", "source": "harness"})
    writer.append("tool_call", {"tool": "bash", "input": {"cmd": "pytest"}, "source": "agent"})
    writer.append("command", {"cmd": "pytest", "exit_code": 1, "source": "agent"})
    writer.append("test_run", {"failed": 1, "command_seq": 2, "source": "agent"})
    writer.append("test_run", {"failed": 0, "command_seq": 2, "source": "snapshot"})
    writer.append("run_end", {"final_report": "All tests pass.", "source": "harness"})
    return writer


@pytest.fixture
def ledger_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "runs" / "r1" / "ledger.jsonl"
    _write_sample(path)
    yield path


def test_canonical_json_is_sorted_compact_and_keeps_unicode() -> None:
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": "café"}]}) == (
        '{"a":[1,{"c":"café","d":2}],"b":1}'
    )


def test_sha256_text_hashes_utf8() -> None:
    assert sha256_text("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_text("café") != sha256_text("cafe")


def test_cap_stream_leaves_short_text_alone() -> None:
    text = "x" * 10
    assert cap_stream(text, limit=10) == (text, False, sha256_text(text))


def test_cap_stream_keeps_head_and_tail_and_hashes_the_full_text() -> None:
    text = "HEAD" + "m" * 100 + "TAIL"
    capped, truncated, digest = cap_stream(text, limit=20)
    assert truncated
    assert digest == sha256_text(text)
    assert capped.startswith("HEAD") and capped.endswith("TAIL")
    assert "[... 88 chars elided by receipts ...]" in capped


def test_cap_stream_with_a_limit_below_two_keeps_no_tail() -> None:
    text = "abcdef"
    capped, truncated, _ = cap_stream(text, limit=1)
    assert truncated
    assert capped == "\n[... 6 chars elided by receipts ...]\n"


def test_cap_stream_default_limit() -> None:
    text = "q" * (MAX_STREAM_CHARS + 1)
    capped, truncated, _ = cap_stream(text)
    assert truncated
    assert capped.count("q") == MAX_STREAM_CHARS
    assert "[... 1 chars elided by receipts ...]" in capped


def test_event_kinds_match_the_literal() -> None:
    assert frozenset(get_args(events.EventKind)) == EVENT_KINDS
    assert "test_run" in EVENT_KINDS


def test_writer_builds_a_chain_from_genesis(tmp_path: Path) -> None:
    writer = _write_sample(tmp_path / "deep" / "ledger.jsonl")
    chain = writer.events
    assert isinstance(chain, tuple)
    assert [e.seq for e in chain] == list(range(6))
    assert chain[0].prev == GENESIS
    assert all(chain[i].prev == chain[i - 1].hash for i in range(1, 6))
    assert [e.ts for e in chain[:3]] == [1000.0, 1000.5, 1001.0]
    assert verify_chain(chain) == []


def test_writer_lines_are_the_canonical_event_json(ledger_path: Path) -> None:
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    loaded = read_ledger(ledger_path)
    assert lines == [event.to_json() for event in loaded]
    raw = json.loads(lines[0])
    assert set(raw) == {"seq", "ts", "kind", "data", "prev", "hash"}


def test_hash_covers_seq_ts_kind_data_and_prev() -> None:
    base = Event.compute_hash(0, 1.0, "command", {"a": 1}, GENESIS)
    assert base == Event.compute_hash(0, 1.0, "command", {"a": 1}, GENESIS)
    assert base != Event.compute_hash(1, 1.0, "command", {"a": 1}, GENESIS)
    assert base != Event.compute_hash(0, 2.0, "command", {"a": 1}, GENESIS)
    assert base != Event.compute_hash(0, 1.0, "diff", {"a": 1}, GENESIS)
    assert base != Event.compute_hash(0, 1.0, "command", {"a": 2}, GENESIS)
    assert base != Event.compute_hash(0, 1.0, "command", {"a": 1}, "1" * 64)


def test_append_rejects_unknown_kinds(tmp_path: Path) -> None:
    writer = LedgerWriter(tmp_path / "l.jsonl")
    with pytest.raises(ValueError, match="unknown event kind"):
        writer.append("thought", {"source": "agent"})
    assert not (tmp_path / "l.jsonl").exists()


def test_append_normalizes_payloads_and_honors_explicit_ts(tmp_path: Path) -> None:
    writer = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 5.0)
    event = writer.append("diff", {"files": ("a", "b"), "source": "snapshot"}, ts=7)
    assert event.ts == 7.0
    assert event.data["files"] == ["a", "b"]
    assert read_ledger(tmp_path / "l.jsonl")[0] == event


def test_from_json_round_trip_and_errors() -> None:
    event = Event(0, 1.5, "command", {"source": "agent"}, GENESIS, "h")
    assert Event.from_json(event.to_json()) == event
    assert event.source == "agent"
    assert Event(0, 1.5, "command", {}, GENESIS, "h").source == ""
    with pytest.raises(ValueError, match="not an object"):
        Event.from_json("[1, 2]")
    with pytest.raises(ValueError, match="missing or mistyped"):
        Event.from_json('{"seq": 0}')
    with pytest.raises(ValueError, match="missing or mistyped"):
        Event.from_json('{"seq": 0, "ts": 1, "kind": "x", "data": 3, "prev": "", "hash": ""}')


def test_read_ledger_skips_blank_lines_and_locates_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    event = writer.append("command", {"source": "agent"})
    path.write_text("\n" + event.to_json() + "\n\n", encoding="utf-8")
    assert read_ledger(path) == [event]
    path.write_text(event.to_json() + "\n{oops\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"l\.jsonl:2:"):
        read_ledger(path)


def test_resume_continues_the_chain(ledger_path: Path) -> None:
    resumed = LedgerWriter(ledger_path, clock=lambda: 2000.0)
    assert len(resumed.events) == 6
    event = resumed.append("diff", {"source": "snapshot"})
    assert event.seq == 6
    assert event.prev == resumed.events[5].hash
    reloaded = read_ledger(ledger_path)
    assert verify_chain(reloaded) == []
    assert reloaded[-1] == event


def _rewrite(path: Path, edit: object) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert callable(edit)
    path.write_text("\n".join(edit(lines)) + "\n", encoding="utf-8")


def _tamper_data(lines: list[str]) -> list[str]:
    raw = json.loads(lines[2])
    raw["data"]["exit_code"] = 0  # the agent's failing command now "passed"
    lines[2] = json.dumps(raw)
    return lines


def test_tampered_payload_is_detected(ledger_path: Path) -> None:
    _rewrite(ledger_path, _tamper_data)
    problems = verify_chain(read_ledger(ledger_path))
    assert problems == ["event 2 hash does not match its content"]
    with pytest.raises(ValueError, match="refusing to extend a broken ledger"):
        LedgerWriter(ledger_path)
    with pytest.raises(ValueError, match="hash does not match"):
        Ledger.load(ledger_path)
    assert len(Ledger.load(ledger_path, verify=False)) == 6


def test_rehashed_tampering_still_breaks_the_chain(ledger_path: Path) -> None:
    def edit(lines: list[str]) -> list[str]:
        event = Event.from_json(lines[2])
        data = dict(event.data, exit_code=0)
        new_hash = Event.compute_hash(event.seq, event.ts, event.kind, data, event.prev)
        lines[2] = Event(event.seq, event.ts, event.kind, data, event.prev, new_hash).to_json()
        return lines

    _rewrite(ledger_path, edit)
    assert verify_chain(read_ledger(ledger_path)) == ["event 3 does not chain to its predecessor"]


def test_dropped_and_reordered_events_are_detected(ledger_path: Path) -> None:
    chain = read_ledger(ledger_path)
    dropped = verify_chain(chain[:2] + chain[3:])
    assert "event 2 has seq 3" in dropped
    assert "event 2 does not chain to its predecessor" in dropped
    swapped = verify_chain([chain[1], chain[0], *chain[2:]])
    assert "event 0 has seq 1" in swapped
    assert "event 0 does not chain to its predecessor" in swapped


def test_unknown_kind_in_file_is_reported() -> None:
    data = {"source": "agent"}
    event = Event(
        0, 1.0, "thought", data, GENESIS, Event.compute_hash(0, 1.0, "thought", data, GENESIS)
    )
    assert verify_chain([event]) == ["event 0 has unknown kind 'thought'"]


def test_ledger_queries(ledger_path: Path) -> None:
    ledger = Ledger.load(ledger_path)
    assert len(ledger) == 6
    assert [e.seq for e in ledger] == list(range(6))
    assert ledger.get(2).kind == "command"
    assert [e.seq for e in ledger.of_kind("test_run")] == [3, 4]
    assert [e.seq for e in ledger.of_kind("test_run", "command", source="agent")] == [2, 3]
    last = ledger.last("test_run")
    assert last is not None and last.source == "snapshot"
    agent_last = ledger.last("test_run", source="agent")
    assert agent_last is not None and agent_last.seq == 3
    assert ledger.last("diff") is None
    assert [e.seq for e in ledger.after(3)] == [4, 5]
    assert [e.seq for e in ledger.after(0, "command", "run_end")] == [2, 5]
    start = ledger.run_start()
    assert start is not None and start.data["run_id"] == "r1"
    assert ledger.final_report() == "All tests pass."


def test_empty_ledger_queries() -> None:
    ledger = Ledger([])
    assert ledger.run_start() is None
    assert ledger.final_report() is None
    assert ledger.of_kind("command") == []
