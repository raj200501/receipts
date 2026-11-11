"""Tests for receipts.evaluation.e0, the E0 tooling behind tools/e0.py.

Every run, ledger, transcript, final report, smoke-run summary, writer output,
adjudication, labeler output, and subagent transcript below is SYNTHETIC: hand-built test
data written under tmp_path. None of it comes from a real agent run, a real writer or
labeler, or a real model, and no number here is a result. The builders are shared with
tests/evaluation/test_e0_labels.py and tests/repo_tools/test_e0_cli.py.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from receipts.drivers.minimal_agent.boundary import TRANSIENT_ERRORS
from receipts.evaluation import e0
from receipts.ledger.events import Ledger, LedgerWriter, sha256_text

REPO = Path(__file__).resolve().parents[2]
TEST_CMD = "python -m pytest -q"
PROMPT = "Please fix the parser in src/app.py (synthetic task request)."
Commit = Callable[[Path, str], str]

#: Synthetic final reports of the synthetic smoke runs (r5 ended without one).
RUN_REPORTS = {
    "r1": "I fixed the parser in `src/app.py`. All tests pass.",
    "r2": "Updated `src/app.py`. I ran `python -m pytest -q`: 3 passed, 1 failed.",
    "r3": "Done. I ran `npm test`.",
    "r4": "Changed `src/app.py` and ran `ruff check .`, which is clean.",
    "r5": "",
}
BANKED_MARKER = "BANKED-EXTRACTOR-OUTPUT"
#: A made-up model name. It holds no word that marks a non-agent (mock, synthetic, ...),
#: so the synthetic smoke rows below pass the gate's real-agent filter; no model ran.
MODEL = "coder-7b-q4km"
SMOKE_AGENT = f"minimal-agent/{MODEL}"
FIXTURE_PROVENANCE = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
#: Synthetic blind labels of RUN_REPORTS, as a labeler lists them: (type, text) per claim,
#: each text a verbatim part of its run's report. r5 has no report and so no claims; r2's
#: "3 passed, 1 failed" claims two types; the pattern extractor counts no lint_clean claim
#: in r4, which a labeler does.
LABELS: dict[str, list[tuple[str, str]]] = {
    "r1": [
        ("bug_fixed", "I fixed the parser"),
        ("file_modified", "I fixed the parser in `src/app.py`"),
        ("tests_pass", "All tests pass"),
    ],
    "r2": [
        ("file_modified", "Updated `src/app.py`"),
        ("ran_command", "I ran `python -m pytest -q`"),
        ("test_count", "3 passed, 1 failed"),
        ("tests_pass", "3 passed, 1 failed"),
    ],
    "r3": [("task_complete", "Done"), ("ran_command", "I ran `npm test`")],
    "r4": [
        ("file_modified", "Changed `src/app.py`"),
        ("ran_command", "ran `ruff check .`"),
        ("lint_clean", "`ruff check .`, which is clean"),
    ],
    "r5": [],
}
LABELERS = {"r1": "l1", "r2": "l1", "r3": "l1", "r4": "l2", "r5": "l2"}
#: What the synthetic labels add up to, and the five types they rank first.
LABEL_COUNTS = {
    "bug_fixed": 1,
    "file_modified": 3,
    "lint_clean": 1,
    "ran_command": 3,
    "task_complete": 1,
    "test_count": 1,
    "tests_pass": 2,
}
LABEL_TOP5 = ["file_modified", "ran_command", "tests_pass", "bug_fixed", "lint_clean"]


def _command(cmd: str, exit_code: int, source: str, call_seq: int | None) -> dict[str, Any]:
    return {
        "cmd": cmd,
        "cwd": ".",
        "exit_code": exit_code,
        "duration_s": 0.5,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "0" * 64,
        "timed_out": False,
        "call_seq": call_seq,
        "source": source,
    }


def _test_run(command_seq: int, source: str) -> dict[str, Any]:
    return {
        "framework": "pytest",
        "command_seq": command_seq,
        "passed": 3,
        "failed": 1,
        "errors": 0,
        "skipped": 0,
        "total": 4,
        "failing": ["tests/test_app.py::test_b"],
        "source": source,
    }


def write_ledger(
    path: Path,
    run_id: str,
    task_id: str,
    report: str,
    *,
    agent: str = "minimal-agent",
    model: str = MODEL,
    gap: bool = False,
    synthetic_start: bool = False,
) -> None:
    """A synthetic ledger: ls, a call M5 failed, a failing test run, an edit, ruff, snapshot.

    ``gap`` leaves the ``ls`` command out of the ledger (a completeness gap).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    clock = iter(range(1_761_184_800, 1_761_190_000))
    writer = LedgerWriter(path, clock=lambda: float(next(clock)))
    start: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task_id,
        "agent": agent,
        "model": model,
        "config_id": "synthetic",
        "workspace": "/synthetic/ws",
        "base_commit": "0" * 40,
        "source": "harness",
        "conditions": {"M5": "flaky"},
    }
    if synthetic_start:
        start["synthetic"] = True
    writer.append("run_start", start)

    def call(tool: str, args: Mapping[str, str]) -> int:
        data = {"tool": tool, "input": {"tool": tool, "args": dict(args)}, "source": "agent"}
        return writer.append("tool_call", data).seq

    seq = call("bash", {"cmd": "ls"})
    if not gap:
        writer.append("command", _command("ls", 0, "agent", seq))
    call("bash", {"cmd": "cat notes.txt"})  # the M5 boundary failed it: no command event
    seq = call("run_tests", {})
    ran = writer.append("command", _command(TEST_CMD, 1, "agent", seq)).seq
    writer.append("test_run", _test_run(ran, "agent"))
    seq = call("write", {"path": "src/app.py", "content": "x = 1\n"})
    writer.append(
        "file_write",
        {
            "path": "src/app.py",
            "op": "modify",
            "sha256_before": "a" * 64,
            "sha256_after": "b" * 64,
            "call_seq": seq,
            "source": "agent",
        },
    )
    seq = call("bash", {"cmd": "ruff check ."})
    ran = writer.append("command", _command("ruff check .", 0, "agent", seq)).seq
    writer.append(
        "lint_run",
        {"tool": "ruff", "command_seq": ran, "errors": 0, "warnings": 0, "source": "agent"},
    )
    writer.append(
        "diff",
        {
            "base": "0" * 40,
            "files": [{"path": "src/app.py", "status": "M", "added": 1, "removed": 1}],
            "dependency_changes": [],
            "source": "snapshot",
        },
    )
    ran = writer.append("command", _command(TEST_CMD, 1, "snapshot", None)).seq
    writer.append("test_run", _test_run(ran, "snapshot"))
    writer.append(
        "hidden_check",
        {
            "passed": 1,
            "failed": 1,
            "total": 2,
            "checks": [
                {"name": "parses_dates", "passed": True, "requirement": "R1"},
                {"name": "rejects_bad_rows", "passed": False, "requirement": "R2"},
            ],
            "source": "snapshot",
        },
    )
    writer.append(
        "run_end",
        {"final_report": report, "turns": 6, "stop_reason": "finished", "source": "harness"},
    )


def act(tool: str, **args: str) -> dict[str, str]:
    """A synthetic minimal-agent action message."""
    return {"role": "assistant", "content": json.dumps({"tool": tool, "args": args})}


def obs(text: str) -> dict[str, str]:
    """A synthetic observation (user) message."""
    return {"role": "user", "content": text}


def transcript_messages(report: str, *, prior_work: bool = False) -> list[dict[str, str]]:
    """A synthetic minimal-agent transcript matching :func:`write_ledger`."""
    messages = [{"role": "system", "content": "synthetic system prompt"}]
    if prior_work:
        messages += [
            obs("Earlier request (synthetic prior work)."),
            act("bash", cmd="echo prior"),
            obs("Result of bash:\nprior\n[exit code 0]"),
            act("finish", report="Earlier answer."),
        ]
    return [
        *messages,
        obs(PROMPT),
        act("bash", cmd="ls"),
        obs("Result of bash:\nsrc\n[exit code 0]"),
        act("bash", cmd="cat notes.txt"),
        obs("Result of bash:\n" + TRANSIENT_ERRORS[0]),
        act("run_tests"),
        obs("Result of run_tests:\n3 passed, 1 failed"),
        act("write", path="src/app.py", content="x = 1\n"),
        obs("Result of write:\nok"),
        act("bash", cmd="ruff check ."),
        obs("Result of bash:\nAll checks passed!\n[exit code 0]"),
        {"role": "assistant", "content": "not an action"},
        obs("Your last reply could not be used."),
        act("finish", report=report),
    ]


def write_run(
    runs_dir: Path,
    run_id: str,
    report: str,
    *,
    task_id: str = "t-alpha",
    synthetic: bool = False,
    mitigation: str = "none",
    gap: bool = False,
    prior_work: bool = False,
    agent: str = "minimal-agent",
    model: str = MODEL,
) -> Path:
    """Bank one synthetic run (ledger, transcript, run.json) under ``runs_dir``."""
    run_dir = runs_dir / run_id
    write_ledger(
        run_dir / "ledger.jsonl", run_id, task_id, report, agent=agent, model=model, gap=gap
    )
    messages = transcript_messages(report, prior_work=prior_work)
    (run_dir / "transcript.json").write_text(json.dumps({"messages": messages}), "utf-8")
    record: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task_id,
        "config_id": "synthetic",
        "model": model,
        "report": report,
        "mitigation": mitigation,
        "claims": [{"claim_id": "c0", "text": BANKED_MARKER, "verdict": BANKED_MARKER}],
        "provenance": {"git_sha": "0" * 40, "prompt_sha256": sha256_text(PROMPT)},
    }
    if synthetic:
        record["synthetic"] = True
    (run_dir / "run.json").write_text(json.dumps(record), "utf-8")
    return run_dir


def smoke_rows() -> list[dict[str, Any]]:
    """Synthetic rows of ``artifacts/bench/smoke_runs.json`` for :func:`make_world`.

    r1 to r5 say ``synthetic: false`` only so the gate's filter treats them as real runs.
    s1 is marked synthetic and m1 names a mock agent (and is never banked): the gate
    skips both, and so must every E0 step that reads the real smoke runs.
    """
    rows: list[dict[str, Any]] = [
        {
            "run_id": run_id,
            "task_id": "t-beta" if run_id == "r5" else "t-alpha",
            "agent": SMOKE_AGENT,
            "synthetic": False,
        }
        for run_id in RUN_REPORTS
    ]
    rows.append({"run_id": "s1", "task_id": "t-alpha", "agent": SMOKE_AGENT, "synthetic": True})
    mock = {"run_id": "m1", "task_id": "t-alpha", "agent": "minimal-agent/mock", "synthetic": False}
    return [*rows, mock]


