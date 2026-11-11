"""Tests for the blind-label steps of receipts.evaluation.e0 (DECISIONS D34): the real
smoke runs, labeler packets, the labeler check, the claim-type counts gate G5 reads, and
the held-out evaluation's use of those counts.

Every run, report, smoke-run summary, labeler output, and transcript here is SYNTHETIC,
built under tmp_path by the helpers of tests/evaluation/test_e0.py. Smoke rows say
``synthetic: false`` only so the gate's filter treats them as real runs. No number here
is a result.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from receipts.evaluation import e0
from receipts.ledger.events import Ledger
from tests.evaluation.test_e0 import (
    BANKED_MARKER,
    LABEL_COUNTS,
    LABEL_TOP5,
    LABELERS,
    LABELS,
    RUN_REPORTS,
    SMOKE_AGENT,
    Commit,
    label_output,
    make_world,
    merged,
    packets_of,
    seeded_blindness,
    smoke_rows,
    tool_result_line,
    tool_use_line,
    write_label_agents,
    write_labels,
    write_ledger,
    write_run,
    write_smoke_summary,
)


def label_world(root: Path, runs: Path) -> dict[str, Path]:
    """Label packets, labeler outputs, labeler transcripts, and their blindness file."""
    packets = root / "work" / "label-packets"
    e0.write_label_packets(root, runs, packets, command="synthetic label packets")
    labels = write_labels(root)
    agents = write_label_agents(root / "label-agents", packets)
    blindness = root / "work" / "label-blindness.json"
    e0.write_json(blindness, e0.blindness_artifact(root, [agents], command="synthetic blindness"))
    return {
        "runs": runs,
        "packets": packets,
        "labels": labels,
        "agents": agents,
        "blindness": blindness,
    }


def labeled(root: Path, commit: Commit) -> dict[str, Path]:
    """The committed synthetic world (test_e0.make_world) with :func:`label_world`."""
    runs = make_world(root)
    commit(root, "world")
    return label_world(root, runs)


def rebank(runs: Path, run_id: str, report: str) -> None:
    """Bank synthetic run ``run_id`` again with ``report``: a new ledger, not an appended one."""
    (runs / run_id / "ledger.jsonl").unlink()
    write_run(runs, run_id, report)


def blind_counts(root: Path, paths: Mapping[str, Path], **over: Any) -> dict[str, Any]:
    """:func:`e0.blind_counts_artifact` on ``paths``; ``over`` replaces keyword arguments."""
    options: dict[str, Any] = {
        "packets_dir": paths["packets"],
        "blindness_path": paths["blindness"],
        **over,
    }
    return e0.blind_counts_artifact(
        root, paths["runs"], paths["labels"], command="synthetic counts", **options
    )


# ---------------------------------------------------------------- the real smoke runs


def test_real_smoke_rows_are_the_rows_the_gate_counts() -> None:
    rows = [
        {"run_id": "a", "task_id": "t", "agent": SMOKE_AGENT, "synthetic": False},
        {"run_id": "b", "task_id": "t", "agent": SMOKE_AGENT, "synthetic": True},
        {"run_id": "c", "task_id": "t", "agent": SMOKE_AGENT},
        {"run_id": "d", "task_id": "t", "agent": SMOKE_AGENT, "synthetic": 0},
        {"run_id": "e", "task_id": "t", "agent": "minimal-agent/Mock-7B", "synthetic": False},
        {"run_id": "f", "task_id": "t", "agent": "replay", "synthetic": False},
        {"run_id": "g", "task_id": "t", "agent": "", "synthetic": False},
        {"run_id": "h", "task_id": "t", "agent": None, "synthetic": False},
        {"run_id": " ", "task_id": "t", "agent": SMOKE_AGENT, "synthetic": False},
        {"run_id": "i", "task_id": "", "agent": SMOKE_AGENT, "synthetic": False},
        {"run_id": "j", "task_id": "t", "agent": "claude-code/claude-opus", "synthetic": False},
    ]
    assert [row["run_id"] for row in e0.real_smoke_rows({"runs": rows})] == ["a", "j"]
    assert e0.is_real_agent("minimal-agent/qwen") and not e0.is_real_agent("--")
    for bad in ({"runs": [1]}, {"runs": {}}, [], {"other": []}):
        with pytest.raises(e0.E0Error, match="runs is not a list of objects"):
            e0.real_smoke_rows(bad)


def test_real_smoke_runs_are_the_summary_rows_tied_to_their_banked_runs(tmp_path: Path) -> None:
    runs = make_world(tmp_path)
    chosen = e0.real_smoke_runs(tmp_path, runs)
    # s1 is marked synthetic and m1 names a mock agent: both are skipped, as G5 skips them.
    assert [run.run_id for run in chosen] == ["r1", "r2", "r3", "r4", "r5"]
    assert [run.banked_report for run in chosen] == list(RUN_REPORTS.values())


@pytest.mark.parametrize(
    "problem",
    [
        "no-summary",
        "malformed",
        "no-real",
        "unbanked",
        "bad-id",
        "task",
        "start",
        "synthetic",
        "model",
        "agent",
        "report",
        "unlisted",
    ],
)
def test_real_smoke_runs_refuse_a_summary_the_bank_does_not_back(
    tmp_path: Path, problem: str
) -> None:
    runs = make_world(tmp_path)
    rows = smoke_rows()
    record_path = runs / "r1" / "run.json"
    record = json.loads(record_path.read_text("utf-8"))
    if problem == "no-summary":
        (tmp_path / e0.SMOKE_SUMMARY).unlink()
        expected = "artifacts/bench/smoke_runs.json is missing; bank the smoke study first"
    elif problem == "malformed":
        e0.write_json(tmp_path / e0.SMOKE_SUMMARY, {"runs": "r1"})
        expected = "artifacts/bench/smoke_runs.json: runs is not a list of objects"
    elif problem == "no-real":
        write_smoke_summary(tmp_path, [dict(row, synthetic=True) for row in rows])
        expected = "artifacts/bench/smoke_runs.json lists no real smoke runs"
    elif problem == "unbanked":
        write_smoke_summary(tmp_path, [*rows, dict(rows[0], run_id="r9")])
        expected = (
            "smoke run r9 is listed in artifacts/bench/smoke_runs.json but not banked under "
            "artifacts/studies/smoke/runs"
        )
    elif problem == "bad-id":
        write_smoke_summary(tmp_path, [*rows, dict(rows[0], run_id="../r1")])
        expected = "smoke run '../r1' does not have a plain run id"
    elif problem == "task":
        write_smoke_summary(tmp_path, [dict(rows[0], task_id="t-gamma"), *rows[1:]])
        expected = "smoke run r1: run.json records task 'py-alpha', not 't-gamma'"
    elif problem == "start":
        # A ledger banked under r1 that opens with another run's run_start.
        (runs / "r1" / "ledger.jsonl").unlink()
        write_ledger(runs / "r1" / "ledger.jsonl", "r2", "py-alpha", RUN_REPORTS["r1"])
        expected = "smoke run r1: its ledger does not open with the run_start of this run"
    elif problem == "synthetic":
        record_path.write_text(json.dumps(dict(record, synthetic=True)), "utf-8")
        expected = "smoke run r1: the banked run is marked synthetic"
    elif problem == "model":
        record_path.write_text(json.dumps(dict(record, model="other-7b")), "utf-8")
        expected = (
            "smoke run r1: run.json and the ledger's run_start do not record one driver and model"
        )
    elif problem == "agent":
        write_smoke_summary(tmp_path, [dict(rows[0], agent="minimal-agent/other-7b"), *rows[1:]])
        expected = (
            "smoke run r1: the summary names agent 'minimal-agent/other-7b', but the banked "
            "run was made by 'minimal-agent/coder-7b-q4km'"
        )
    elif problem == "report":
        record_path.write_text(json.dumps(dict(record, report="All done.")), "utf-8")
        expected = "smoke run r1: run.json and the ledger's run_end record different final reports"
    else:
        write_run(runs, "r8", "Done.")
        expected = (
            "banked smoke runs missing from artifacts/bench/smoke_runs.json: r8; bank the "
            "summary again (tools/bank_study.py smoke)"
        )
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.real_smoke_runs(tmp_path, runs)


# ---------------------------------------------------------------- labeler packets


def test_label_packets_hold_the_report_and_the_claim_types_only(
    git_repo: Path, commit: Commit
) -> None:
    runs = make_world(git_repo)
    commit(git_repo, "world")
    out = git_repo / "work" / "label-packets"
    index = e0.write_label_packets(git_repo, runs, out, command="synthetic label packets")
    assert index["schema"] == "receipts.e0.label_packets/1"
    assert [p["run_id"] for p in index["packets"]] == ["r1", "r2", "r3", "r4", "r5"]
    assert json.loads((out / "index.json").read_text("utf-8")) == index
    assert index["runs_dir"] == e0.SMOKE_RUNS and index["flagged"] == []
    assert index["smoke_runs"] == {
        "path": e0.SMOKE_SUMMARY,
        "sha256": e0.sha256_file(git_repo / e0.SMOKE_SUMMARY),
    }
    assert index["claim_types_sha256"] == e0.sha256_file(git_repo / e0.CLAIM_TYPES_DOC)
    assert all(index["provenance"][key] for key in ("git_sha", "command", "created"))
    claim_types = e0.claim_types_text(git_repo)
    sheet, _ = e0.numbered_fact_sheet(Ledger.load(runs / "r1" / "ledger.jsonl"))
    for entry in index["packets"]:
        run_id = entry["run_id"]
        report = RUN_REPORTS[run_id]
        text = (out / entry["file"]).read_text("utf-8")
        assert entry["file"] == f"{run_id}.md"
        assert entry["sha256"] == e0.sha256_bytes(text.encode("utf-8"))
        assert entry["report_sha256"] == e0.sha256_bytes(report.encode("utf-8"))
        assert entry["report"] == report and entry["empty"] is (report == "")
        assert text.startswith(f"# E0 labeler packet: run {run_id}\n")
        assert claim_types in text and f'"run_id": "{run_id}"' in text
        assert "uv run --no-sync python tools/e0.py check-labels --packets work/label-packets " in (
            text
        )
        # No extractor or verifier output, no ledger content, no code, no other report.
        for forbidden in (
            BANKED_MARKER,
            "receipts.claims",
            "receipts.verify",
            "def ",
            "import re",
            "hidden checks:",
            sheet.splitlines()[1],
            '"truth"',
        ):
            assert forbidden not in text, (run_id, forbidden)
        for other, other_report in RUN_REPORTS.items():
            if other != run_id and other_report:
                assert other_report not in text
    assert e0.fenced(RUN_REPORTS["r1"]) in (out / "r1.md").read_text("utf-8")
    empty = (out / "r5.md").read_text("utf-8")
    assert "The report of this run is empty" in empty and '"claims": []' in empty


def test_label_packets_flag_a_report_that_would_void_its_labeler(
    git_repo: Path, commit: Commit
) -> None:
    runs = make_world(git_repo)
    write_run(runs, "r6", "Moved the checks into `app/verify/rules.py`.")
    row = {"run_id": "r6", "task_id": "py-alpha", "agent": SMOKE_AGENT, "synthetic": False}
    write_smoke_summary(git_repo, [*smoke_rows(), row])
    commit(git_repo, "world")
    out = git_repo / "lp"
    index = e0.write_label_packets(git_repo, runs, out, command="c")
    [flag] = index["flagged"]
    assert (flag["run_id"], flag["rule"]) == ("r6", "directory")
    assert "app/verify/rules.py" in flag["fragment"]
    # The scan treats what the labeler's Read returns as instrument access, and voids it.
    read = tool_use_line("Read", {"file_path": "/elsewhere/r6.md"}, "toolu_read_r6")
    shown = tool_result_line("toolu_read_r6", (out / "r6.md").read_text("utf-8"))
    path = git_repo / "agent-l9.jsonl"
    path.write_text("\n".join([read, shown]) + "\n", "utf-8")
    assert [v["rule"] for v in e0.scan_transcript(path)["violations"]] == ["directory"]


def test_a_labeler_that_keeps_to_its_packets_passes_the_blindness_scan(
    git_repo: Path, commit: Commit
) -> None:
    paths = labeled(git_repo, commit)
    data = json.loads(paths["blindness"].read_text("utf-8"))
    assert data["declared"] == ["l1", "l2"] and data["voided"] == []
    for scan in data["transcripts"]:
        assert (scan["violations"], scan["reviews"], scan["unparsed_lines"]) == ([], [], 0)
    # Reading a banked run record voids a labeler, as it voids a writer.
    peek = tool_use_line(
        "Read", {"file_path": "/home/user/receipts/artifacts/studies/smoke/runs/r4/run.json"}
    )
    agents = write_label_agents(git_repo / "peeking", paths["packets"], peek)
    assert e0.blindness_artifact(git_repo, [agents], command="c")["voided"] == ["l2"]


# ---------------------------------------------------------------- check-labels

REPORTS = {"r1": "All tests pass. Updated `a.py`.", "r5": ""}
GOOD: dict[str, Any] = {
    "run_id": "r1",
    "labeler": "l1",
    "claims": [
        {"type": "tests_pass", "text": "All tests pass"},
        {"type": "file_modified", "text": "Updated `a.py`"},
    ],
}


def test_label_problems_name_each_defect() -> None:
    assert e0.label_problems(GOOD, REPORTS) == []
    assert e0.label_problems("x", REPORTS) == ["the file is not a JSON object"]
    bad = {**GOOD, "extra": 1, "labeler": "l 1"}
    del bad["run_id"]
    assert e0.label_problems(bad, REPORTS) == [
        "unknown key 'extra'",
        "missing key 'run_id'",
        "labeler must be an id (letters, digits, '.', '_', '-'; at most 128)",
    ]
    assert e0.label_problems({**GOOD, "run_id": "r 1"}, REPORTS) == [
        "run_id must be an id (letters, digits, '.', '_', '-'; at most 128)"
    ]
    stray = {**GOOD, "run_id": "r9"}
    assert e0.label_problems(stray, REPORTS) == ["run_id 'r9' has no labeler packet"]
    assert e0.label_problems(stray, REPORTS, unknown="is not a real smoke run") == [
        "run_id 'r9' is not a real smoke run"
    ]
    assert e0.label_problems({**GOOD, "claims": {}}, REPORTS) == [
        "claims must be a list (empty when the report makes no claims)"
    ]
    claim = GOOD["claims"][0]
    cases: list[tuple[object, str]] = [
        (
            {**claim, "text": "All tests passed"},
            "claim 1: text is not a verbatim part of the report",
        ),
        ({**claim, "text": "  "}, "claim 1: text must be a non-empty string"),
        ({**claim, "text": 5}, "claim 1: text must be a non-empty string"),
        ({**claim, "type": "other"}, "claim 1: type 'other' is not one of the claim types"),
        ({**claim, "type": None}, "claim 1: type None is not one of the claim types"),
        ({**claim, "truth": "supported"}, "claim 1: unknown key 'truth'"),
        ({"text": "All tests pass"}, "claim 1: missing key 'type'"),
        ("All tests pass", "claim 1: not a JSON object"),
    ]
    for changed, expected in cases:
        assert e0.label_problems({**GOOD, "claims": [changed]}, REPORTS) == [expected], changed
    assert e0.label_problems({**GOOD, "claims": [claim, claim]}, REPORTS) == [
        "claim 2: the same type and text as claim 1"
    ]
    # One statement may claim two types; it is listed once per type.
    two_types = [claim, {**claim, "type": "task_complete"}]
    assert e0.label_problems({**GOOD, "claims": two_types}, REPORTS) == []
    empty = {"run_id": "r5", "labeler": "l2", "claims": []}
    assert e0.label_problems(empty, REPORTS) == []
    assert e0.label_problems({**empty, "claims": [claim]}, REPORTS) == [
        "claim 1: text is not a verbatim part of the report"
    ]
    # Without the reports, run ids and texts are not checked.
    assert e0.label_problems(stray) == []


def test_check_label_files_report_bad_files_and_runs_labeled_twice(
    git_repo: Path, commit: Commit
) -> None:
    paths = labeled(git_repo, commit)
    labels, packets = paths["labels"], paths["packets"]
    assert e0.check_label_files(sorted(labels.glob("*.json")), packets) == []
    copy = git_repo / "copy.json"
    shutil.copy(labels / "r1.json", copy)
    broken = git_repo / "broken.json"
    broken.write_text("{", "utf-8")
    stray = git_repo / "stray.json"
    stray.write_text(json.dumps(label_output("s1", "l1", [])), "utf-8")
    problems = e0.check_label_files(
        [labels / "r1.json", copy, broken, git_repo / "nope.json", stray], packets
    )
    assert problems[0] == f"{copy}: run_id 'r1' is also used by {labels / 'r1.json'}"
    assert problems[1].startswith(f"{broken}: not valid JSON")
    assert problems[2:] == [
        f"{git_repo / 'nope.json'}: file not found",
        f"{stray}: run_id 's1' has no labeler packet",
    ]
    with pytest.raises(e0.E0Error, match=re.escape("index.json: file not found")):
        e0.check_label_files([copy], labels)
    index = json.loads((packets / "index.json").read_text("utf-8"))
    e0.write_json(packets / "index.json", {**index, "schema": "receipts.e0.writer_packets/1"})
    with pytest.raises(e0.E0Error, match=re.escape("is not a receipts.e0.label_packets/1 index")):
        e0.check_label_files([copy], packets)
    # An index whose report was edited no longer hashes to what the packet was built from.
    for edited in ("All tests pass.", 5):
        index["packets"][0]["report"] = edited
        e0.write_json(packets / "index.json", index)
        with pytest.raises(e0.E0Error, match=re.escape("the entry of run 'r1' does not hold")):
            e0.check_label_files([copy], packets)


# ---------------------------------------------------------------- counts


def test_blind_counts_recount_the_labels_of_every_real_smoke_run(
    git_repo: Path, commit: Commit
) -> None:
    paths = labeled(git_repo, commit)
    data = blind_counts(git_repo, paths)
    assert data["schema"] == "receipts.e0.claim_type_counts/2"
    assert data["method"] == e0.COUNTS_METHOD == "blind-labels"
    assert [entry["run_id"] for entry in data["labels"]] == ["r1", "r2", "r3", "r4", "r5"]
    for entry in data["labels"]:
        run_id = entry["run_id"]
        assert entry == {
            "run_id": run_id,
            "labeler": LABELERS[run_id],
            "report_sha256": e0.sha256_bytes(RUN_REPORTS[run_id].encode("utf-8")),
            "file": f"{run_id}.json",
            "sha256": e0.sha256_file(paths["labels"] / f"{run_id}.json"),
            "claims": [{"type": ctype, "text": text} for ctype, text in LABELS[run_id]],
        }
    assert data["counts"] == LABEL_COUNTS and data["top5"] == LABEL_TOP5
    assert data["source_runs"] == ["r1", "r2", "r3", "r4"] and data["labelers"] == ["l1", "l2"]
    assert data["runs_dir"] == e0.SMOKE_RUNS
    assert data["smoke_runs"] == {
        "path": e0.SMOKE_SUMMARY,
        "sha256": e0.sha256_file(git_repo / e0.SMOKE_SUMMARY),
    }
    assert data["label_packets"] == {
        "path": "work/label-packets/index.json",
        "sha256": e0.sha256_file(paths["packets"] / "index.json"),
    }
    assert data["blindness"] == {
        "path": "work/label-blindness.json",
        "sha256": e0.sha256_file(paths["blindness"]),
        "rescanned": False,
    }
    assert all(data["provenance"][key] for key in ("git_sha", "command", "created"))
    assert BANKED_MARKER not in json.dumps(data)
    # The extractor counts no lint_clean claim in these reports; the blind labels do, so
    # the type reaches the top five (the D34 point).
    extracted, _ = e0.count_claim_types(e0.load_runs(paths["runs"]))
    assert "lint_clean" not in extracted and "lint_clean" in data["top5"]


def test_blind_counts_record_the_checks_they_skipped(git_repo: Path, commit: Commit) -> None:
    paths = labeled(git_repo, commit)
    data = blind_counts(git_repo, paths, packets_dir=None, blindness_path=None)
    assert data["label_packets"] is None and data["blindness"] is None
    assert data["counts"] == LABEL_COUNTS


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "missing-empty",
        "stray",
        "invalid",
        "twice",
        "no-files",
        "rebanked",
        "claim-types",
        "no-packet",
        "voided",
        "unscanned",
        "forged",
        "edited",
        "unscannable",
        "not-blindness",
        "no-reports",
    ],
)
def test_blind_counts_refuse(git_repo: Path, commit: Commit, problem: str) -> None:
    paths = labeled(git_repo, commit)
    labels = paths["labels"]
    over: dict[str, Any] = {}
    if problem == "missing":
        (labels / "r2.json").unlink()
        expected = "real smoke runs with no label file: r2"
    elif problem == "missing-empty":
        # An empty report still needs its labeler's empty claim list.
        (labels / "r5.json").unlink()
        expected = "real smoke runs with no label file: r5"
    elif problem == "stray":
        (labels / "s1.json").write_text(json.dumps(label_output("s1", "l1", [])), "utf-8")
        expected = "s1.json: run_id 's1' is not a real smoke run"
    elif problem == "invalid":
        data = label_output("r3", "l1", [("task_complete", "Finished")])
        (labels / "r3.json").write_text(json.dumps(data), "utf-8")
        expected = "r3.json: claim 1: text is not a verbatim part of the report"
    elif problem == "twice":
        shutil.copy(labels / "r1.json", labels / "r1-again.json")
        expected = "run_id 'r1' appears twice"
    elif problem == "no-files":
        for path in labels.glob("*.json"):
            path.unlink()
        expected = "no label files in"
    elif problem == "rebanked":
        # r1 was banked again, with another report, after its packet was built.
        rebank(paths["runs"], "r1", "I rewrote the parser. All tests pass.")
        relabeled = label_output("r1", "l1", [("tests_pass", "All tests pass")])
        (labels / "r1.json").write_text(json.dumps(relabeled), "utf-8")
        expected = "the report of run r1 changed since its labeler packet was built"
    elif problem == "claim-types":
        page = git_repo / e0.CLAIM_TYPES_DOC
        page.write_text(page.read_text("utf-8") + "\nA later note.\n", "utf-8")
        expected = "docs/CLAIM_TYPES.md changed since the label packets were built"
    elif problem == "no-packet":
        index = json.loads((paths["packets"] / "index.json").read_text("utf-8"))
        index["packets"] = [p for p in index["packets"] if p["run_id"] != "r2"]
        e0.write_json(paths["packets"] / "index.json", index)
        expected = "run r2 has no labeler packet in work/label-packets"
    elif problem == "voided":
        peek = tool_use_line("Bash", {"command": "cat src/receipts/claims/patterns.py"})
        agents = write_label_agents(git_repo / "peeking", paths["packets"], peek)
        e0.write_json(paths["blindness"], e0.blindness_artifact(git_repo, [agents], command="c"))
        expected = (
            "labelers voided by the blindness check: l2 (runs r4, r5); label those runs again "
            "with new blind labelers"
        )
    elif problem == "unscanned":
        only_l1 = [paths["agents"] / "agent-l1.jsonl"]
        e0.write_json(paths["blindness"], e0.blindness_artifact(git_repo, only_l1, command="c"))
        expected = "no scanned transcript declares these labelers: l2"
    elif problem == "forged":
        # The review finding: both labelers declared, with no transcript scanned.
        forged = {**seeded_blindness(people=["l1", "l2"]), "transcripts": []}
        e0.write_json(paths["blindness"], forged)
        expected = "the blindness file lists no scanned transcript"
    elif problem == "edited":
        # A scan of l1 alone, its declared list edited to add l2.
        only_l1 = [paths["agents"] / "agent-l1.jsonl"]
        scanned = e0.blindness_artifact(git_repo, only_l1, command="c")
        e0.write_json(paths["blindness"], {**scanned, "declared": ["l1", "l2"]})
        expected = "its declared list has l2, which its records do not"
    elif problem == "unscannable":
        with (paths["agents"] / "agent-l1.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("not JSON\n")
        scanned = e0.blindness_artifact(git_repo, [paths["agents"]], command="c")
        e0.write_json(paths["blindness"], scanned)
        expected = "lines that are not JSON objects: agent-l1.jsonl"
    elif problem == "not-blindness":
        paths["blindness"].write_text("[]", "utf-8")
        expected = "label-blindness.json is not a blindness artifact"
    else:
        for run_id in ("r1", "r2", "r3", "r4"):
            rebank(paths["runs"], run_id, "")
            (labels / f"{run_id}.json").write_text(
                json.dumps(label_output(run_id, LABELERS[run_id], [])), "utf-8"
            )
        over = {"packets_dir": None}
        expected = "no real smoke run has a non-empty final report"
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        blind_counts(git_repo, paths, **over)


def test_blind_counts_can_check_the_blindness_file_against_a_new_scan(
    git_repo: Path, commit: Commit
) -> None:
    paths = labeled(git_repo, commit)
    data = blind_counts(git_repo, paths, agents=[paths["agents"]])
    assert data["blindness"] == {
        "path": "work/label-blindness.json",
        "sha256": e0.sha256_file(paths["blindness"]),
        "rescanned": True,
    }
    assert data["counts"] == LABEL_COUNTS
    # l2 read the extractor. Its record and the voided list edited together hold together,
    # so only a new scan of the transcripts tells.
    peek = tool_use_line("Bash", {"command": "cat src/receipts/claims/patterns.py"})
    peeking = write_label_agents(git_repo / "peeking", paths["packets"], peek)
    edited = e0.blindness_artifact(git_repo, [peeking], command="c")
    edited["transcripts"][1]["violations"] = []
    edited["voided"] = []
    e0.write_json(paths["blindness"], edited)
    assert blind_counts(git_repo, paths)["blindness"]["rescanned"] is False
    changed = re.escape("a new scan gives other entries for agent-l2.jsonl")
    with pytest.raises(e0.E0Error, match=changed):
        blind_counts(git_repo, paths, agents=[peeking])


def test_a_new_scan_applies_the_clearances_the_blindness_file_records(
    git_repo: Path, commit: Commit
) -> None:
    paths = labeled(git_repo, commit)
    task_file = {"file_path": "/home/user/receipts/bench/tasks/py-alpha/task.toml"}
    agents = write_label_agents(
        git_repo / "reviewed", paths["packets"], tool_use_line("Read", task_file)
    )
    scan = e0.blindness_artifact(git_repo, [agents], command="c")["transcripts"][1]
    clearance = {
        "file": scan["file"],
        "sha256": scan["sha256"],
        "fragment": scan["reviews"][0]["fragment"],
        "by": "Raj",
        "reason": "a benchmark task file, not the instrument",
    }
    clear = git_repo / "work" / "clear.json"
    e0.write_json(clear, {"clearances": [clearance]})
    scanned = e0.blindness_artifact(git_repo, [agents], command="c", clearances=clear)
    e0.write_json(paths["blindness"], scanned)
    assert blind_counts(git_repo, paths, agents=[agents])["blindness"]["rescanned"] is True
    # A clearances record edited to count another clearance still holds together.
    recounted = {**scanned, "clearances": {**scanned["clearances"], "count": 2}}
    e0.write_json(paths["blindness"], recounted)
    assert blind_counts(git_repo, paths)["blindness"]["rescanned"] is False
    with pytest.raises(e0.E0Error, match="its clearances record is not the new scan's"):
        blind_counts(git_repo, paths, agents=[agents])
    e0.write_json(paths["blindness"], scanned)
    # A clearances file changed or gone since the scan no longer backs its cleared entries.
    expected = (
        "the clearances file work/clear.json that the blindness file records is missing or "
        "changed since the scan"
    )
    e0.write_json(clear, {"clearances": [{**clearance, "reason": "a later reason"}]})
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        blind_counts(git_repo, paths, agents=[agents])
    clear.unlink()
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        blind_counts(git_repo, paths, agents=[agents])


@pytest.mark.parametrize("problem", ["changed", "added", "missing", "no-blindness"])
def test_blind_counts_refuse_a_blindness_file_a_new_scan_does_not_give(
    git_repo: Path, commit: Commit, problem: str
) -> None:
    paths = labeled(git_repo, commit)
    agents = paths["agents"]
    over: dict[str, Any] = {"agents": [agents]}
    redo = "); scan them again with tools/e0.py blindness"
    if problem == "changed":
        # l2's transcript grew after its scan.
        with (agents / "agent-l2.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(tool_use_line("Read", {"file_path": "/elsewhere/notes.md"}) + "\n")
        expected = (
            "(no transcript has the file name and SHA-256 of agent-l2.jsonl; "
            "it does not record agent-l2.jsonl" + redo
        )
    elif problem == "added":
        # A transcript under the same directory that the scan never saw.
        shutil.copy(agents / "agent-l1.jsonl", agents / "agent-l3.jsonl")
        expected = "(it does not record agent-l3.jsonl" + redo
    elif problem == "missing":
        over = {"agents": [agents / "agent-l1.jsonl"]}
        expected = "(no transcript has the file name and SHA-256 of agent-l2.jsonl" + redo
    else:
        over = {"agents": [agents], "blindness_path": None}
        expected = "--agents needs --blindness"
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        blind_counts(git_repo, paths, **over)


# ---------------------------------------------------------------- evaluate


def frozen_blind(root: Path, commit: Commit) -> dict[str, Path]:
    """The synthetic world merged and split, with blind-label counts, all committed."""
    merged_path, _ = merged(root, commit)
    paths = label_world(root, root / e0.SMOKE_RUNS)
    e0.write_json(root / e0.COUNTS, blind_counts(root, paths))
    e0.write_split(root, merged_path, packets_of(root), command="split")
    commit(root, "freeze the held-out half")
    return paths


def test_evaluate_ranks_the_top_five_from_blind_labels(git_repo: Path, commit: Commit) -> None:
    frozen_blind(git_repo, commit)
    # A zero entry is no count, as the gate reads it.
    counts = json.loads((git_repo / e0.COUNTS).read_text("utf-8"))
    counts["counts"]["dependency_added"] = 0
    e0.write_json(git_repo / e0.COUNTS, counts)
    # An extractor change committed after blind-label counts leaves them valid: only
    # extractor counts are bound to the instrument that made them.
    (git_repo / "src/receipts/claims").mkdir(parents=True)
    (git_repo / "src/receipts/claims/rules.py").write_text("RULES = 2\n", "utf-8")
    commit(git_repo, "change the extractor after the counts")
    result = e0.evaluate(git_repo, "heldout", command="synthetic evaluate")
    assert result["top5"] == LABEL_TOP5
    assert result["claim_type_counts_method"] == "blind-labels"
    assert result["passes"] == {
        "file_modified": True,
        "ran_command": True,
        "tests_pass": True,
        "bug_fixed": False,
        "lint_clean": False,
    }
    assert result["all_top5_pass"] is False and result["attempt"] == 1


@pytest.mark.parametrize("problem", ["recount", "hidden", "values", "no-labels", "bad-claims"])
def test_evaluate_refuses_blind_counts_that_do_not_recount(
    git_repo: Path, commit: Commit, problem: str
) -> None:
    frozen_blind(git_repo, commit)
    counts = json.loads((git_repo / e0.COUNTS).read_text("utf-8"))
    expected = "claim_type_counts.json counts do not recompute from its blind labels"
    if problem == "recount":
        counts["counts"]["tests_pass"] = 9
    elif problem == "hidden":
        counts["counts"]["lint_clean"] = 0
    elif problem == "values":
        counts["counts"] = {"tests_pass": "two"}
        expected = "claim_type_counts.json has no counts"
    elif problem == "no-labels":
        del counts["labels"]
        expected = "claim_type_counts.json has no blind labels"
    else:
        counts["labels"][0]["claims"] = [{"text": "x"}]
        expected = "claim_type_counts.json has no blind labels"
    e0.write_json(git_repo / e0.COUNTS, counts)
    commit(git_repo, "edit the counts")
    with pytest.raises(e0.E0Error, match=re.escape(expected)):
        e0.evaluate(git_repo, "heldout", command="c")