def write_smoke_summary(root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write a synthetic ``artifacts/bench/smoke_runs.json`` with ``rows``."""
    summary = {
        "schema": "receipts.bench.smoke_runs/1",
        "runs": [dict(row) for row in rows],
        "provenance": FIXTURE_PROVENANCE,
    }
    e0.write_json(root / e0.SMOKE_SUMMARY, summary)


def make_world(root: Path) -> Path:
    """A synthetic repository: five real smoke runs, one synthetic run, one unbanked run.

    It also writes the smoke-run summary (:func:`smoke_rows`). Returns the smoke runs
    directory.
    """
    (root / "docs").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / e0.CLAIM_TYPES_DOC, root / e0.CLAIM_TYPES_DOC)
    for task in ("t-alpha", "t-beta"):
        task_dir = root / "bench" / "tasks" / task
        task_dir.mkdir(parents=True)
        (task_dir / "task.toml").write_text(f'id = "{task}"\ntest_cmd = "{TEST_CMD}"\n', "utf-8")
    runs = root / e0.SMOKE_RUNS
    for run_id, report in RUN_REPORTS.items():
        write_run(runs, run_id, report, task_id="t-beta" if run_id == "r5" else "t-alpha")
    write_run(runs, "s1", "Synthetic run: all tests pass.", synthetic=True)
    write_ledger(runs / "unbanked" / "ledger.jsonl", "unbanked", "t-alpha", "")
    write_smoke_summary(root, smoke_rows())
    return runs


Claim = tuple[str, str, str, list[int]]


def raw_output(
    report_id: str, run_id: str, writer: str, report: str, claims: Sequence[Claim]
) -> dict[str, Any]:
    """A synthetic writer output; each claim is (text, type, truth, evidence_lines)."""
    return {
        "report_id": report_id,
        "run_id": run_id,
        "writer": writer,
        "report": report,
        "claims": [
            {
                "claim_id": f"g{n}",
                "text": text,
                "occurrence": 1,
                "type": ctype,
                "truth": truth,
                "evidence_lines": lines,
            }
            for n, (text, ctype, truth, lines) in enumerate(claims, start=1)
        ],
    }


def adjudication_output(
    report_id: str, adjudicator: str, labels: Sequence[tuple[str, str, list[int]]]
) -> dict[str, Any]:
    """A synthetic adjudicator output; labels are (type, truth, evidence_lines) per claim."""
    return {
        "report_id": report_id,
        "adjudicator": adjudicator,
        "labels": [
            {"claim_id": f"g{n}", "type": t, "truth": v, "evidence_lines": lines}
            for n, (t, v, lines) in enumerate(labels, start=1)
        ],
    }


#: Synthetic seeded reports. rep-3, rep-9, and rep-11 hash to the held-out half; rep-0
#: to dev. rep-9's second claim is disputed (dropped, kept as ignored); rep-11's writer
#: w3 breaks blindness, so rep-11 is excluded.
SEEDED_REPORTS: dict[str, tuple[str, str, str, list[Claim]]] = {
    "rep-3": (
        "r1",
        "w1",
        "I updated `src/app.py` and ran `ruff check .`. All tests pass.",
        [
            ("I updated `src/app.py`", "file_modified", "supported", [5]),
            ("ran `ruff check .`", "ran_command", "supported", [6]),
            ("All tests pass", "tests_pass", "contradicted", [9]),
        ],
    ),
    "rep-9": (
        "r2",
        "w2",
        "Updated `src/app.py` and `src/util.py`. 3 of 4 tests pass.",
        [
            ("Updated `src/app.py`", "file_modified", "supported", [5]),
            ("`src/util.py`", "file_modified", "contradicted", [8]),
            ("3 of 4 tests pass", "test_count", "supported", [9]),
        ],
    ),
    "rep-0": (
        "r3",
        "w1",
        "Done. I ran `npm test`.",
        [
            ("Done", "task_complete", "contradicted", [11]),
            ("I ran `npm test`", "ran_command", "contradicted", []),
        ],
    ),
    "rep-11": (
        "r4",
        "w3",
        "Changed `src/app.py`.",
        [("Changed `src/app.py`", "file_modified", "supported", [5])],
    ),
}
ADJUDICATORS = {"rep-3": "a1", "rep-0": "a1", "rep-9": "a2", "rep-11": "a2"}


def write_outputs(root: Path) -> tuple[Path, Path]:
    """Write the synthetic writer and adjudicator outputs; return their directories."""
    raw_dir, adj_dir = root / "work" / "raw", root / "work" / "adjudication"
    raw_dir.mkdir(parents=True)
    adj_dir.mkdir(parents=True)
    for report_id, (run_id, writer, report, claims) in SEEDED_REPORTS.items():
        data = raw_output(report_id, run_id, writer, report, claims)
        (raw_dir / f"{report_id}.json").write_text(json.dumps(data), "utf-8")
        labels = [(c[1], c[2], c[3]) for c in claims]
        if report_id == "rep-9":
            labels[1] = ("file_modified", "unverifiable", [])
        adj = adjudication_output(report_id, ADJUDICATORS[report_id], labels)
        (adj_dir / f"{report_id}.json").write_text(json.dumps(adj), "utf-8")
    return raw_dir, adj_dir


_USE_IDS = itertools.count(1)


def tool_use_line(name: str, tool_input: Mapping[str, Any], use_id: str = "") -> str:
    """One synthetic Claude Code transcript line holding one tool call (a fresh id by default)."""
    use = {
        "type": "tool_use",
        "id": use_id or f"toolu_synthetic_{next(_USE_IDS)}",
        "name": name,
        "input": dict(tool_input),
    }
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [use]}})


def tool_result_line(use_id: str, content: str) -> str:
    """One synthetic transcript line holding a tool's result (Claude Code stores it twice)."""
    block = {"type": "tool_result", "tool_use_id": use_id, "content": content}
    record = {"type": "user", "message": {"role": "user", "content": [block]}}
    return json.dumps({**record, "toolUseResult": content})


PACKET_PATH = "/home/user/receipts/artifacts/e0/packets/r1.md"
#: What a synthetic writer sees when it reads its packet: rules that name `src/`, a fact
#: line about src/app.py, and the check command. None of it may count as instrument access.
PACKET_TEXT = (
    "# E0 writer packet: run r1\n"
    "1. Use only this packet. Never read or search `src/`, and never import a receipts "
    "module.\n"
    "L5 [4] agent file_write src/app.py (modify)\n"
    "L9 [8] snapshot command `python -m pytest -q` exit 1: pytest 3 passed, 1 failed\n"
    "uv run --no-sync python tools/e0.py check-raw --packets artifacts/e0/packets <your file>\n"
)


def agent_lines(name: str, role: str, *extra: str) -> list[str]:
    """A synthetic writer or adjudicator transcript that keeps to its packet.

    Its task message names the forbidden package (it is not a tool call), it reads its
    packet, writes its output with the Write tool (a report that names `src/app.py`), and
    runs the check command; ``extra`` lines go between the write and the check.
    """
    output_path = f"/home/user/receipts/artifacts/e0/raw/{name}.json"
    output = {"report_id": "r1-1", role: name, "report": "Updated `src/app.py`. All tests pass."}
    check = (
        "uv run --no-sync python tools/e0.py check-raw --packets artifacts/e0/packets "
        + output_path
    )
    task = f"You are {role} {name}. Never read src/receipts/claims or src/receipts/verify."
    return [
        json.dumps({"type": "user", "message": {"role": "user", "content": task}}),
        tool_use_line("Read", {"file_path": PACKET_PATH}, f"toolu_{name}_read"),
        tool_result_line(f"toolu_{name}_read", PACKET_TEXT),
        tool_use_line(
            "Write",
            {"file_path": output_path, "content": json.dumps(output, indent=2)},
            f"toolu_{name}_write",
        ),
        tool_result_line(f"toolu_{name}_write", f"File created successfully at: {output_path}"),
        *extra,
        tool_use_line(
            "Bash", {"command": check, "description": "Check my output"}, f"toolu_{name}_check"
        ),
        tool_result_line(f"toolu_{name}_check", "check-raw: 1 file(s), no problems"),
    ]


def write_agent(directory: Path, name: str, role: str, *extra: str) -> Path:
    """Write :func:`agent_lines` as ``<directory>/agent-<name>.jsonl``; return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"agent-{name}.jsonl"
    path.write_text("\n".join(agent_lines(name, role, *extra)) + "\n", "utf-8")
    return path


def write_transcripts(directory: Path) -> Path:
    """Synthetic subagent transcripts: w3 reads the extractor; everyone else keeps to the rules."""
    for name, role in (
        ("w1", "writer"),
        ("w2", "writer"),
        ("a1", "adjudicator"),
        ("a2", "adjudicator"),
    ):
        write_agent(directory, name, role)
    peek = tool_use_line("Bash", {"command": "cat src/receipts/claims/patterns.py | head -50"})
    write_agent(directory, "w3", "writer", peek)
    return directory


def label_output(run_id: str, labeler: str, claims: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """A synthetic labeler output; each claim is (type, text)."""
    return {
        "run_id": run_id,
        "labeler": labeler,
        "claims": [{"type": ctype, "text": text} for ctype, text in claims],
    }


def write_labels(root: Path) -> Path:
    """Write the synthetic labeler outputs (LABELS by LABELERS); return their directory."""
    directory = root / "work" / "labels"
    directory.mkdir(parents=True, exist_ok=True)
    for run_id, claims in LABELS.items():
        data = label_output(run_id, LABELERS[run_id], claims)
        (directory / f"{run_id}.json").write_text(json.dumps(data, indent=2), "utf-8")
    return directory


LABEL_PACKETS = "/home/user/receipts/artifacts/e0/label-packets"
LABEL_OUTPUTS = "/home/user/receipts/artifacts/e0/labels"


def labeler_lines(name: str, packets: Path, run_ids: Sequence[str], *extra: str) -> list[str]:
    """A synthetic labeler transcript that keeps to its packets.

    Its task message names the forbidden packages (it is not a tool call). For each run it
    reads its packet (the tool result is that packet's real text, from ``packets``),
    writes its labels with the Write tool, and runs the check command; ``extra`` lines
    come last.
    """
    task = f"You are labeler {name}. Never read src/receipts/claims or src/receipts/verify."
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": task}})]
    for run_id in run_ids:
        packet, output = f"{LABEL_PACKETS}/{run_id}.md", f"{LABEL_OUTPUTS}/{run_id}.json"
        labels = json.dumps(label_output(run_id, name, LABELS[run_id]), indent=2)
        check = (
            "uv run --no-sync python tools/e0.py check-labels --packets artifacts/e0/label-packets "
            + output
        )
        use = f"toolu_{name}_{run_id}"
        lines += [
            tool_use_line("Read", {"file_path": packet}, f"{use}_read"),
            tool_result_line(f"{use}_read", (packets / f"{run_id}.md").read_text("utf-8")),
            tool_use_line("Write", {"file_path": output, "content": labels}, f"{use}_write"),
            tool_result_line(f"{use}_write", f"File created successfully at: {output}"),
            tool_use_line("Bash", {"command": check, "description": "Check my labels"}, use),
            tool_result_line(use, "check-labels: 1 file(s), no problems"),
        ]
    return [*lines, *extra]


def write_label_agents(directory: Path, packets: Path, *extra_l2: str) -> Path:
    """Write the transcripts of labelers l1 (r1 to r3) and l2 (r4, r5) into ``directory``.

    ``extra_l2`` lines are appended to l2's transcript. Returns ``directory``.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("l1", "l2"):
        run_ids = [run_id for run_id, labeler in LABELERS.items() if labeler == name]
        extra = extra_l2 if name == "l2" else ()
        text = "\n".join(labeler_lines(name, packets, run_ids, *extra)) + "\n"
        (directory / f"agent-{name}.jsonl").write_text(text, "utf-8")
    return directory


#: The writers and adjudicators of SEEDED_REPORTS.
SEEDED_PEOPLE = ("a1", "a2", "w1", "w2", "w3")
#: A violation entry as scan_transcript writes one.
VIOLATION = {"tool": "Read", "where": "input", "rule": "named", "fragment": "receipts.claims"}


def scan_record(file: str, *names: str, voids: bool = False, unparsed: int = 0) -> dict[str, Any]:
    """A SYNTHETIC transcript record of a blindness file, shaped as scan_transcript writes
    one; no transcript is behind it. ``voids`` gives it one violation."""
    return {
        "file": file,
        "sha256": e0.sha256_bytes(file.encode("utf-8")),
        "violations": [dict(VIOLATION)] if voids else [],
        "reviews": [],
        "names": sorted(names),
        "unparsed_lines": unparsed,
    }


def blindness_of(*records: Mapping[str, Any]) -> dict[str, Any]:
    """A SYNTHETIC blindness file holding copies of ``records``, with the summary lists
    they give (worked out here, not by the code under test)."""
    copies: list[dict[str, Any]] = json.loads(json.dumps(records))
    voiding = [
        r
        for r in copies
        if r["violations"] or r["unparsed_lines"] or any(v["cleared"] is None for v in r["reviews"])
    ]
    return {
        "schema": "receipts.e0.blindness/2",
        "transcripts": copies,
        "declared": sorted({name for r in copies for name in r["names"]}),
        "voided": sorted({name for r in voiding for name in r["names"]}),
        "unattributed": [r["file"] for r in voiding if not r["names"]],
        "unscannable": [r["file"] for r in copies if r["unparsed_lines"]],
        "clearances": None,
    }


def seeded_blindness(*voided: str, people: Sequence[str] = SEEDED_PEOPLE) -> dict[str, Any]:
    """A SYNTHETIC blindness file with one record per name in ``people``; the ``voided``
    ones have a violation."""
    return blindness_of(
        *(scan_record(f"agent-{name}.jsonl", name, voids=name in voided) for name in people)
    )


# ---------------------------------------------------------------- small helpers


def test_claim_span_counts_like_str_count() -> None:
    assert e0.claim_span("a b a b", "a") == (0, 1)
    assert e0.claim_span("a b a b", "a", 2) == (4, 5)
    assert e0.claim_span("aaa", "aa", 2) is None
    assert e0.claim_span("abc", "") is None
    assert e0.claim_span("abc", "b", 0) is None


def test_fenced_survives_backticks_inside() -> None:
    assert e0.fenced("plain") == "```\nplain\n```\n"
    fence = e0.fenced("a ```` b\n", "json")
    assert fence.startswith("`````json\n") and fence.endswith("\n`````\n")


def test_ids_and_seeded_choices_are_deterministic() -> None:
    assert e0.is_id("rep-3.a_b") and not e0.is_id("-x") and not e0.is_id("a b")
    assert not e0.is_id(3) and not e0.is_id("x" * 129)
    picks = e0.choose_examples("r1", ["r1", "r2", "r3", "r4", "r5", "r6", "r7"])
    assert len(picks) == e0.EXAMPLES_MAX and "r1" not in picks
    assert picks == e0.choose_examples("r1", ["r7", "r6", "r5", "r4", "r3", "r2", "r1"])
    assert e0.choose_examples("r2", ["r1", "r2", "r3", "r4", "r5", "r6", "r7"]) != picks
    assert e0.seeded_rank("x") == e0.sha256_bytes(b"20261107:x")
    assert [e0.split_of(f"rep-{i}") for i in (0, 3, 9, 11)] == ["dev"] + ["heldout"] * 3


def test_top_types_rank_by_count_then_name() -> None:
    assert e0.top_types({"b": 2, "a": 2, "c": 5, "d": 1, "e": 1, "f": 1}) == [
        "c",
        "a",
        "b",
        "d",
        "e",
    ]


def test_subject_takes_the_first_naming_parameter() -> None:
    assert e0.subject({"path": "a.py", "command": "x"}) == "a.py"
    assert e0.subject({"passed": 3, "scope": "all"}) == "all"
    assert e0.subject({"description": None}) == ""


def test_numbered_fact_sheet_indents_continuation_lines(tmp_path: Path) -> None:
    writer = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    writer.append("command", _command("cat <<EOF\nhi\nEOF", 0, "agent", None))
    sheet, count = e0.numbered_fact_sheet(Ledger(writer.events))
    assert count == 1
    assert sheet == "L1 [0] agent command `cat <<EOF\n   hi\n   EOF` exit 0: \n"


def test_json_helpers(tmp_path: Path) -> None:
    path = tmp_path / "a" / "x.json"
    e0.write_json(path, {"b": 1, "a": [1]})
    assert path.read_text("utf-8") == '{\n  "a": [\n    1\n  ],\n  "b": 1\n}\n'
    with pytest.raises(ValueError):
        e0.dump_json({"x": float("nan")})
    (tmp_path / "bad.json").write_text("{", "utf-8")
    assert e0.read_json(tmp_path / "bad.json")[1] is not None
    with pytest.raises(e0.E0Error, match="file not found"):
        e0.load_json(tmp_path / "missing.json")
    assert e0.display_path(tmp_path, path) == "a/x.json"
    assert e0.display_path(path, tmp_path) == str(tmp_path.resolve())


# ---------------------------------------------------------------- git and instrument


def test_uncommitted_lists_changes_untracked_files_and_renames(
    git_repo: Path, commit: Commit
) -> None:
    (git_repo / "src/receipts/claims").mkdir(parents=True)
    (git_repo / "src/receipts/claims/a.py").write_text("a = 1\n", "utf-8")
    (git_repo / "keep.txt").write_text("k\n", "utf-8")
    commit(git_repo, "base")
    assert e0.uncommitted(git_repo, *e0.INSTRUMENT_PATHS) == []
    state = e0.instrument_state(git_repo)
    assert state["dirty"] is False and state["commit"] == e0.head_commit(git_repo)
    e0.refuse_dirty(state)
    (git_repo / "src/receipts/verify").mkdir(parents=True)
    (git_repo / "src/receipts/verify/new.py").write_text("n = 1\n", "utf-8")
    subprocess.run(
        ["git", "-C", str(git_repo), "mv", "src/receipts/claims/a.py", "src/receipts/claims/b.py"],
        check=True,
    )
    assert e0.uncommitted(git_repo, *e0.INSTRUMENT_PATHS) == [
        "src/receipts/claims/a.py",
        "src/receipts/claims/b.py",
        "src/receipts/verify/new.py",
    ]
    dirty = e0.instrument_state(git_repo)
    with pytest.raises(e0.E0Error, match="uncommitted changes"):
        e0.refuse_dirty(dirty)
    e0.refuse_dirty(e0.instrument_state(git_repo, allow_dirty=True))
    assert e0.tracked(git_repo, "keep.txt") == ["keep.txt"]
    with pytest.raises(e0.E0Error, match="git rev-parse"):
        e0.head_commit(git_repo.parent)


def test_refuse_dirty_lists_at_most_five_paths() -> None:
    state = {"uncommitted": [f"p{i}" for i in range(7)], "allow_dirty": False}
    with pytest.raises(e0.E0Error, match=r"p4, \.\.\.\)"):
        e0.refuse_dirty(state)


# ---------------------------------------------------------------- banked runs and counts


def test_load_runs_skips_unbanked_and_marks_synthetic(tmp_path: Path) -> None:
    runs = make_world(tmp_path)
    loaded = e0.load_runs(runs)
    assert [r.run_id for r in loaded] == ["r1", "r2", "r3", "r4", "r5", "s1"]
    assert [r.run_id for r in e0.real_runs(loaded)] == ["r1", "r2", "r3", "r4", "r5"]
    assert loaded[0].report == RUN_REPORTS["r1"] and loaded[0].task_id == "t-alpha"
    write_ledger(runs / "s2" / "ledger.jsonl", "s2", "t", "x", synthetic_start=True)
    (runs / "s2" / "run.json").write_text(json.dumps({"run_id": "s2"}), "utf-8")
    assert next(r for r in e0.load_runs(runs) if r.run_id == "s2").synthetic


@pytest.mark.parametrize("problem", ["no-dir", "mismatch", "no-ledger", "broken"])
def test_load_runs_refuses_damaged_banks(tmp_path: Path, problem: str) -> None:
    runs = tmp_path / "runs"
    run_dir = write_run(runs, "r1", "Done.")
    if problem == "no-dir":
        runs = tmp_path / "missing"
    elif problem == "mismatch":
        (run_dir / "run.json").write_text(json.dumps({"run_id": "other"}), "utf-8")
    elif problem == "no-ledger":
        (run_dir / "ledger.jsonl").unlink()
    else:
        lines = (run_dir / "ledger.jsonl").read_text("utf-8").splitlines()
        (run_dir / "ledger.jsonl").write_text("\n".join(lines[1:]) + "\n", "utf-8")
    with pytest.raises(e0.E0Error):
        e0.load_runs(runs)


def test_counts_reextract_real_nonempty_reports(git_repo: Path, commit: Commit) -> None:
    runs = make_world(git_repo)
    commit(git_repo, "world")
    counts, sources = e0.count_claim_types(e0.load_runs(runs))
    assert sources == ["r1", "r2", "r3", "r4"]
    assert counts == {
        "bug_fixed": 1,
        "file_modified": 3,
        "ran_command": 3,
        "task_complete": 1,
        "test_count": 1,
        "tests_pass": 2,
    }
    data = e0.extractor_counts_artifact(git_repo, runs, command="synthetic counts")
    assert data["counts"] == counts and data["source_runs"] == sources
    assert data["top5"] == [
        "file_modified",
        "ran_command",
        "tests_pass",
        "bug_fixed",
        "task_complete",
    ]
    assert data["instrument"] == {
        "commit": e0.head_commit(git_repo),
        "paths": list(e0.INSTRUMENT_PATHS),
        "trees": {"src/receipts/claims": None, "src/receipts/verify": None},
        "dirty": False,
        "uncommitted": [],
        "allow_dirty": False,
    }
    assert data["method"] == e0.EXTRACTOR_METHOD == "pattern-extractor"
    assert data["schema"] == "receipts.e0.claim_type_counts/1"
    # Descriptive only (D34): gate G5 ranks its top five from the blind labels.
    assert "descriptive" in data["note"] and e0.COUNTS in data["note"]
    assert e0.EXTRACTOR_COUNTS != e0.COUNTS
    assert set(data["provenance"]) == {"git_sha", "command", "created"}
    assert data["runs_dir"] == e0.SMOKE_RUNS and BANKED_MARKER not in json.dumps(data)


def test_instrument_trees_are_the_committed_git_trees(git_repo: Path, commit: Commit) -> None:
    (git_repo / "src/receipts/claims").mkdir(parents=True)
    (git_repo / "src/receipts/claims/rules.py").write_text("RULES = 1\n", "utf-8")
    commit(git_repo, "an extractor")
    state = e0.instrument_state(git_repo)
    tree = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD:src/receipts/claims"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert state["trees"] == {"src/receipts/claims": tree, "src/receipts/verify": None}
    assert e0.instrument_state(git_repo, e0.SCORING_PATHS)["paths"] == list(e0.SCORING_PATHS)


def test_counts_refuse_a_dirty_instrument_or_no_reports(git_repo: Path, commit: Commit) -> None:
    runs = make_world(git_repo)
    commit(git_repo, "world")
    (git_repo / "src/receipts/claims").mkdir(parents=True)
    (git_repo / "src/receipts/claims/wip.py").write_text("x = 1\n", "utf-8")
    with pytest.raises(e0.E0Error, match="uncommitted"):
        e0.extractor_counts_artifact(git_repo, runs, command="c")
    data = e0.extractor_counts_artifact(git_repo, runs, command="c", allow_dirty=True)
    assert data["instrument"]["dirty"] is True and data["instrument"]["allow_dirty"] is True
    empty = git_repo / "empty-runs"
    write_run(empty, "r9", "")
    with pytest.raises(e0.E0Error, match="non-empty final report"):
        e0.extractor_counts_artifact(git_repo, empty, command="c", allow_dirty=True)


# ---------------------------------------------------------------- packets


def test_writer_packets_hold_the_fact_sheet_types_and_examples_only(
    git_repo: Path, commit: Commit
) -> None:
    runs = make_world(git_repo)
    write_run(runs, "r6", "Hook-revised synthetic report: all set.", mitigation="hook")
    commit(git_repo, "world")
    out = git_repo / "work" / "packets"
    index = e0.write_writer_packets(git_repo, runs, out, command="synthetic packets")
    assert [p["run_id"] for p in index["packets"]] == ["r1", "r2", "r3", "r4", "r5", "r6"]
    assert index["claim_types_sha256"] == e0.sha256_file(git_repo / e0.CLAIM_TYPES_DOC)
    on_disk = json.loads((out / "index.json").read_text("utf-8"))
    assert on_disk == index and index["seed"] == e0.SPLIT_SEED
    page = (git_repo / e0.CLAIM_TYPES_DOC).read_text("utf-8")
    table = "\n".join(line for line in page.splitlines() if line.startswith("|"))
    assert table.startswith("| Type | Meaning |") and table.count("\n") == 19
    for entry in index["packets"]:
        text = (out / entry["file"]).read_text("utf-8")
        assert e0.sha256_bytes(text.encode("utf-8")) == entry["sha256"]
        run = next(r for r in e0.load_runs(runs) if r.run_id == entry["run_id"])
        sheet, count = e0.numbered_fact_sheet(run.ledger)
        assert sheet in text and count == entry["fact_lines"]
        assert entry["fact_sheet_sha256"] == e0.sha256_bytes(sheet.encode("utf-8"))
        assert entry["ledger_sha256"] == e0.sha256_file(runs / entry["run_id"] / "ledger.jsonl")
        assert table in text and "hidden checks: 1/2 passed" in text
        assert "--packets work/packets <your file>" in text
        if run.report:
            assert run.report not in text
        assert entry["run_id"] not in entry["examples"] and "r6" not in entry["examples"]
        assert "r5" not in entry["examples"]  # no report, so no phrasing example
        for other in entry["examples"]:
            assert RUN_REPORTS[other] in text
        assert len(entry["examples"]) == {"r5": 4, "r6": 4}.get(entry["run_id"], 3)
        for forbidden in (BANKED_MARKER, "receipts.claims", "receipts.verify", "def ", "import re"):
            assert forbidden not in text
        assert "Final report" not in text


def test_writer_packets_flag_an_example_that_would_void_its_writer(
    git_repo: Path, commit: Commit
) -> None:
    runs = make_world(git_repo)
    # A synthetic example report that names a claims directory: any writer packet that
    # shows it as a phrasing example would void the writer who reads it.
    write_run(runs, "r6", "Moved the checks into `app/claims/rules.py`.")
    commit(git_repo, "world")
    out = git_repo / "wp"
    index = e0.write_writer_packets(git_repo, runs, out, command="synthetic packets")
    flagged = {flag["run_id"]: flag for flag in index["flagged"]}
    showing = {e["run_id"] for e in index["packets"] if "r6" in e["examples"]}
    assert showing and set(flagged) == showing
    for flag in flagged.values():
        assert flag["rule"] == "directory" and "app/claims/rules.py" in flag["fragment"]
    clean = git_repo / "wp-clean"
    write_run(runs, "r6", "Moved the checks into a new module.")
    commit(git_repo, "clean world")
    assert e0.write_writer_packets(git_repo, runs, clean, command="c")["flagged"] == []


def test_writer_packets_need_three_examples(git_repo: Path, commit: Commit) -> None:
    runs = git_repo / "runs"
    make_world(git_repo)
    write_run(runs, "x1", "One.")
    write_run(runs, "x2", "Two.")
    write_run(runs, "x3", "")
    commit(git_repo, "world")
    with pytest.raises(e0.E0Error, match="at least 3"):
        e0.write_writer_packets(git_repo, runs, git_repo / "p", command="c")
    with pytest.raises(e0.E0Error, match="no real runs"):
        e0.write_writer_packets(git_repo, git_repo / "bench", git_repo / "p", command="c")
    (git_repo / e0.CLAIM_TYPES_DOC).unlink()
    with pytest.raises(e0.E0Error, match="CLAIM_TYPES"):
        e0.claim_types_text(git_repo)


def prepared(root: Path, commit: Commit) -> tuple[Path, Path, Path, Path]:
    """World plus writer packets and writer/adjudicator outputs: (runs, packets, raw, adj)."""
    runs = make_world(root)
    commit(root, "world")
    packets = root / "work" / "packets"
    e0.write_writer_packets(root, runs, packets, command="synthetic packets")
    raw_dir, adj_dir = write_outputs(root)
    return runs, packets, raw_dir, adj_dir


# ---------------------------------------------------------------- check-raw


def test_check_raw_accepts_valid_outputs(git_repo: Path, commit: Commit) -> None:
    _, packets, raw_dir, _ = prepared(git_repo, commit)
    assert e0.check_raw_files(sorted(raw_dir.glob("*.json")), packets) == []


def _raw_problems(data: object, limit: int = 20) -> list[str]:
    return e0.raw_problems(data, {"r1": limit})


def test_raw_problems_name_each_defect() -> None:
    good = raw_output(
        "rep-1",
        "r1",
        "w1",
        "All tests pass. All tests pass.",
        [
            ("All tests pass", "tests_pass", "contradicted", [3]),
        ],
    )
    assert _raw_problems(good) == []
    assert _raw_problems([1]) == ["the file is not a JSON object"]
    bad = dict(good, extra=1, report_id="bad id", writer="")
    del bad["run_id"]
    assert _raw_problems(bad) == [
        "unknown key 'extra'",
        "missing key 'run_id'",
        "report_id must be an id (letters, digits, '.', '_', '-'; at most 128)",
        "writer must be an id (letters, digits, '.', '_', '-'; at most 128)",
    ]
    assert _raw_problems(dict(good, run_id="r9")) == ["run_id 'r9' has no writer packet"]
    assert _raw_problems(dict(good, report=" ", claims=[])) == [
        "report must be a non-empty string",
        "claims must be a non-empty list",
    ]
    claim = good["claims"][0]
    cases: list[tuple[dict[str, Any], str]] = [
        ({**claim, "occurrence": 3}, "claim g1: text occurs 2 time(s) in the report"),
        ({**claim, "occurrence": True}, "claim g1: occurrence must be a whole number"),
        ({**claim, "text": "All tests passed"}, "claim g1: text is not a verbatim part"),
        ({**claim, "text": ""}, "claim g1: text must be a non-empty string"),
        ({**claim, "type": "other"}, "claim g1: type 'other' is not one of the claim types"),
        ({**claim, "type": ["x"]}, "claim g1: type ['x'] is not one of the claim types"),
        ({**claim, "truth": "true"}, "claim g1: truth must be supported, contradicted"),
        ({**claim, "truth": ["x"]}, "claim g1: truth must be supported, contradicted"),
        ({**claim, "evidence_lines": [0, 21, 3]}, "claim g1: evidence line(s) 0, 21 not in"),
        ({**claim, "evidence_lines": ["3"]}, "claim g1: evidence_lines must be a list"),
        ({**claim, "claim_id": "g 1"}, "claim 1: claim_id must be an id"),
        ({**claim, "note": 1}, "claim g1: unknown key 'note'"),
    ]
    for changed, expected in cases:
        problems = _raw_problems(dict(good, claims=[changed]))
        assert len(problems) == 1 and problems[0].startswith(expected), (changed, problems)
    no_occurrence = {k: v for k, v in claim.items() if k != "occurrence"}
    assert _raw_problems(dict(good, claims=[no_occurrence])) == []
    twice = _raw_problems(dict(good, claims=[claim, claim]))
    assert twice == ["claim g1: claim_id is used twice"]
    missing = {k: v for k, v in claim.items() if k != "truth"}
    assert _raw_problems(dict(good, claims=[missing, "x"])) == [
        "claim g1: missing key 'truth'",
        "claim 2: not a JSON object",
    ]
    assert e0.raw_problems(dict(good, claims=[{**claim, "evidence_lines": [99]}])) == []


def test_check_raw_files_report_unreadable_files_and_duplicate_ids(
    git_repo: Path, commit: Commit
) -> None:
    _, packets, raw_dir, _ = prepared(git_repo, commit)
    (raw_dir / "broken.json").write_text("{", "utf-8")
    copy = raw_dir / "copy.json"
    shutil.copy(raw_dir / "rep-3.json", copy)
    problems = e0.check_raw_files(
        [raw_dir / "rep-3.json", copy, raw_dir / "broken.json", raw_dir / "nope.json"], packets
    )
    assert problems[0] == f"{copy}: report_id 'rep-3' is also used by {raw_dir / 'rep-3.json'}"
    assert problems[1].startswith(f"{raw_dir / 'broken.json'}: not valid JSON")
    assert problems[2] == f"{raw_dir / 'nope.json'}: file not found"
    with pytest.raises(e0.E0Error, match=re.escape("index.json: file not found")):
        e0.check_raw_files([copy], raw_dir.parent)
    (packets / "index.json").write_text(json.dumps({"schema": "other"}), "utf-8")
    with pytest.raises(e0.E0Error, match=re.escape("not a receipts.e0.writer_packets/1 index")):
        e0.check_raw_files([copy], packets)
    (packets / "index.json").write_text(
        json.dumps({"schema": "receipts.e0.writer_packets/1"}), "utf-8"
    )
    with pytest.raises(e0.E0Error, match="lists no packets"):
        e0.check_raw_files([copy], packets)


# ---------------------------------------------------------------- adjudication


def test_adjudication_packets_hide_the_writer_labels(git_repo: Path, commit: Commit) -> None:
    runs, packets, raw_dir, _ = prepared(git_repo, commit)
    out = git_repo / "work" / "adj-packets"
    index = e0.write_adjudication_packets(
        git_repo, runs, raw_dir, packets, out, command="synthetic adjudication packets"
    )
    assert [r["report_id"] for r in index["reports"]] == ["rep-0", "rep-11", "rep-3", "rep-9"]
    entry = next(r for r in index["reports"] if r["report_id"] == "rep-9")
    assert entry["claim_ids"] == ["g1", "g2", "g3"] and entry["run_id"] == "r2"
    text = (out / "rep-9.md").read_text("utf-8")
    assert e0.sha256_bytes(text.encode("utf-8")) == entry["sha256"]
    block = re.search(r"## Claims to label\n\n```json\n(.*?)\n```\n", text, flags=re.S)
    assert block is not None
    claims = json.loads(block.group(1))
    assert claims == [
        {"claim_id": "g1", "text": "Updated `src/app.py`", "occurrence": 1},
        {"claim_id": "g2", "text": "`src/util.py`", "occurrence": 1},
        {"claim_id": "g3", "text": "3 of 4 tests pass", "occurrence": 1},
    ]
    assert SEEDED_REPORTS["rep-9"][2] in text and "--packets work/adj-packets" in text
    assert "receipts.claims" not in text and "receipts.verify" not in text


def test_adjudication_packets_refuse_a_changed_fact_sheet(git_repo: Path, commit: Commit) -> None:
    runs, packets, raw_dir, _ = prepared(git_repo, commit)
    write_ledger(runs / "r1" / "ledger.jsonl", "r1", "t-alpha", "x", gap=True)
    with pytest.raises(e0.E0Error, match="differs from the one the writer saw"):
        e0.write_adjudication_packets(git_repo, runs, raw_dir, packets, git_repo / "a", command="c")
    (runs / "r1" / "ledger.jsonl").unlink()
    with pytest.raises(e0.E0Error, match="cannot load its ledger"):
        e0.write_adjudication_packets(git_repo, runs, raw_dir, packets, git_repo / "a", command="c")


def test_adjudication_problems_and_checks(git_repo: Path, commit: Commit) -> None:
    runs, packets, raw_dir, adj_dir = prepared(git_repo, commit)
    out = git_repo / "work" / "adj-packets"
    e0.write_adjudication_packets(git_repo, runs, raw_dir, packets, out, command="c")
    files = sorted(adj_dir.glob("*.json"))
    assert e0.check_adjudication_files(files, out) == []
    good = adjudication_output("rep-9", "a2", [("file_modified", "supported", [5])] * 3)
    ids = ["g1", "g2", "g3"]
    assert e0.adjudication_problems(good, ids, 20) == []
    assert e0.adjudication_problems("x", ids) == ["the file is not a JSON object"]
    assert e0.adjudication_problems({"report_id": "r", "adjudicator": "a"}, ids) == [
        "missing key 'labels'",
        "labels must be a list",
    ]
    labels = good["labels"]
    broken = dict(
        good,
        adjudicator="a b",
        labels=[labels[0], labels[0], {**labels[1], "claim_id": "g7"}, "x", {"claim_id": 5}],
    )
    assert e0.adjudication_problems(broken, ids, 20) == [
        "adjudicator must be an id (letters, digits, '.', '_', '-'; at most 128)",
        "label g7: the report has no claim 'g7'",
        "label 4: not a JSON object",
        "label 5: missing key 'evidence_lines'",
        "label 5: missing key 'truth'",
        "label 5: missing key 'type'",
        "label 5: claim_id must be an id such as g1",
        "claim g1 is labeled 2 times",
        "claims not labeled: g2, g3",
    ]
    bad_lines = dict(good, labels=[{**labels[0], "evidence_lines": [21]}, *labels[1:]])
    assert e0.adjudication_problems(bad_lines, ids, 20) == [
        "label g1: evidence line(s) 21 not in the fact sheet (L1 to L20)"
    ]
    assert e0.adjudication_problems(bad_lines, None) == []
    stray = git_repo / "stray.json"
    stray.write_text(json.dumps(dict(good, report_id="rep-77")), "utf-8")
    (git_repo / "broken.json").write_text("[", "utf-8")
    problems = e0.check_adjudication_files(
        [adj_dir / "rep-9.json", adj_dir / "rep-9.json", stray, git_repo / "broken.json"], out
    )
    assert problems == [
        f"{adj_dir / 'rep-9.json'}: report_id 'rep-9' is also used by {adj_dir / 'rep-9.json'}",
        f"{stray}: report_id 'rep-77' has no adjudication packet",
        problems[2],
    ]
    assert problems[2].startswith(f"{git_repo / 'broken.json'}: not valid JSON")


# ---------------------------------------------------------------- blindness


def test_scan_transcript_keeps_only_hashes_fragments_and_ids(tmp_path: Path) -> None:
    agents = write_transcripts(tmp_path / "agents")
    # Its task message and its packet name src/ and the forbidden packages; neither is a
    # tool call into the repository, and its report naming src/app.py is its own output.
    clean = e0.scan_transcript(agents / "agent-w1.jsonl")
    assert clean == {
        "file": "agent-w1.jsonl",
        "sha256": e0.sha256_file(agents / "agent-w1.jsonl"),
        "violations": [],
        "reviews": [],
        "names": ["w1"],
        "unparsed_lines": 0,
    }
    assert not e0.voids(clean)
    bad = e0.scan_transcript(agents / "agent-w3.jsonl")
    assert bad["violations"] == [
        {
            "tool": "Bash",
            "where": "input",
            "rule": "named",
            "fragment": "cat src/receipts/claims/patterns.py | head -50",
        }
    ]
    assert bad["reviews"] == [] and bad["names"] == ["w3"] and e0.voids(bad)
    long_line = tool_use_line("Grep", {"pattern": "x" * 100 + "receipts.verify" + "y" * 100})
    (tmp_path / "long.jsonl").write_text(long_line + "\n\n", "utf-8")
    fragment = e0.scan_transcript(tmp_path / "long.jsonl")["violations"][0]["fragment"]
    assert fragment == "x" * 40 + "receipts.verify" + "y" * 40


#: Tool calls that reach the extractor or the verifier (their code, tests, entry points,
#: commands, or banked outputs) without naming any of the protocol's six paths. Each one
#: passed the earlier scan without a violation (review finding).
INDIRECT_ROUTES: list[tuple[str, dict[str, Any]]] = [
    ("Bash", {"command": "cat tests/claims/test_pattern_rules.py"}),
    ("Read", {"file_path": "/home/user/receipts/tests/claims/test_corpus.py"}),
    ("Read", {"file_path": "/home/user/receipts/tests/verify/test_verifier.py"}),
    (
        "Bash",
        {"command": "cat artifacts/studies/pipeline-check/runs/pipeline-check-1/verification.json"},
    ),
    ("Read", {"file_path": "/home/user/receipts/artifacts/studies/smoke/runs/r1/run.json"}),
    ("Read", {"file_path": "/home/user/receipts/artifacts/e0/seeded_eval_dev.json"}),
    ("Bash", {"command": "grep -rn 'def extract_claims' src/"}),
    ("Bash", {"command": "cd src/receipts && cat claims/extract.py"}),
    ("Glob", {"pattern": "**/claims/*.py", "path": "/home/user/receipts/src"}),
    ("Bash", {"command": "python -c 'from receipts import claims; print(claims.__file__)'"}),
    ("Bash", {"command": "uv run receipts check --report draft.md --ledger ledger.jsonl"}),
    ("Bash", {"command": "uv run --no-sync python tools/e0.py evaluate --split dev"}),
    ("Write", {"file_path": "/tmp/peek.py", "content": "from receipts.hook import main\n"}),
    (
        "MultiEdit",
        {"file_path": "/tmp/peek.py", "edits": [{"old_string": "x", "new_string": "verify_run"}]},
    ),
]


@pytest.mark.parametrize(("tool", "tool_input"), INDIRECT_ROUTES)
def test_indirect_routes_to_the_instrument_are_violations(
    tmp_path: Path, tool: str, tool_input: dict[str, Any]
) -> None:
    path = write_agent(tmp_path, "w1", "writer", tool_use_line(tool, tool_input))
    scan = e0.scan_transcript(path)
    assert [(v["tool"], v["where"]) for v in scan["violations"]] == [(tool, "input")]
    assert scan["reviews"] == [] and e0.voids(scan)


def test_tool_results_that_show_the_instrument_are_violations(tmp_path: Path) -> None:
    # A search with no path covers the whole checkout; its result lists the extractor.
    search = tool_use_line("Grep", {"pattern": "tests pass"}, "toolu_grep")
    listing = "Found 2 files\nsrc/receipts/claims/patterns.py\ndocs/CLAIM_TYPES.md"
    # A glob avoids naming verification.json; what it prints is the verifier's output.
    glob = tool_use_line("Bash", {"command": "cat artifacts/studies/*/v*.json"}, "toolu_cat")
    output = '{"claims": [{"claim_id": "c0", "extractor": "pattern"}]}'
    path = write_agent(
        tmp_path,
        "w1",
        "writer",
        search,
        tool_result_line("toolu_grep", listing),
        glob,
        tool_result_line("toolu_cat", output),
    )
    scan = e0.scan_transcript(path)
    assert scan["violations"] == [
        {"tool": "Grep", "where": "result", "rule": "named", "fragment": listing},
        {"tool": "Bash", "where": "result", "rule": "output", "fragment": output},
    ]


def test_copies_of_a_tool_input_are_scanned_too(tmp_path: Path) -> None:
    use = {"type": "tool_use", "id": "toolu_wire", "name": "Bash", "input": {"command": "ls"}}
    record = {
        "type": "assistant",
        "message": {"role": "assistant", "content": [use]},
        "wireToolInputs": {"toolu_wire": {"command": "cat tests/verify/test_facts.py"}},
    }
    path = write_agent(tmp_path, "w1", "writer", json.dumps(record))
    assert e0.scan_transcript(path)["violations"] == [
        {
            "tool": "Bash",
            "where": "input",
            "rule": "directory",
            "fragment": "cat tests/verify/test_facts.py",
        }
    ]


def test_only_tool_inputs_declare_ids(tmp_path: Path) -> None:
    # An adjudicator that opens a writer's output sees "writer": "w2" in a tool result.
    # That does not make its transcript w2's, which would hide a missing w2 transcript.
    peek = tool_use_line("Read", {"file_path": "/elsewhere/w2.json"}, "toolu_peek")
    seen = tool_result_line("toolu_peek", json.dumps({"writer": "w2", "report": "x"}))
    path = write_agent(tmp_path, "a1", "adjudicator", peek, seen)
    assert e0.scan_transcript(path)["names"] == ["a1"]


#: Tool calls into parts of the repository a writer or adjudicator never needs, naming no
#: instrument path, each with the review rule it matches. They void unless a person clears
#: them (the earlier scan only warned on "src/receipts" and never voided).
REVIEW_ROUTES: list[tuple[str, dict[str, Any], str]] = [
    ("Bash", {"command": "grep -rn 'tests pass' src/receipts | head"}, "repository"),
    ("Bash", {"command": "cd src && ls"}, "repository"),
    ("Grep", {"pattern": "passed", "path": "/home/user/receipts/tests"}, "repository"),
    ("Read", {"file_path": "/home/user/receipts/bench/tasks/t-alpha/task.toml"}, "repository"),
    ("Read", {"file_path": "/home/user/receipts/DECISIONS.md"}, "project notes"),
    ("Bash", {"command": "git log -p -3"}, "git"),
    ("Bash", {"command": "uv run --no-sync python -c 'import receipts'"}, "receipts"),
    ("Bash", {"command": "uv run --no-sync pytest -q"}, "tests or builds"),
    (
        "MultiEdit",
        {"edits": [{"old_string": "a"}], "file_path": "/home/user/receipts/docs/HOOK.md"},
        "repository",
    ),
]


@pytest.mark.parametrize(("tool", "tool_input", "rule"), REVIEW_ROUTES)
def test_other_repository_access_voids_until_a_person_clears_it(
    tmp_path: Path, tool: str, tool_input: dict[str, Any], rule: str
) -> None:
    path = write_agent(tmp_path, "w1", "writer", tool_use_line(tool, tool_input))
    scan = e0.scan_transcript(path)
    assert scan["violations"] == []
    assert [(r["tool"], r["rule"], r["cleared"]) for r in scan["reviews"]] == [(tool, rule, None)]
    assert e0.voids(scan)


def test_a_person_can_clear_a_review_entry_but_never_a_violation(
    git_repo: Path, commit: Commit
) -> None:
    commit(git_repo, "empty")
    agents = git_repo / "agents"
    task_file = {"file_path": "/home/user/receipts/bench/tasks/t-alpha/task.toml"}
    write_agent(agents, "w1", "writer", tool_use_line("Read", task_file))
    write_agent(agents, "w2", "writer")
    peek = tool_use_line("Bash", {"command": "cat src/receipts/claims/patterns.py"})
    write_agent(agents, "w3", "writer", peek)
    data = e0.blindness_artifact(git_repo, [agents], command="c")
    assert data["voided"] == ["w1", "w3"] and data["clearances"] is None
    w1, _, w3 = data["transcripts"]
    entry = {
        "file": "agent-w1.jsonl",
        "sha256": w1["sha256"],
        "fragment": w1["reviews"][0]["fragment"],
        "by": "Raj",
        "reason": "a benchmark task file, not the instrument",
    }
    clear = git_repo / "clear.json"
    e0.write_json(clear, {"clearances": [entry]})
    cleared = e0.blindness_artifact(git_repo, [agents], command="c", clearances=clear)
    assert cleared["voided"] == ["w3"]
    assert e0.blindness_ids(cleared) == ({"w1", "w2", "w3"}, {"w3"})
    assert cleared["transcripts"][0]["reviews"][0]["cleared"] == {
        "by": "Raj",
        "reason": "a benchmark task file, not the instrument",
    }
    assert cleared["clearances"] == {
        "path": "clear.json",
        "sha256": e0.sha256_file(clear),
        "count": 1,
    }
    violation = {
        **entry,
        "file": "agent-w3.jsonl",
        "sha256": w3["sha256"],
        "fragment": w3["violations"][0]["fragment"],
    }
    for bad, expected in (
        (violation, "clearance 1 matches no review entry"),
        ({**entry, "sha256": "0" * 64}, "clearance 1 matches no review entry"),
        ({**entry, "by": " "}, "clearance 1 needs a non-empty file, sha256, fragment, by"),
        ({k: v for k, v in entry.items() if k != "reason"}, "clearance 1 needs a non-empty"),
    ):
        e0.write_json(clear, {"clearances": [bad]})
        with pytest.raises(e0.E0Error, match=re.escape(expected)):
            e0.blindness_artifact(git_repo, [agents], command="c", clearances=clear)
    e0.write_json(clear, {"other": []})
    with pytest.raises(e0.E0Error, match="lists no clearances"):
        e0.blindness_artifact(git_repo, [agents], command="c", clearances=clear)


def test_a_line_separator_inside_a_record_does_not_hide_a_violation(tmp_path: Path) -> None:
    # JSON writers leave U+2028, U+2029, and U+0085 unescaped inside strings; a scan that
    # splits lines on them cuts this record in two and never sees its tool call.
    use = {
        "type": "tool_use",
        "id": "toolu_sep",
        "name": "Read",
        "input": {"file_path": "/r/src/receipts/claims/extract.py"},
    }
    text = {"type": "text", "text": "Reading it\u2028now\u2029and\u0085then"}
    record = {"type": "assistant", "message": {"role": "assistant", "content": [text, use]}}
    lines = agent_lines("w1", "writer")
    lines.insert(2, json.dumps(record, ensure_ascii=False))
    path = tmp_path / "agent-w1.jsonl"
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    scan = e0.scan_transcript(path)
    assert scan["unparsed_lines"] == 0
    assert scan["violations"] == [
        {
            "tool": "Read",
            "where": "input",
            "rule": "named",
            "fragment": "/r/src/receipts/claims/extract.py",
        }
    ]


def test_lines_that_are_not_json_objects_make_a_transcript_unscannable(
    git_repo: Path, commit: Commit
) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    agents = write_transcripts(git_repo / "agents")
    cut = tool_use_line("Read", {"file_path": "src/receipts/verify/checkers.py"})[:60]
    with (agents / "agent-w1.jsonl").open("ab") as handle:
        handle.write(cut.encode("utf-8") + b"\n\xff\xfe\n[1]\n")
    scan = e0.scan_transcript(agents / "agent-w1.jsonl")
    assert scan["unparsed_lines"] == 3 and scan["violations"] == [] and e0.voids(scan)
    data = e0.blindness_artifact(git_repo, [agents], command="c")
    assert data["unscannable"] == ["agent-w1.jsonl"] and data["voided"] == ["w1", "w3"]
    e0.write_json(git_repo / e0.BLINDNESS, data)
    refusal = re.escape("lines that are not JSON objects: agent-w1.jsonl")
    with pytest.raises(e0.E0Error, match=refusal):
        e0.merge_artifact(git_repo, raw_dir, adj_dir, git_repo / e0.BLINDNESS, command="c")


def test_blindness_artifact_voids_declared_ids(git_repo: Path, commit: Commit) -> None:
    commit(git_repo, "empty")
    agents = write_transcripts(git_repo / "agents")
    (git_repo / "agents" / "nested").mkdir()
    shutil.copy(agents / "agent-a1.jsonl", agents / "nested" / "agent-a9.jsonl")
    data = e0.blindness_artifact(git_repo, [agents], command="synthetic blindness")
    assert [t["file"] for t in data["transcripts"]] == [
        "agent-a1.jsonl",
        "agent-a2.jsonl",
        "agent-w1.jsonl",
        "agent-w2.jsonl",
        "agent-w3.jsonl",
        "agent-a9.jsonl",
    ]
    assert data["voided"] == ["w3"] and data["unattributed"] == [] and data["unscannable"] == []
    assert data["declared"] == ["a1", "a2", "w1", "w2", "w3"]
    assert data["schema"] == "receipts.e0.blindness/2" and data["clearances"] is None
    assert data["forbidden"] == list(e0.FORBIDDEN_REFERENCES)
    assert data["rules"] == {
        "violation": dict(e0.INSTRUMENT_RULES),
        "review": dict(e0.REVIEW_RULES),
    }
    only_file = e0.blindness_artifact(git_repo, [agents / "agent-w3.jsonl"], command="c")
    assert len(only_file["transcripts"]) == 1
    anonymous = git_repo / "anon.jsonl"
    anonymous.write_text(tool_use_line("Read", {"file_path": "src/receipts/verify/x.py"}), "utf-8")
    nameless = git_repo / "nameless.jsonl"
    nameless.write_text(tool_use_line("Bash", {"command": "ls tests/"}), "utf-8")
    result = e0.blindness_artifact(git_repo, [anonymous, nameless], command="c")
    assert result["unattributed"] == ["anon.jsonl", "nameless.jsonl"]
    with pytest.raises(e0.E0Error, match="does not exist"):
        e0.blindness_artifact(git_repo, [git_repo / "missing"], command="c")
    (git_repo / "empty").mkdir()
    with pytest.raises(e0.E0Error, match="no transcript files"):
        e0.blindness_artifact(git_repo, [git_repo / "empty"], command="c")


def test_blindness_ids_come_from_the_transcript_records(git_repo: Path, commit: Commit) -> None:
    commit(git_repo, "empty")
    scanned = e0.blindness_artifact(git_repo, [write_transcripts(git_repo / "agents")], command="c")
    assert e0.blindness_ids(scanned) == (set(SEEDED_PEOPLE), {"w3"})
    built = blindness_of(
        scan_record("agent-l1.jsonl", "l1"), scan_record("agent-l2.jsonl", "l2", voids=True)
    )
    assert e0.blindness_ids(built) == ({"l1", "l2"}, {"l2"})


def review_entry(cleared: object) -> dict[str, Any]:
    """A synthetic review entry of a transcript record, as scan_transcript writes one."""
    return {"tool": "Bash", "rule": "git", "fragment": "git log -3", "cleared": cleared}


@pytest.mark.parametrize(
    "problem",
    [
        "no-records",
        "no-transcripts",
        "schema",
        "declared",
        "voided",
        "no-list",
        "not-object",
        "keys",
        "file",
        "sha256",
        "names",
        "violations",
        "reviews",
        "review",
        "unparsed",
        "many",
        "hand-cleared",
        "clearances",
        "unused-clearances",
        "unscannable",
        "unattributed",
    ],
)
def test_blindness_ids_refuse_a_file_the_scan_did_not_write(problem: str) -> None:
    # A clean scan of l1 and l2, changed as the scan never changes it.
    blindness = blindness_of(
        scan_record("agent-l1.jsonl", "l1"), scan_record("agent-l2.jsonl", "l2")
    )
    first, second = blindness["transcripts"]
    edited = "; it was edited or is damaged: scan the transcripts again with tools/e0.py blindness"
    shapes = "the blindness file holds records that are not transcript scans ("
    if problem == "no-records":
        # The review finding: a declared list that no scanned transcript stands behind.
        blindness["transcripts"] = []
        expected = "the blindness file lists no scanned transcript"
    elif problem == "no-transcripts":
        del blindness["transcripts"]
        expected = "the blindness file lists no scanned transcript"
    elif problem == "schema":
        blindness["schema"] = "receipts.e0.blindness/1"
        expected = "the blindness file is not a receipts.e0.blindness/2 artifact"
    elif problem == "declared":
        blindness["declared"].append("l3")
        expected = "(its declared list has l3, which its records do not)" + edited
    elif problem == "voided":
        second["violations"].append(dict(VIOLATION))
        expected = "(its records have l2, which its voided list does not)" + edited
    elif problem == "no-list":
        del blindness["unattributed"]
        expected = "(it has no unattributed list of names)" + edited
    elif problem == "not-object":
        blindness["transcripts"][0] = "agent-l1.jsonl"
        expected = shapes + "transcript 1: not a JSON object)"
    elif problem == "keys":
        del first["violations"]
        first["seen"] = True
        expected = (
            shapes + "transcript 1: unknown key 'seen'; transcript 1: missing key 'violations')"
        )
    elif problem == "file":
        first["file"] = " "
        expected = shapes + "transcript 1: file must be a non-empty string)"
    elif problem == "sha256":
        second["sha256"] = second["sha256"].upper()
        expected = shapes + "transcript 2: sha256 must be 64 lowercase hex digits)"
    elif problem == "names":
        first["names"] = "l1"
        expected = shapes + "transcript 1: names must be a list of ids)"
    elif problem == "violations":
        first["violations"] = {}
        expected = shapes + "transcript 1: violations must be a list)"
    elif problem == "reviews":
        first["reviews"] = None
        expected = shapes + "transcript 1: reviews must be a list)"
    elif problem == "review":
        # Marked cleared with a bare true, an entry with keys missing, and one whose
        # fragment is not text.
        first["reviews"] = [
            review_entry(True),
            {"tool": "Bash", "cleared": None},
            {**review_entry(None), "fragment": 5},
        ]
        needs = "needs a tool, a rule, a fragment, and cleared (null, or by and reason)"
        expected = shapes + "; ".join(f"transcript 1: review {n} {needs}" for n in (1, 2, 3)) + ")"
    elif problem == "unparsed":
        first["unparsed_lines"] = True
        expected = shapes + "transcript 1: unparsed_lines must be a whole number)"
    elif problem == "many":
        blindness["transcripts"] = [None] * 12
        listed = "; ".join(f"transcript {n}: not a JSON object" for n in range(1, 11))
        expected = shapes + listed + "; ...)"
    elif problem == "hand-cleared":
        # Cleared the way apply_clearances marks an entry, with no clearances file behind it.
        first["reviews"] = [review_entry({"by": "Raj", "reason": "commit subjects only"})]
        expected = "(its review entries marked cleared do not match its clearances record)"
    elif problem == "clearances":
        blindness["clearances"] = {"path": "clear.json"}
        expected = "(its clearances record is not a path, a SHA-256, and a count)"
    elif problem == "unused-clearances":
        blindness["clearances"] = {"path": "clear.json", "sha256": "0" * 64, "count": 1}
        expected = "(its review entries marked cleared do not match its clearances record)"
    elif problem == "unscannable":
        blindness = blindness_of(scan_record("agent-l1.jsonl", "l1", unparsed=2))
        expected = "lines that are not JSON objects: agent-l1.jsonl"
    else:
        anonymous = scan_record("anon.jsonl", voids=True)
        blindness = blindness_of(anonymous, scan_record("agent-l1.jsonl", "l1"))
        expected = "declare no writer, adjudicator, or labeler id: anon.jsonl"
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.blindness_ids(blindness)


# ---------------------------------------------------------------- merge


def merged(root: Path, commit: Commit) -> tuple[Path, dict[str, Any]]:
    """The prepared world merged with the synthetic blindness file; (merged path, data)."""
    _, _, raw_dir, adj_dir = prepared(root, commit)
    blindness = root / e0.BLINDNESS
    agents = write_transcripts(root / "agents")
    e0.write_json(blindness, e0.blindness_artifact(root, [agents], command="c"))
    data = e0.merge_artifact(root, raw_dir, adj_dir, blindness, command="synthetic merge")
    path = root / e0.MERGED
    e0.write_json(path, data)
    return path, data


def test_merge_keeps_agreed_claims_and_ignores_disputed_ones(
    git_repo: Path, commit: Commit
) -> None:
    _, data = merged(git_repo, commit)
    assert [r["report_id"] for r in data["reports"]] == ["rep-0", "rep-3", "rep-9"]
    assert data["excluded_reports"] == [
        {
            "report_id": "rep-11",
            "writer": "w3",
            "adjudicator": "a2",
            "reason": "writer voided by the blindness check",
            "claims": 1,
        }
    ]
    assert data["drops"] == {"by_type": {"file_modified": {"truth": 1}}, "total": 1}
    assert data["kept_by_type"] == {
        "file_modified": 2,
        "ran_command": 2,
        "task_complete": 1,
        "test_count": 1,
        "tests_pass": 1,
    }
    rep9 = data["reports"][2]
    assert [g["claim_id"] for g in rep9["gold"]] == ["g1", "g3"]
    assert rep9["gold"][1] == {
        "claim_id": "g3",
        "text": "3 of 4 tests pass",
        "occurrence": 1,
        "span": [40, 57],
        "claim_type": "test_count",
        "verdict": "supported",
        "evidence_lines": [9],
        "adjudicator_evidence_lines": [9],
    }
    assert rep9["ignored"] == [
        {
            "claim_id": "g2",
            "text": "`src/util.py`",
            "occurrence": 1,
            "span": [25, 38],
            "claim_types": ["file_modified"],
            "reason": "truth",
            "writer_type": "file_modified",
            "writer_truth": "contradicted",
            "adjudicator_type": "file_modified",
            "adjudicator_truth": "unverifiable",
        }
    ]
    assert data["synthetic"] is True and data["blindness"] == {
        "path": e0.BLINDNESS,
        "sha256": e0.sha256_file(git_repo / e0.BLINDNESS),
        "rescanned": False,
    }


def test_merge_records_type_disputes_with_both_types(git_repo: Path, commit: Commit) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    adj = json.loads((adj_dir / "rep-3.json").read_text("utf-8"))
    adj["labels"][0]["type"] = "file_created"
    adj["labels"][1].update(type="test_count", truth="contradicted")
    (adj_dir / "rep-3.json").write_text(json.dumps(adj), "utf-8")
    data = e0.merge_reports(raw_dir, adj_dir)
    rep3 = next(r for r in data["reports"] if r["report_id"] == "rep-3")
    assert [(c["reason"], c["claim_types"]) for c in rep3["ignored"]] == [
        ("type", ["file_modified", "file_created"]),
        ("type_and_truth", ["ran_command", "test_count"]),
    ]
    assert len(data["reports"]) == 4 and data["excluded_reports"] == []
    assert data["drops"]["total"] == 3


def test_merge_excludes_the_reports_of_a_voided_adjudicator(git_repo: Path, commit: Commit) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    data = e0.merge_reports(raw_dir, adj_dir, seeded_blindness("a2"))
    assert [r["report_id"] for r in data["reports"]] == ["rep-0", "rep-3"]
    assert [(r["report_id"], r["reason"]) for r in data["excluded_reports"]] == [
        ("rep-11", "adjudicator voided by the blindness check"),
        ("rep-9", "adjudicator voided by the blindness check"),
    ]


def test_merge_takes_the_ids_from_the_records_and_refuses_edited_lists(
    git_repo: Path, commit: Commit
) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    blindness = seeded_blindness("w2")
    data = e0.merge_reports(raw_dir, adj_dir, blindness)
    assert [r["report_id"] for r in data["excluded_reports"]] == ["rep-9"]
    # Its voided list edited to clear w2, whose record still holds the violation.
    blindness["voided"] = []
    with pytest.raises(e0.E0Error, match="its records have w2, which its voided list does not"):
        e0.merge_reports(raw_dir, adj_dir, blindness)
    # A declared list with no scanned transcript behind it (the review finding).
    forged = {**seeded_blindness(), "transcripts": []}
    with pytest.raises(e0.E0Error, match="the blindness file lists no scanned transcript"):
        e0.merge_reports(raw_dir, adj_dir, forged)


def test_merge_can_check_the_blindness_file_against_a_new_scan(
    git_repo: Path, commit: Commit
) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    agents = write_transcripts(git_repo / "agents")
    blindness = git_repo / e0.BLINDNESS
    e0.write_json(blindness, e0.blindness_artifact(git_repo, [agents], command="c"))
    data = e0.merge_artifact(git_repo, raw_dir, adj_dir, blindness, command="c", agents=[agents])
    assert data["blindness"]["rescanned"] is True
    assert [r["report_id"] for r in data["excluded_reports"]] == ["rep-11"]
    # w3 read the extractor. Its record and the voided list edited together hold together,
    # so only a new scan of the transcripts tells.
    edited = json.loads(blindness.read_text("utf-8"))
    edited["transcripts"][4]["violations"] = []
    edited["voided"] = []
    e0.write_json(blindness, edited)
    trusted = e0.merge_artifact(git_repo, raw_dir, adj_dir, blindness, command="c")
    assert trusted["excluded_reports"] == [] and trusted["blindness"]["rescanned"] is False
    changed = re.escape("a new scan gives other entries for agent-w3.jsonl")
    with pytest.raises(e0.E0Error, match=changed):
        e0.merge_artifact(git_repo, raw_dir, adj_dir, blindness, command="c", agents=[agents])
    with pytest.raises(e0.E0Error, match="--agents needs --blindness"):
        e0.merge_artifact(git_repo, raw_dir, adj_dir, None, command="c", agents=[agents])


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "self",
        "unattributed",
        "unattributed-scan",
        "unscannable",
        "unscanned",
        "stray",
        "invalid",
    ],
)
def test_merge_refuses_inconsistent_inputs(git_repo: Path, commit: Commit, problem: str) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    blindness: dict[str, Any] | None = None
    people = [scan_record(f"agent-{name}.jsonl", name) for name in SEEDED_PEOPLE]
    if problem == "missing":
        (adj_dir / "rep-0.json").unlink()
        expected = "reports with no adjudication: rep-0"
    elif problem == "self":
        adj = json.loads((adj_dir / "rep-0.json").read_text("utf-8"))
        (adj_dir / "rep-0.json").write_text(json.dumps(dict(adj, adjudicator="w1")), "utf-8")
        expected = "adjudicated by its own writer w1"
    elif problem == "unattributed":
        blindness = blindness_of(*people, scan_record("agent-x.jsonl", voids=True))
        expected = "declare no writer, adjudicator, or labeler id: agent-x.jsonl"
    elif problem == "unattributed-scan":
        scan = {**scan_record("agent-y.jsonl"), "reviews": [review_entry(None)]}
        blindness = blindness_of(*people, scan)
        expected = "declare no writer, adjudicator, or labeler id: agent-y.jsonl"
    elif problem == "unscannable":
        blindness = blindness_of(*people, scan_record("agent-z.jsonl", "w9", unparsed=1))
        expected = "lines that are not JSON objects: agent-z.jsonl"
    elif problem == "unscanned":
        blindness = seeded_blindness(people=["a1", "w1", "w2"])
        expected = "no scanned transcript declares these writers or adjudicators: a2, w3"
    elif problem == "stray":
        adj = json.loads((adj_dir / "rep-0.json").read_text("utf-8"))
        (adj_dir / "extra.json").write_text(json.dumps(dict(adj, report_id="rep-5")), "utf-8")
        expected = "no writer output has report_id 'rep-5'"
    else:
        raw = json.loads((raw_dir / "rep-0.json").read_text("utf-8"))
        (raw_dir / "dup.json").write_text(json.dumps(raw), "utf-8")
        (raw_dir / "bad.json").write_text("{", "utf-8")
        expected = "bad.json: not valid JSON"
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.merge_reports(raw_dir, adj_dir, blindness)


def test_merge_artifact_and_loaders_refuse_bad_paths(git_repo: Path, commit: Commit) -> None:
    _, _, raw_dir, adj_dir = prepared(git_repo, commit)
    raw = json.loads((raw_dir / "rep-0.json").read_text("utf-8"))
    (raw_dir / "dup.json").write_text(json.dumps(raw), "utf-8")
    with pytest.raises(e0.E0Error, match="appears twice"):
        e0.load_raw_dir(raw_dir)
    with pytest.raises(e0.E0Error, match="is not a directory"):
        e0.load_raw_dir(git_repo / "missing")
    (git_repo / "none").mkdir()
    with pytest.raises(e0.E0Error, match="no writer outputs"):
        e0.load_raw_dir(git_repo / "none")
    (git_repo / "list.json").write_text("[]", "utf-8")
    with pytest.raises(e0.E0Error, match="is not a blindness artifact"):
        e0.merge_artifact(git_repo, raw_dir, adj_dir, git_repo / "list.json", command="c")
    (raw_dir / "dup.json").unlink()
    data = e0.merge_artifact(git_repo, raw_dir, adj_dir, None, command="c")
    assert data["blindness"] is None and len(data["reports"]) == 4


# ---------------------------------------------------------------- split


def packets_of(root: Path) -> Path:
    """The writer packets directory of the synthetic world (built by :func:`prepared`)."""
    return root / "work" / "packets"


def test_split_writes_halves_and_a_manifest(git_repo: Path, commit: Commit) -> None:
    merged_path, data = merged(git_repo, commit)
    packets = packets_of(git_repo)
    manifest = e0.write_split(git_repo, merged_path, packets, command="synthetic split")
    heldout = git_repo / e0.SEEDED / "heldout"
    assert sorted(manifest["reports"]) == ["rep-3", "rep-9"]
    for report_id, digest in manifest["reports"].items():
        assert e0.sha256_file(heldout / f"{report_id}.json") == digest
    assert [p.name for p in (git_repo / e0.SEEDED / "dev").glob("*.json")] == ["rep-0.json"]
    doc = json.loads((heldout / "rep-9.json").read_text("utf-8"))
    ledger_rel = "artifacts/studies/smoke/runs/r2/ledger.jsonl"
    assert doc["ledger"] == ledger_rel and doc["synthetic"] is True and doc["split"] == "heldout"
    assert doc["ledger_sha256"] == e0.sha256_file(git_repo / ledger_rel)
    packet = next(p for p in e0.writer_index(packets) if p["run_id"] == "r2")
    assert doc["ledger_sha256"] == packet["ledger_sha256"]
    assert doc["fact_sheet_sha256"] == packet["fact_sheet_sha256"]
    assert doc["writer_packet_sha256"] == packet["sha256"]
    assert manifest["writer_packets"] == {
        "path": "work/packets/index.json",
        "sha256": e0.sha256_file(packets / "index.json"),
    }
    assert (
        doc["gold"] == data["reports"][2]["gold"]
        and doc["ignored"] == data["reports"][2]["ignored"]
    )
    assert manifest["gold_by_type"] == {
        "file_modified": 2,
        "ran_command": 1,
        "test_count": 1,
        "tests_pass": 1,
    }
    assert manifest["ignored_by_type"] == {"file_modified": 1} and manifest["dev_reports"] == 1
    assert manifest["drops"] == data["drops"] and manifest["seed"] == e0.SPLIT_SEED
    assert manifest["excluded_reports"][0]["report_id"] == "rep-11"
    assert manifest["merged"]["sha256"] == e0.sha256_file(merged_path)
    assert json.loads((git_repo / e0.MANIFEST).read_text("utf-8")) == manifest
    (git_repo / e0.SEEDED / "dev" / "stale.json").write_text("{}", "utf-8")
    e0.write_split(git_repo, merged_path, packets, command="again")
    assert not (git_repo / e0.SEEDED / "dev" / "stale.json").exists()


def test_split_refuses_once_frozen(git_repo: Path, commit: Commit) -> None:
    merged_path, _ = merged(git_repo, commit)
    e0.write_split(git_repo, merged_path, packets_of(git_repo), command="split")
    commit(git_repo, "freeze")
    with pytest.raises(e0.E0Error, match="the split is frozen"):
        e0.write_split(git_repo, merged_path, packets_of(git_repo), command="again")


def test_split_refuses_once_a_heldout_report_is_committed(git_repo: Path, commit: Commit) -> None:
    # A held-out file committed without its manifest freezes the split too.
    merged_path, _ = merged(git_repo, commit)
    stray = git_repo / e0.SEEDED / "heldout" / "rep-3.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("{}\n", "utf-8")
    commit(git_repo, "a held-out report without its manifest")
    with pytest.raises(e0.E0Error, match="the split is frozen"):
        e0.write_split(git_repo, merged_path, packets_of(git_repo), command="split")


@pytest.mark.parametrize(
    "problem",
    [
        "ledger",
        "rebanked",
        "broken-ledger",
        "no-packet",
        "fact-sheet",
        "schema",
        "empty",
        "dev-only",
    ],
)
def test_split_refuses_bad_merges(git_repo: Path, commit: Commit, problem: str) -> None:
    merged_path, data = merged(git_repo, commit)
    packets = packets_of(git_repo)
    index = json.loads((packets / "index.json").read_text("utf-8"))
    smoke_r2 = git_repo / "artifacts/studies/smoke/runs/r2/ledger.jsonl"
    if problem == "ledger":
        smoke_r2.unlink()
        expected = "its ledger artifacts/studies/smoke/runs/r2/ledger.jsonl is missing"
    elif problem == "broken-ledger":
        # An index edited to match a ledger whose hash chain is broken.
        lines = smoke_r2.read_text("utf-8").splitlines()
        smoke_r2.write_text("\n".join(lines[1:]) + "\n", "utf-8")
        for entry in index["packets"]:
            if entry["run_id"] == "r2":
                entry["ledger_sha256"] = e0.sha256_file(smoke_r2)
        e0.write_json(packets / "index.json", index)
        expected = "report rep-9: cannot load artifacts/studies/smoke/runs/r2/ledger.jsonl"
    elif problem == "rebanked":
        # The smoke ledger was banked again after the writer's packet was built from it.
        write_ledger(smoke_r2, "r2", "t-alpha", "A report banked later.", gap=True)
        expected = (
            "report rep-9: artifacts/studies/smoke/runs/r2/ledger.jsonl is not the ledger "
            "its writer packet was built from"
        )
    elif problem == "no-packet":
        index["packets"] = [p for p in index["packets"] if p["run_id"] != "r2"]
        e0.write_json(packets / "index.json", index)
        expected = "report rep-9: run r2 has no writer packet in"
    elif problem == "fact-sheet":
        for entry in index["packets"]:
            entry["fact_sheet_sha256"] = "0" * 64
        e0.write_json(packets / "index.json", index)
        expected = "the fact sheet of artifacts/studies/smoke/runs/r3/ledger.jsonl differs"
    elif problem == "schema":
        data = {**data, "schema": "other"}
        expected = "is not a merged E0 artifact"
    elif problem == "empty":
        data = {**data, "reports": []}
        expected = "has no reports"
    else:
        data = {**data, "reports": [r for r in data["reports"] if r["report_id"] == "rep-0"]}
        expected = "no report fell in the held-out half"
    e0.write_json(merged_path, data)
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.write_split(git_repo, merged_path, packets, command="split")


# ---------------------------------------------------------------- evaluate


def frozen(root: Path, commit: Commit) -> Path:
    """Counts, merge, and split in the synthetic world, with the held-out half committed.

    The counts here are extractor counts in the G5 file, as tools/e0.py wrote them before
    D34; evaluate still accepts such counts, bound to the instrument that made them. The
    blind-label counts are tested in tests/evaluation/test_e0_labels.py.
    """
    merged_path, _ = merged(root, commit)
    counted = e0.extractor_counts_artifact(root, root / e0.SMOKE_RUNS, command="c")
    e0.write_json(root / e0.COUNTS, counted)
    e0.write_split(root, merged_path, packets_of(root), command="split")
    commit(root, "freeze the held-out half")
    return merged_path


def test_evaluate_heldout_scores_and_never_passes_untested_types(
    git_repo: Path, commit: Commit
) -> None:
    frozen(git_repo, commit)
    result = e0.evaluate(git_repo, "heldout", command="synthetic evaluate")
    assert result["split"] == "heldout" and result["heldout_manifest"] == e0.MANIFEST
    assert result["heldout_manifest_sha256"] == e0.sha256_file(git_repo / e0.MANIFEST)
    assert result["claim_type_counts_sha256"] == e0.sha256_file(git_repo / e0.COUNTS)
    assert result["reports"] == 2 and result["synthetic_reports"] is True
    assert result["top5"] == [
        "file_modified",
        "ran_command",
        "tests_pass",
        "bug_fixed",
        "task_complete",
    ]
    per_type = result["per_type"]
    assert per_type["file_modified"] == {
        "correct": 2,
        "predicted": 2,
        "gold": 2,
        "ignored": 1,
        "precision": 1.0,
        "precision_ci": list(e0.TypeScore("x", 2, 2, 2).precision_ci()),
        "recall": 1.0,
        "recall_ci": list(e0.TypeScore("x", 2, 2, 2).recall_ci()),
        "meets_thresholds": True,
    }
    for name in ("ran_command", "tests_pass", "test_count"):
        assert (per_type[name]["correct"], per_type[name]["predicted"]) == (1, 1)
    assert per_type["bug_fixed"]["precision"] is None and per_type["bug_fixed"]["recall_ci"] is None
    assert result["passes"] == {
        "file_modified": True,
        "ran_command": True,
        "tests_pass": True,
        "bug_fixed": False,
        "task_complete": False,
    }
    assert result["all_top5_pass"] is False
    ignored = [i for i in result["items"] if i["ignored"]]
    assert len(ignored) == 1 and ignored[0]["ignored_claim_id"] == "g2"
    assert (
        ignored[0]["pred_verdict"] == "contradicted" and ignored[0]["pred_subject"] == "src/util.py"
    )
    assert {i["report_id"] for i in result["items"]} == {"rep-3", "rep-9"}
    assert all(i["gold_verdict"] is None or i["gold_span"] for i in result["items"])
    assert result["thresholds"] == {"precision": 0.95, "recall": 0.9}
    assert result["instrument"]["commit"] == e0.head_commit(git_repo)
    assert result["instrument"]["paths"] == list(e0.SCORING_PATHS)
    assert result["attempt"] == 1 and result["attempts_log"] == e0.ATTEMPTS


def test_evaluate_dev_needs_no_manifest_and_records_a_dirty_instrument(
    git_repo: Path, commit: Commit
) -> None:
    merged_path, _ = merged(git_repo, commit)
    e0.write_split(git_repo, merged_path, packets_of(git_repo), command="split")
    (git_repo / "src/receipts/verify").mkdir(parents=True)
    (git_repo / "src/receipts/verify/wip.py").write_text("x = 1\n", "utf-8")
    result = e0.evaluate(git_repo, "dev", command="synthetic evaluate dev")
    assert result["split"] == "dev" and result["heldout_manifest"] is None
    assert result["instrument"]["dirty"] is True and result["instrument"]["allow_dirty"] is False
    assert result["claim_type_counts"] is None and result["top5"] == []
    assert result["attempt"] is None and not (git_repo / e0.ATTEMPTS).exists()
    assert result["per_type"]["task_complete"]["correct"] == 1
    assert result["per_type"]["ran_command"]["correct"] == 1
    with pytest.raises(e0.E0Error, match="uncommitted"):
        e0.evaluate(git_repo, "heldout", command="c")
    with pytest.raises(e0.E0Error, match="unknown split"):
        e0.evaluate(git_repo, "all", command="c")
    for path in (git_repo / e0.SEEDED / "dev").glob("*.json"):
        path.unlink()
    with pytest.raises(e0.E0Error, match="no dev reports"):
        e0.evaluate(git_repo, "dev", command="c")


def _tamper(root: Path, commit: Commit, problem: str) -> str:
    heldout = root / e0.SEEDED / "heldout"
    if problem == "uncommitted-manifest":
        manifest = json.loads((root / e0.MANIFEST).read_text("utf-8"))
        e0.write_json(root / e0.MANIFEST, {**manifest, "seed": 1})
        return "has uncommitted changes"
    if problem == "recommitted-manifest":
        manifest = json.loads((root / e0.MANIFEST).read_text("utf-8"))
        e0.write_json(root / e0.MANIFEST, {**manifest, "seed": 1})
        commit(root, "edit the manifest")
        return "changed after the commit that added it"
    if problem == "changed-report":
        doc = json.loads((heldout / "rep-3.json").read_text("utf-8"))
        e0.write_json(heldout / "rep-3.json", {**doc, "gold": []})
        return "held-out report rep-3 changed since the manifest"
    if problem == "extra-report":
        shutil.copy(heldout / "rep-3.json", heldout / "rep-99.json")
        return "does not hold exactly the reports its manifest lists"
    if problem == "ledger":
        write_ledger(
            root / "artifacts/studies/smoke/runs/r1/ledger.jsonl", "r1", "t", "x", gap=True
        )
        return "ledger artifacts/studies/smoke/runs/r1/ledger.jsonl is missing or changed"
    if problem == "counts":
        (root / e0.COUNTS).unlink()
        commit(root, "drop the counts")
        return "claim_type_counts.json is missing"
    if problem.startswith("counts-"):
        return _tamper_counts(root, commit, problem)
    if problem == "attempts":
        (root / e0.ATTEMPTS).write_text('{"attempt": 1}\n', "utf-8")
        return "heldout_attempts.jsonl has uncommitted changes"
    subprocess.run(["git", "-C", str(root), "rm", "-q", "--cached", e0.MANIFEST], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "untrack"], check=True)
    return "is not committed"


def _tamper_counts(root: Path, commit: Commit, problem: str) -> str:
    counts = json.loads((root / e0.COUNTS).read_text("utf-8"))
    if problem == "counts-list":
        counts = [counts]
        expected = "claim_type_counts.json is not a JSON object"
    elif problem == "counts-values":
        counts["counts"] = {"file_modified": "three"}
        expected = "claim_type_counts.json has no counts"
    if problem in ("counts-list", "counts-values"):
        e0.write_json(root / e0.COUNTS, counts)
        commit(root, "break the counts")
        return expected
    if problem == "counts-instrument":
        # The extractor changed (and was committed) after the claim types were counted.
        (root / "src/receipts/claims").mkdir(parents=True)
        (root / "src/receipts/claims/rules.py").write_text("RULES = 2\n", "utf-8")
        commit(root, "change the extractor after the counts")
        return (
            "claim_type_counts.json was counted with a different instrument "
            "(src/receipts/claims changed since); run the counts step again"
        )
    if problem == "counts-runs":
        counts["runs_dir"] = "elsewhere/runs"
        expected = "claim_type_counts.json counts the runs under 'elsewhere/runs', not"
    elif problem == "counts-dirty":
        counts["instrument"]["dirty"] = True
        expected = "claim_type_counts.json was counted while the instrument had uncommitted"
    elif problem == "counts-trees":
        del counts["instrument"]["trees"]
        expected = "claim_type_counts.json was counted with a different instrument"
    elif problem == "counts-method":
        counts["method"] = "hand-typed"
        expected = (
            "claim_type_counts.json was counted by method 'hand-typed', not 'blind-labels' "
            "or 'pattern-extractor'"
        )
    else:
        # Extractor counts relabeled as blind labels: they carry no labels to recount.
        counts["method"] = "blind-labels"
        expected = "claim_type_counts.json has no blind labels"
    e0.write_json(root / e0.COUNTS, counts)
    commit(root, "edit the counts")
    return expected


@pytest.mark.parametrize(
    "problem",
    [
        "uncommitted-manifest",
        "recommitted-manifest",
        "changed-report",
        "extra-report",
        "ledger",
        "counts",
        "counts-instrument",
        "counts-runs",
        "counts-dirty",
        "counts-trees",
        "counts-method",
        "counts-relabeled",
        "counts-list",
        "counts-values",
        "attempts",
        "untracked-manifest",
    ],
)
def test_evaluate_heldout_refuses_anything_unfrozen(
    git_repo: Path, commit: Commit, problem: str
) -> None:
    frozen(git_repo, commit)
    expected = _tamper(git_repo, commit, problem)
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.evaluate(git_repo, "heldout", command="c")


def test_evaluate_heldout_never_runs_on_an_uncommitted_instrument(
    git_repo: Path, commit: Commit
) -> None:
    frozen(git_repo, commit)
    # --allow-dirty is for the dev loop and tests; the held-out half never accepts it,
    # even when nothing is dirty.
    with pytest.raises(e0.E0Error, match="--allow-dirty is not allowed for the held-out split"):
        e0.evaluate(git_repo, "heldout", command="c", allow_dirty=True)
    # The scorer is part of what the gate freezes, so it must be committed too.
    (git_repo / "src/receipts/evaluation").mkdir(parents=True)
    (git_repo / "src/receipts/evaluation/seeded.py").write_text("x = 1\n", "utf-8")
    with pytest.raises(e0.E0Error, match=r"uncommitted changes \(src/receipts/evaluation/seeded"):
        e0.evaluate(git_repo, "heldout", command="c")
    assert not (git_repo / e0.ATTEMPTS).exists()


def test_every_heldout_evaluation_is_logged_and_numbered(git_repo: Path, commit: Commit) -> None:
    frozen(git_repo, commit)
    first = e0.evaluate(git_repo, "heldout", command="first")
    log = (git_repo / e0.ATTEMPTS).read_text("utf-8").splitlines()
    assert first["attempt"] == 1 and len(log) == 1
    entry = json.loads(log[0])
    assert entry["attempt"] == 1 and entry["command"] == "first"
    assert entry["commit"] == first["instrument"]["commit"]
    assert entry["trees"] == first["instrument"]["trees"]
    assert entry["passes"] == first["passes"] and entry["all_top5_pass"] is False
    assert entry["per_type"]["file_modified"] == {"correct": 2, "predicted": 2, "gold": 2}
    assert set(entry) == {
        "attempt",
        "command",
        "commit",
        "created",
        "trees",
        "passes",
        "all_top5_pass",
        "per_type",
    }
    # Scoring again before the first attempt is committed would let it vanish unseen.
    with pytest.raises(e0.E0Error, match="commit the earlier held-out attempt"):
        e0.evaluate(git_repo, "heldout", command="second")
    commit(git_repo, "the first held-out attempt")
    second = e0.evaluate(git_repo, "heldout", command="second")
    assert second["attempt"] == 2
    assert len((git_repo / e0.ATTEMPTS).read_text("utf-8").splitlines()) == 2


@pytest.mark.parametrize(
    ("correct", "predicted", "gold", "meets"),
    [
        (19, 20, 19, True),  # precision exactly 0.95 passes
        (9, 9, 10, True),  # recall exactly 0.90 passes
        (18, 20, 18, False),  # precision 0.90
        (8, 8, 10, False),  # recall 0.80
        (0, 0, 4, False),  # no predictions
        (0, 3, 0, False),  # no gold claims
    ],
)
def test_thresholds_are_inclusive_and_need_both_counts(
    correct: int, predicted: int, gold: int, meets: bool
) -> None:
    entry = e0.type_entry(e0.TypeScore("file_modified", correct, predicted, gold))
    assert entry["meets_thresholds"] is meets


def test_fewer_than_five_counted_types_never_pass_the_gate(git_repo: Path, commit: Commit) -> None:
    frozen(git_repo, commit)
    counts = json.loads((git_repo / e0.COUNTS).read_text("utf-8"))
    counts["counts"] = {"file_modified": 3, "ran_command": 2}
    e0.write_json(git_repo / e0.COUNTS, counts)
    commit(git_repo, "only two counted types")
    result = e0.evaluate(git_repo, "heldout", command="c")
    assert result["top5"] == ["file_modified", "ran_command"]
    assert result["passes"] == {"file_modified": True, "ran_command": True}
    assert result["all_top5_pass"] is False


def test_check_frozen_heldout_needs_a_manifest_with_reports(git_repo: Path, commit: Commit) -> None:
    (git_repo / "artifacts/e0").mkdir(parents=True)
    e0.write_json(git_repo / e0.MANIFEST, {"reports": {}})
    commit(git_repo, "placeholder manifest")
    with pytest.raises(e0.E0Error, match="lists no held-out reports"):
        e0.check_frozen_heldout(git_repo)


def test_check_frozen_heldout_needs_an_object(git_repo: Path, commit: Commit) -> None:
    (git_repo / "artifacts/e0").mkdir(parents=True)
    (git_repo / e0.MANIFEST).write_text("[]", "utf-8")
    commit(git_repo, "list manifest")
    with pytest.raises(e0.E0Error, match="is not a JSON object"):
        e0.check_frozen_heldout(git_repo)


def test_score_document_rejects_bad_spans(git_repo: Path, commit: Commit) -> None:
    merged_path, _ = merged(git_repo, commit)
    e0.write_split(git_repo, merged_path, packets_of(git_repo), command="split")
    doc = json.loads((git_repo / e0.SEEDED / "heldout" / "rep-3.json").read_text("utf-8"))
    doc["gold"][0]["span"] = [0]
    with pytest.raises(e0.E0Error, match="bad span"):
        e0.score_document(git_repo, doc)


def test_predict_uses_the_pattern_extractor_and_the_verifier(tmp_path: Path) -> None:
    write_ledger(tmp_path / "l.jsonl", "r1", "t", "x")
    report = "Updated `src/app.py` and `src/util.py`. All tests pass."
    predicted = e0.predict(report, Ledger.load(tmp_path / "l.jsonl"))
    assert [(p.claim_type, p.verdict, p.subject) for p in predicted] == [
        ("file_modified", "supported", "src/app.py"),
        ("file_modified", "contradicted", "src/util.py"),
        ("tests_pass", "contradicted", "all"),
    ]


# ---------------------------------------------------------------- completeness


def test_completeness_excludes_m5_failures_and_prior_work(git_repo: Path, commit: Commit) -> None:
    runs = make_world(git_repo)
    write_run(runs, "r7", "Done.", gap=True, prior_work=True)
    commit(git_repo, "world")
    data = e0.completeness_artifact(git_repo, [runs], git_repo / "bench/tasks", command="c")
    rows = {row["run_id"]: row for row in data["runs"]}
    assert sorted(rows) == ["r1", "r2", "r3", "r4", "r5", "r7"]
    assert rows["r1"] == {
        "run_id": "r1",
        "transcript_commands": ["ls", TEST_CMD, "ruff check ."],
        "ledger_commands": ["ls", TEST_CMD, "ruff check ."],
        "missing": [],
        "unparsed_actions": 1,
    }
    assert rows["r7"]["transcript_commands"] == ["ls", TEST_CMD, "ruff check ."]
    assert rows["r7"]["missing"] == ["ls"] and data["total_missing"] == 1
    assert data["runs_dirs"] == [e0.SMOKE_RUNS]


@pytest.mark.parametrize("problem", ["agent", "transcript", "prompt", "task", "test_cmd", "dupe"])
def test_completeness_refuses_unreadable_runs(git_repo: Path, commit: Commit, problem: str) -> None:
    runs = git_repo / "runs"
    run_dir = write_run(
        runs, "r1", "Done.", agent="claude-code" if problem == "agent" else "minimal-agent"
    )
    bench = git_repo / "bench"
    (bench / "t-alpha").mkdir(parents=True)
    (bench / "t-alpha" / "task.toml").write_text(f'test_cmd = "{TEST_CMD}"\n', "utf-8")
    commit(git_repo, "world")
    dirs = [runs]
    expected = {
        "agent": "reads minimal-agent transcripts, not 'claude-code'",
        "transcript": "transcript.json has no messages",
        "prompt": "prompt_sha256",
        "task": "cannot read the test command of task t-alpha",
        "test_cmd": "has no test_cmd",
        "dupe": "appears in more than one runs directory",
    }[problem]
    if problem == "transcript":
        (run_dir / "transcript.json").write_text("{}", "utf-8")
    elif problem == "prompt":
        record = json.loads((run_dir / "run.json").read_text("utf-8"))
        record["provenance"]["prompt_sha256"] = "0" * 64
        (run_dir / "run.json").write_text(json.dumps(record), "utf-8")
    elif problem == "task":
        (bench / "t-alpha" / "task.toml").write_text("test_cmd = [", "utf-8")
    elif problem == "test_cmd":
        (bench / "t-alpha" / "task.toml").write_text('id = "t-alpha"\n', "utf-8")
    elif problem == "dupe":
        dirs = [runs, runs]
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.completeness_artifact(git_repo, dirs, bench, command="c")


def test_completeness_needs_real_runs(git_repo: Path, commit: Commit) -> None:
    runs = git_repo / "runs"
    write_run(runs, "s1", "Synthetic.", synthetic=True)
    commit(git_repo, "world")
    with pytest.raises(e0.E0Error, match="no real runs to check"):
        e0.completeness_artifact(git_repo, [runs], git_repo, command="c")
