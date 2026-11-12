"""Tests for tools/e0.py, the E0 command line (gate G5).

Every run, report, smoke-run summary, writer output, adjudication, labeler output, and
transcript here is SYNTHETIC, built by the helpers of tests/evaluation/test_e0.py under
tmp_path; smoke rows say ``synthetic: false`` only so the gate's filter treats them as
real runs, and no number here is a result. The blindness tests run the writer,
adjudicator, and labeler commands in a subprocess and check that neither receipts.claims
nor receipts.verify is ever imported. The contract tests run the G5 code of this working
tree (tools/ship_check.py) on what this tool writes.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import e0 as cli
import ship_check
from receipts.evaluation import e0
from receipts.evaluation.seeded import VERDICTS
from tests.evaluation.test_e0 import (
    LABEL_TOP5,
    REQUIREMENTS,
    SMOKE_AGENT,
    label_output,
    make_world,
    raw_output,
    smoke_rows,
    tool_use_line,
    write_agent,
    write_label_agents,
    write_labels,
    write_outputs,
    write_run,
    write_smoke_summary,
    write_transcripts,
)

REPO = Path(__file__).resolve().parents[2]
Commit = Callable[[Path, str], str]
INSTRUMENT_MODULES = ("receipts.claims", "receipts.verify")


def run(root: Path, *argv: str) -> int:
    return cli.main(list(argv), root=root)


def pipeline(root: Path, commit: Commit, capsys: pytest.CaptureFixture[str]) -> dict[str, Path]:
    """Every E0 step through the command line, up to a frozen held-out half."""
    runs = make_world(root)
    commit(root, "world")
    packets, adj_packets = root / "work" / "packets", root / "work" / "adj-packets"
    label_packets = root / "work" / "label-packets"
    assert run(root, "label-packets", "--runs", str(runs), "--out", str(label_packets)) == 0
    labels = write_labels(root)
    label_files = sorted(map(str, labels.glob("*.json")))
    assert run(root, "check-labels", "--packets", str(label_packets), *label_files) == 0
    agents = write_label_agents(write_transcripts(root / "agents"), label_packets)
    assert run(root, "packets", "--runs", str(runs), "--out", str(packets)) == 0
    raw_dir, adj_dir = write_outputs(root)
    assert run(root, "check-raw", "--packets", str(packets), *map(str, raw_dir.glob("*"))) == 0
    assert (
        run(
            root,
            "adjudication-packets",
            "--runs",
            str(runs),
            "--raw",
            str(raw_dir),
            "--packets",
            str(packets),
            "--out",
            str(adj_packets),
        )
        == 0
    )
    files = sorted(map(str, adj_dir.glob("*")))
    assert run(root, "check-adjudication", "--packets", str(adj_packets), *files) == 0
    assert run(root, "blindness", "--agents", str(agents)) == 0
    blindness = str(root / e0.BLINDNESS)
    # Counts and merge both scan the transcripts again to check the blindness file.
    assert (
        run(
            root,
            "counts",
            "--method",
            "blind-labels",
            "--labels",
            str(labels),
            "--packets",
            str(label_packets),
            "--blindness",
            blindness,
            "--agents",
            str(agents),
        )
        == 0
    )
    assert (
        run(
            root,
            "merge",
            "--raw",
            str(raw_dir),
            "--adjudication",
            str(adj_dir),
            "--blindness",
            blindness,
            "--agents",
            str(agents),
        )
        == 0
    )
    for name in (e0.COUNTS, e0.MERGED):
        assert json.loads((root / name).read_text("utf-8"))["blindness"]["rescanned"] is True
    assert run(root, "split", "--packets", str(packets)) == 0
    capsys.readouterr()
    return {
        "runs": runs,
        "packets": packets,
        "adj_packets": adj_packets,
        "raw": raw_dir,
        "adj": adj_dir,
        "label_packets": label_packets,
        "labels": labels,
    }


def test_the_whole_pipeline_through_the_command_line(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = pipeline(git_repo, commit, capsys)
    assert run(git_repo, "evaluate") == 2
    assert "is not committed" in capsys.readouterr().err
    commit(git_repo, "freeze the held-out half")
    assert run(git_repo, "evaluate") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("file_modified: P=1.000 [") and "R=1.000 [" in out[0]
    assert out[3] == "bug_fixed: P=n/a R=n/a"
    assert out[-1] == (
        "wrote artifacts/e0/seeded_eval.json: heldout, 2 reports; not every top-five type passes"
    )
    assert run(git_repo, "evaluate", "--split", "dev") == 0
    assert "wrote artifacts/e0/seeded_eval_dev.json: dev, 1 reports" in capsys.readouterr().out
    assert run(git_repo, "completeness", "--runs", str(paths["runs"])) == 0
    assert capsys.readouterr().out == (
        "wrote artifacts/e0/ledger_completeness.json: 5 runs, 0 missing\n"
    )
    evaluation = json.loads((git_repo / e0.EVAL).read_text("utf-8"))
    assert evaluation["provenance"]["command"] == "python tools/e0.py evaluate"
    # Verified in the preregistered verifier mode, with a record per report (D54).
    assert evaluation["verifier_mode"] == "task_requirements"
    assert sorted(evaluation["report_requirements"]) == ["rep-3", "rep-9"]
    alt = git_repo / "rescored.json"
    assert run(git_repo, "evaluate", "--out", str(alt)) == 2
    assert "commit the earlier held-out attempt" in capsys.readouterr().err
    commit(git_repo, "the first held-out attempt")
    assert run(git_repo, "evaluate", "--out", str(alt)) == 0
    rescored = json.loads(alt.read_text("utf-8"))
    assert rescored["items"] == evaluation["items"]
    assert (evaluation["attempt"], rescored["attempt"]) == (1, 2)
    assert run(git_repo, "evaluate", "--allow-dirty") == 2
    assert "--allow-dirty is not allowed for the held-out split" in capsys.readouterr().err


def test_step_summaries(git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]) -> None:
    runs = make_world(git_repo)
    commit(git_repo, "world")
    extracted = ["counts", "--method", "pattern-extractor", "--runs", str(runs)]
    assert run(git_repo, *extracted, "--out", str(git_repo / "c.json")) == 0
    assert capsys.readouterr().out == (
        "wrote c.json: 4 reports; top five: file_modified, ran_command, tests_pass, "
        "bug_fixed, task_complete; descriptive only, not the G5 counts\n"
    )
    agents = write_transcripts(git_repo / "agents")
    assert run(git_repo, "blindness", "--agents", str(agents)) == 0
    assert capsys.readouterr().out == (
        "wrote artifacts/e0/blindness.json: 5 transcripts, 1 with violations, "
        "0 with uncleared reviews, 0 unscannable; voided: w3\n"
    )
    raw_dir, adj_dir = write_outputs(git_repo)
    assert run(git_repo, "merge", "--raw", str(raw_dir), "--adjudication", str(adj_dir)) == 0
    assert capsys.readouterr().out == (
        "wrote artifacts/e0/merged.json: 4 reports, 8 gold claims, 1 dropped, 0 reports excluded\n"
    )
    packets = git_repo / "work" / "packets"
    assert run(git_repo, "packets", "--runs", str(runs), "--out", str(packets)) == 0
    assert capsys.readouterr().out == "wrote work/packets/index.json: 5 packets\n"
    assert run(git_repo, "split", "--packets", str(packets)) == 0
    assert (
        capsys.readouterr().out == "wrote artifacts/e0/heldout_manifest.json: 3 held out, 1 dev\n"
    )


def test_blindness_clears_reviews_and_exits_1_while_merge_would_refuse(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(git_repo, "empty")
    agents = git_repo / "agents"
    write_agent(agents, "w1", "writer", tool_use_line("Bash", {"command": "git log -3"}))
    assert run(git_repo, "blindness", "--agents", str(agents)) == 0
    assert capsys.readouterr().out.endswith("1 with uncleared reviews, 0 unscannable; voided: w1\n")
    scan = json.loads((git_repo / e0.BLINDNESS).read_text("utf-8"))["transcripts"][0]
    clearance = {
        "file": scan["file"],
        "sha256": scan["sha256"],
        "fragment": scan["reviews"][0]["fragment"],
        "by": "Raj",
        "reason": "git log of the receipts repository shows commit subjects only",
    }
    clear = git_repo / "clear.json"
    e0.write_json(clear, {"clearances": [clearance]})
    assert run(git_repo, "blindness", "--agents", str(agents), "--clear", str(clear)) == 0
    assert capsys.readouterr().out.endswith(
        "0 with uncleared reviews, 0 unscannable; voided: none\n"
    )
    (agents / "anon.jsonl").write_text(
        tool_use_line("Bash", {"command": "ls tests/"}) + "\nnot JSON\n", "utf-8"
    )
    assert run(git_repo, "blindness", "--agents", str(agents), "--clear", str(clear)) == 1
    assert capsys.readouterr().out.splitlines() == [
        "anon.jsonl: 1 line(s) that are not JSON objects; merge and counts refuse until it "
        "is scanned in full",
        "anon.jsonl: voids but declares no writer, adjudicator, or labeler id; merge and "
        "counts refuse",
        "wrote artifacts/e0/blindness.json: 2 transcripts, 0 with violations, "
        "1 with uncleared reviews, 1 unscannable; voided: none",
    ]


def test_checks_print_one_line_per_problem_and_exit_1(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = pipeline(git_repo, commit, capsys)
    bad = git_repo / "bad.json"
    bad.write_text(json.dumps(raw_output("rep-x", "r1", "w1", "All good.", [])), "utf-8")
    nameless = git_repo / "nameless.json"
    nameless.write_text(json.dumps({"report_id": 5}), "utf-8")
    assert (
        run(git_repo, "check-raw", "--packets", str(paths["packets"]), str(bad), str(nameless)) == 1
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"{bad}: claims must be a non-empty list"
    assert lines[1] == f"{nameless}: missing key 'claims'"
    assert len(lines) == 6 and all(line.startswith(str(nameless)) for line in lines[1:])
    labels = json.loads((paths["adj"] / "rep-3.json").read_text("utf-8"))
    labels["labels"] = labels["labels"][:1]
    short = git_repo / "short.json"
    short.write_text(json.dumps(labels), "utf-8")
    assert (
        run(git_repo, "check-adjudication", "--packets", str(paths["adj_packets"]), str(short)) == 1
    )
    assert capsys.readouterr().out == f"{short}: claims not labeled: g2, g3\n"


def test_refusals_exit_2_with_the_reason(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = pipeline(git_repo, commit, capsys)
    commit(git_repo, "freeze")
    assert run(git_repo, "split", "--packets", str(paths["packets"])) == 2
    assert capsys.readouterr().err.startswith("e0 split: artifacts/e0/heldout_manifest.json or")
    assert run(git_repo, "check-raw", "--packets", str(git_repo), "x.json") == 2
    assert "index.json: file not found" in capsys.readouterr().err
    merge = ["merge", "--raw", str(paths["raw"]), "--adjudication", str(paths["adj"])]
    assert run(git_repo, *merge, "--agents", str(git_repo / "agents")) == 2
    assert capsys.readouterr().err == "e0 merge: --agents needs --blindness\n"
    with pytest.raises(SystemExit):
        run(git_repo, "evaluate", "--split", "all")


def test_counts_and_completeness_default_to_the_smoke_runs(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    make_world(git_repo)
    commit(git_repo, "world")
    assert run(git_repo, "counts", "--method", "pattern-extractor") == 0
    # Extractor counts are descriptive output with their own file (D34).
    assert (git_repo / e0.EXTRACTOR_COUNTS).is_file() and not (git_repo / e0.COUNTS).exists()
    assert run(git_repo, "completeness", "--bench", str(git_repo / "bench" / "tasks")) == 0
    assert run(git_repo, "completeness") == 0
    data = json.loads((git_repo / e0.COMPLETENESS).read_text("utf-8"))
    assert data["runs_dirs"] == [e0.SMOKE_RUNS] and data["total_missing"] == 0
    packets = git_repo / "p"
    assert run(git_repo, "packets", "--out", str(packets)) == 0
    raw_dir, _ = write_outputs(git_repo)
    out = git_repo / "ap"
    assert (
        run(
            git_repo,
            "adjudication-packets",
            "--raw",
            str(raw_dir),
            "--packets",
            str(packets),
            "--out",
            str(out),
        )
        == 0
    )
    assert "wrote ap/index.json: 4 packets" in capsys.readouterr().out


# ---------------------------------------------------------------- blind labels (D34)


def labeled(root: Path, commit: Commit, capsys: pytest.CaptureFixture[str]) -> dict[str, Path]:
    """Label packets, labeler outputs, and the labelers' blindness file, by command line."""
    runs = make_world(root)
    commit(root, "world")
    packets = root / "work" / "label-packets"
    assert run(root, "label-packets", "--runs", str(runs), "--out", str(packets)) == 0
    labels = write_labels(root)
    agents = write_label_agents(root / "label-agents", packets)
    blindness = root / "work" / "label-blindness.json"
    assert run(root, "blindness", "--agents", str(agents), "--out", str(blindness)) == 0
    capsys.readouterr()
    return {
        "runs": runs,
        "packets": packets,
        "labels": labels,
        "agents": agents,
        "blindness": blindness,
    }


def test_labeling_through_the_command_line(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    make_world(git_repo)
    commit(git_repo, "world")
    packets = git_repo / "work" / "label-packets"
    assert run(git_repo, "label-packets", "--out", str(packets)) == 0
    assert capsys.readouterr().out == (
        "wrote work/label-packets/index.json: 5 packets (1 with an empty report)\n"
    )
    labels = write_labels(git_repo)
    files = sorted(map(str, labels.glob("*.json")))
    assert run(git_repo, "check-labels", "--packets", str(packets), *files) == 0
    assert capsys.readouterr().out == "check-labels: 5 file(s), no problems\n"
    bad = git_repo / "bad.json"
    claims = [("task_complete", "Finished"), ("other", "Done")]
    bad.write_text(json.dumps(label_output("r3", "l1", claims)), "utf-8")
    assert run(git_repo, "check-labels", "--packets", str(packets), str(bad)) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"{bad}: claim 1: text is not a verbatim part of the report",
        f"{bad}: claim 2: type 'other' is not one of the claim types",
    ]
    assert run(git_repo, "check-labels", "--packets", str(git_repo), str(bad)) == 2
    assert "index.json: file not found" in capsys.readouterr().err


def test_label_packets_exit_1_when_a_packet_would_void_its_labeler(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = make_world(git_repo)
    write_run(runs, "r6", "Moved the checks into `app/verify/rules.py`.")
    row = {"run_id": "r6", "task_id": "py-alpha", "agent": SMOKE_AGENT, "synthetic": False}
    write_smoke_summary(git_repo, [*smoke_rows(), row])
    commit(git_repo, "world")
    out = git_repo / "lp"
    assert run(git_repo, "label-packets", "--out", str(out)) == 1
    first, last = capsys.readouterr().out.splitlines()
    assert first.startswith("r6: its packet matches the blindness rule 'directory' (")
    assert first.endswith("); the scan voids a labeler who reads it")
    assert last == "wrote lp/index.json: 6 packets (1 with an empty report)"
    assert (out / "r6.md").is_file()


def test_blind_counts_through_the_command_line(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = labeled(git_repo, commit, capsys)
    counted = ["counts", "--method", "blind-labels", "--labels", str(paths["labels"])]
    checks = ["--packets", str(paths["packets"]), "--blindness", str(paths["blindness"])]
    # The G5 file is written only with both checks: the reports are the ones the packets
    # showed, and the blindness scan cleared every labeler (D34).
    assert run(git_repo, *counted) == 2
    assert "artifacts/e0/claim_type_counts.json needs --packets and --blindness" in (
        capsys.readouterr().err
    )
    assert run(git_repo, *counted, "--packets", str(paths["packets"])) == 2
    assert "needs --packets and --blindness" in capsys.readouterr().err
    assert not (git_repo / e0.COUNTS).exists()
    assert run(git_repo, *counted, *checks) == 0
    assert capsys.readouterr().out == (
        "wrote artifacts/e0/claim_type_counts.json: 5 runs labeled, 4 with a report, "
        "12 claims; top five: " + ", ".join(LABEL_TOP5) + "\n"
    )
    data = json.loads((git_repo / e0.COUNTS).read_text("utf-8"))
    assert data["provenance"]["command"] == "python tools/e0.py " + " ".join([*counted, *checks])
    assert data["blindness"]["rescanned"] is False
    # --agents scans the labelers' transcripts again to check the blindness file.
    assert run(git_repo, *counted, *checks, "--agents", str(paths["agents"])) == 0
    capsys.readouterr()
    assert json.loads((git_repo / e0.COUNTS).read_text("utf-8"))["blindness"]["rescanned"] is True
    trial = git_repo / "trial.json"
    assert run(git_repo, *counted, "--out", str(trial)) == 0
    capsys.readouterr()
    skipped = json.loads(trial.read_text("utf-8"))
    assert skipped["label_packets"] is None and skipped["blindness"] is None
    extractor = ["counts", "--method", "pattern-extractor"]
    agents = ["--agents", str(paths["agents"])]
    for argv, message in (
        (["counts", "--method", "blind-labels"], "--method blind-labels needs --labels DIR"),
        (
            [*counted, "--allow-dirty", "--out", str(trial)],
            "--allow-dirty applies only to --method pattern-extractor",
        ),
        ([*counted, *agents, "--out", str(trial)], "--agents needs --blindness"),
        (
            [*extractor, "--blindness", str(paths["blindness"])],
            "--labels, --packets, --blindness, and --agents apply only to --method blind-labels",
        ),
        (
            [*extractor, *agents],
            "--labels, --packets, --blindness, and --agents apply only to --method blind-labels",
        ),
        (
            [*extractor, "--allow-dirty", "--out", str(git_repo / e0.COUNTS)],
            "extractor counts never go to artifacts/e0/claim_type_counts.json",
        ),
    ):
        assert run(git_repo, *argv) == 2, argv
        assert message in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run(git_repo, "counts")


# ---------------------------------------------------------------- the G5 contract


def test_the_real_smoke_rows_are_the_rows_g5_and_g6_count() -> None:
    # The producer's copy of the gate's row filter; both must keep the same rows.
    assert e0.NON_AGENT_WORDS == ship_check.NON_AGENT_WORDS
    agents: list[object] = [
        SMOKE_AGENT,
        "claude-code/claude-sonnet",
        "",
        " ",
        "--",
        None,
        3,
        *(f"minimal-agent/{word}-7b" for word in sorted(ship_check.NON_AGENT_WORDS)),
        *(f"minimal-agent/{word.upper()}" for word in sorted(ship_check.NON_AGENT_WORDS)),
    ]
    flags: list[object] = [False, True, None, 0, "false"]
    ids: list[object] = ["r", " ", None]
    tasks: list[object] = ["t", "", 5]
    rows: list[dict[str, Any]] = []
    for n, (agent, flag, run_id, task_id) in enumerate(
        itertools.product(agents, flags, ids, tasks)
    ):
        row: dict[str, Any] = {"agent": agent, "synthetic": flag, "task_id": task_id}
        row["run_id"] = f"{run_id}{n}" if run_id == "r" else run_id
        rows.append(row)
    rows.append({"run_id": "no-flag", "task_id": "t", "agent": SMOKE_AGENT})
    kept = e0.real_smoke_rows({"runs": rows})
    assert kept == ship_check.real_smoke_runs({"runs": rows})
    # Two agent labels name agents; only synthetic: false with both ids present counts.
    assert [row["agent"] for row in kept] == [SMOKE_AGENT, "claude-code/claude-sonnet"]


def test_g5_recounts_the_blind_counts_this_tool_writes(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    """The G5 code of this working tree (ship_check.blind_top_types, with the real smoke
    runs from ship_check.verified_smoke_runs) accepts the counts artifact tools/e0.py
    writes and ranks the same five types, so the producer and the gate cannot drift."""
    paths = labeled(git_repo, commit, capsys)
    argv = [
        "counts",
        "--method",
        "blind-labels",
        "--labels",
        str(paths["labels"]),
        "--packets",
        str(paths["packets"]),
        "--blindness",
        str(paths["blindness"]),
    ]
    assert run(git_repo, *argv) == 0
    smoke = ship_check.load_json(git_repo, ship_check.SMOKE_RUNS)
    banked = {str(r.row["run_id"]): r for r in ship_check.verified_smoke_runs(git_repo, smoke)}
    produced = e0.real_smoke_runs(git_repo, paths["runs"])
    assert sorted(banked) == [r.run_id for r in produced] == ["r1", "r2", "r3", "r4", "r5"]
    reports = {run_id: banked_run.report for run_id, banked_run in banked.items()}
    assert reports == {r.run_id: r.banked_report for r in produced}
    counts = json.loads((git_repo / e0.COUNTS).read_text("utf-8"))
    assert ship_check.blind_top_types(git_repo, reports) == counts["top5"] == LABEL_TOP5
    # The gate is live on this artifact: a real run left unlabeled fails it.
    counts["labels"] = counts["labels"][:-1]
    e0.write_json(git_repo / e0.COUNTS, counts)
    with pytest.raises(ship_check.GateError, match="blind labels cover 4 of the 5"):
        ship_check.blind_top_types(git_repo, reports)


def gate_counts(items: list[dict[str, Any]], ctype: str) -> tuple[int, int, int]:
    """(correct, predicted, gold) exactly as tools/ship_check.py's g5 counts them today."""
    mine = [i for i in items if i.get("claim_type") == ctype]
    gold = [i for i in mine if i.get("gold_verdict") in VERDICTS]
    pred = [i for i in mine if i.get("pred_verdict") in VERDICTS]
    correct = sum(1 for i in gold if i.get("pred_verdict") == i.get("gold_verdict"))
    return correct, len(pred), len(gold)


def test_artifacts_carry_the_fields_of_the_plan_g5_row(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = (REPO / "docs" / "PLAN.md").read_text("utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| G5 |"))
    for named in (
        "`artifacts/e0/claim_type_counts.json` (`counts`, `source_runs`)",
        "`artifacts/e0/seeded_eval.json` (`split: heldout`, `heldout_manifest`, `items[]` with "
        "`report_id`, `claim_type`, `gold_verdict`, `pred_verdict`; `verifier_mode`, "
        "`reports`, `report_requirements`, `per_type`, `top5`, `passes`, `all_top5_pass`, "
        "`instrument` (`commit`, `paths`, `trees`, `dirty`, `uncommitted`), `attempt`, "
        "`attempts_log`)",
        "`artifacts/e0/heldout_attempts.jsonl` (one line per held-out scoring: `attempt`, "
        "`created`, `command`, `commit`, `trees`, `passes`, `all_top5_pass`, `per_type` with "
        "`correct`, `predicted`, `gold`)",
        "`artifacts/e0/heldout_manifest.json` (`reports: {id: sha256}`)",
        "`artifacts/e0/seeded/heldout/<id>.json`",
        "`artifacts/e0/ledger_completeness.json` (`runs_dirs`; `runs[]` with "
        "`transcript_commands`, `ledger_commands`, `missing`, `unparsed_actions`)",
        "the output of `tools/e0.py recheck` run in the clone after `make setup`",
    ):
        assert named in row
    paths = pipeline(git_repo, commit, capsys)
    commit(git_repo, "freeze")
    assert run(git_repo, "evaluate") == 0
    assert run(git_repo, "completeness", "--runs", str(paths["runs"])) == 0

    def load(rel: str) -> Any:
        return json.loads((git_repo / rel).read_text("utf-8"))

    counts, evaluation = load(e0.COUNTS), load(e0.EVAL)
    manifest, completeness = load(e0.MANIFEST), load(e0.COMPLETENESS)
    for artifact in (counts, evaluation, manifest, completeness):
        assert all(artifact["provenance"][key] for key in ("git_sha", "command", "created"))
    assert isinstance(counts["counts"], dict) and counts["source_runs"] == ["r1", "r2", "r3", "r4"]
    assert evaluation["split"] == "heldout" and evaluation["heldout_manifest"] == e0.MANIFEST
    assert all(
        {"report_id", "claim_type", "gold_verdict", "pred_verdict"} <= set(i)
        for i in evaluation["items"]
    )
    # What G5 re-derives with tools/e0.py recheck and compares with the attempt log (D66).
    assert set(e0.RECHECKED_FIELDS) <= set(evaluation)
    instrument = evaluation["instrument"]
    assert {"commit", "paths", "trees", "dirty", "uncommitted"} <= set(instrument)
    assert set(instrument["trees"]) == set(instrument["paths"])
    assert evaluation["attempt"] == 1 and evaluation["attempts_log"] == e0.ATTEMPTS
    (line,) = (git_repo / e0.ATTEMPTS).read_text("utf-8").splitlines()
    logged = json.loads(line)
    assert {
        "attempt",
        "created",
        "command",
        "commit",
        "trees",
        "passes",
        "all_top5_pass",
        "per_type",
    } <= set(logged)
    assert all(
        set(ship_check.ATTEMPT_COUNTS) <= set(counts) for counts in logged["per_type"].values()
    )
    for report_id, digest in manifest["reports"].items():
        assert e0.sha256_file(git_repo / e0.SEEDED / "heldout" / f"{report_id}.json") == digest
    fields = {"transcript_commands", "ledger_commands", "missing", "unparsed_actions"}
    assert all(fields <= set(r) for r in completeness["runs"])
    assert completeness["runs_dirs"]  # G5 re-derives the rows from these (D58)
    # The gate's counts equal per_type once ignored items are skipped (harness request).
    plain = [i for i in evaluation["items"] if not i["ignored"]]
    for name, entry in evaluation["per_type"].items():
        assert gate_counts(plain, name) == (entry["correct"], entry["predicted"], entry["gold"])
    _, predicted, _ = gate_counts(evaluation["items"], "file_modified")
    assert predicted == evaluation["per_type"]["file_modified"]["predicted"] + 1


# ---------------------------------------------------------------- the re-scoring (D66)


def evaluated(root: Path, commit: Commit, capsys: pytest.CaptureFixture[str]) -> str:
    """The command-line pipeline, a frozen held-out half, and one committed held-out
    attempt (``tools/e0.py evaluate``). Returns the commit that holds them."""
    pipeline(root, commit, capsys)
    commit(root, "freeze the held-out half")
    assert run(root, "evaluate") == 0
    capsys.readouterr()
    return commit(root, "the first held-out attempt")


def retype_first_prediction(root: Path) -> None:
    """Hand-edit the first prediction of the committed evaluation (SYNTHETIC tampering)."""
    data = json.loads((root / e0.EVAL).read_text("utf-8"))
    item = next(i for i in data["items"] if i["pred_verdict"])
    item["pred_verdict"] = "contradicted" if item["pred_verdict"] == "supported" else "supported"
    e0.write_json(root / e0.EVAL, data)


def test_recheck_through_the_command_line(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline(git_repo, commit, capsys)
    assert run(git_repo, "recheck") == 2
    assert capsys.readouterr().err == f"e0 recheck: {e0.EVAL}: file not found\n"
    commit(git_repo, "freeze the held-out half")
    assert run(git_repo, "evaluate") == 0
    commit(git_repo, "the first held-out attempt")
    capsys.readouterr()
    before = {rel: (git_repo / rel).read_bytes() for rel in (e0.EVAL, e0.ATTEMPTS)}
    assert run(git_repo, "recheck") == 0
    assert capsys.readouterr().out == (
        f"recheck: {e0.EVAL} (attempt 1) is what its 2 held-out reports score now; "
        "nothing written, no attempt logged\n"
    )
    assert {rel: (git_repo / rel).read_bytes() for rel in before} == before
    # A difference exits 1 and names it on stderr, where gate G5 reads it.
    retype_first_prediction(git_repo)
    assert run(git_repo, "recheck") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(
        f"e0 recheck: {e0.EVAL} differs from a new scoring of the held-out reports in items; "
        "first differing item: items[0] (report rep-3, "
    )
    assert captured.err.count("\n") == 1
    # A refusal exits 2.
    (git_repo / "src/receipts/claims").mkdir(parents=True)
    (git_repo / "src/receipts/claims/wip.py").write_text("x = 1\n", "utf-8")
    assert run(git_repo, "recheck") == 2
    assert "the instrument has uncommitted changes" in capsys.readouterr().err


class CliContext(ship_check.Context):
    """A gate Context on a SYNTHETIC repository: ``make`` succeeds, and a repository script
    is this working tree's ``tools/e0.py``, run in process on the repository ``clone``."""

    def make(self, target: str, timeout: float, *args: str, **kw: Any) -> ship_check.CmdResult:
        return ship_check.CmdResult(f"make-{target}", 0, "", "", 0.0)

    def python(self, name: str, script_args: Sequence[str], timeout: float) -> ship_check.CmdResult:
        assert script_args[0] == "tools/e0.py"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(script_args[1:]), root=self.clone)
        return ship_check.CmdResult(name, code, out.getvalue(), err.getvalue(), 0.0)


def cli_context(root: Path, sha: str) -> CliContext:
    """A fresh :class:`CliContext` (its results cache empty) on ``root`` at ``sha``."""
    return CliContext(orig=root, clone=root, logs=root, fast=True, sha=sha)


def retype_per_type(root: Path) -> None:
    """Hand-edit a per-type count of the committed evaluation (SYNTHETIC tampering): one
    fewer correct file_modified claim, its pass left as it was."""
    data = json.loads((root / e0.EVAL).read_text("utf-8"))
    data["per_type"]["file_modified"]["correct"] -= 1
    e0.write_json(root / e0.EVAL, data)


def edit_requirement(root: Path) -> None:
    """Edit a requirement text of the task the held-out reports' ledgers name, after the
    scoring (SYNTHETIC task files): the digests the evaluation recorded (D54) go stale."""
    task = root / "bench" / "tasks" / "py-alpha" / "task.toml"
    text = task.read_text("utf-8")
    assert REQUIREMENTS["R2"] in text
    task.write_text(text.replace(REQUIREMENTS["R2"], "The parser rejects bad rows fast."), "utf-8")


@pytest.mark.parametrize(
    ("tamper", "named"),
    [
        pytest.param(
            retype_first_prediction,
            r"in items; first differing item: items\[0\] \(report rep-3, \w+\): pred_verdict ",
            id="typed-prediction",
        ),
        pytest.param(retype_per_type, r"in per_type \(file_modified\)$", id="typed-per-type"),
        pytest.param(
            edit_requirement, r"in report_requirements \(rep-3, rep-9\)", id="edited-requirement"
        ),
    ],
)
def test_g5_reruns_the_scoring_this_tool_records(
    git_repo: Path,
    commit: Commit,
    capsys: pytest.CaptureFixture[str],
    tamper: Callable[[Path], None],
    named: str,
) -> None:
    """The G5 code of this working tree (ship_check.rescored_heldout) runs ``tools/e0.py
    recheck`` on the evaluation this tool writes, with the real extractor and verifier: it
    passes, and a prediction or a per-type count typed into the file, or a requirement
    text edited after the scoring, fails with the tool's reason, so the producer and the
    gate cannot drift (review B6, D66)."""
    sha = evaluated(git_repo, commit, capsys)
    ship_check.rescored_heldout(cli_context(git_repo, sha))
    tamper(git_repo)
    sha = commit(git_repo, "change the evaluation or its inputs after the held-out scoring")
    with pytest.raises(
        ship_check.GateError,
        match=r"^the held-out scoring was not reproduced in the clone \(tools/e0\.py recheck, "
        r"exit 1\): e0 recheck: artifacts/e0/seeded_eval\.json differs from a new scoring of "
        r"the held-out reports " + named,
    ):
        ship_check.rescored_heldout(cli_context(git_repo, sha))


def edit_source(root: Path, rel: str) -> None:
    """Append a SYNTHETIC comment to the source file ``rel`` of the world ``root``, copied
    from this repository first when the world lacks it."""
    path = root / rel
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REPO / rel).read_bytes())
    edited = path.read_text("utf-8") + "# SYNTHETIC edit after a held-out attempt\n"
    path.write_text(edited, "utf-8")


def test_g5_reads_the_attempt_log_this_tool_writes(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    """ship_check.heldout_attempt reads the log that ``tools/e0.py evaluate`` appends to
    (receipts.evaluation.e0.log_attempt): a re-score on the same instrument is the next
    attempt, also after an edit to code that sits beside the instrument in the logged
    directories but that the scoring never loads (DECISIONS D36; review B6, FR1), and one
    after the instrument changed fails (D66). The world commits this repository's
    instrument files (gate G5's import closure), so each logged commit holds the
    instrument; the scoring runs this working tree's package."""
    for rel in ship_check.instrument_files(REPO):
        (git_repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (git_repo / rel).write_bytes((REPO / rel).read_bytes())
    evaluated(git_repo, commit, capsys)

    def evaluation() -> dict[str, Any]:
        return dict(json.loads((git_repo / e0.EVAL).read_text("utf-8")))

    assert ship_check.heldout_attempt(git_repo, evaluation()) == 1
    assert run(git_repo, "evaluate") == 0
    commit(git_repo, "the held-out half scored again, same instrument")
    assert ship_check.heldout_attempt(git_repo, evaluation()) == 2
    # Old code: FAIL, since the logged trees of src/receipts/evaluation and
    # src/receipts/bench changed.
    for rel in ("src/receipts/evaluation/e3.py", "src/receipts/bench/validate.py"):
        assert rel not in ship_check.instrument_files(git_repo)
        edit_source(git_repo, rel)
    commit(git_repo, "E3 and benchmark changes after the held-out scoring")
    assert run(git_repo, "evaluate") == 0
    commit(git_repo, "the held-out half scored again, same instrument")
    assert ship_check.heldout_attempt(git_repo, evaluation()) == 3
    edit_source(git_repo, "src/receipts/claims/patterns.py")
    commit(git_repo, "revise the extractor")
    assert run(git_repo, "evaluate") == 0
    commit(git_repo, "the held-out half scored after the revision")
    capsys.readouterr()
    with pytest.raises(
        ship_check.GateError,
        match=r"^attempt 1 of artifacts/e0/heldout_attempts\.jsonl scored another instrument "
        r"than attempt 4 \(changed: src/receipts/claims/patterns\.py\): the held-out half was "
        r"scored again after the instrument changed",
    ):
        ship_check.heldout_attempt(git_repo, evaluation())


# ---------------------------------------------------------------- blindness of the checks


def imported_modules(
    argv: list[str], cwd: Path
) -> tuple[subprocess.CompletedProcess[str], set[str]]:
    """Run ``python -X importtime tools/e0.py <argv>`` and return the modules it imported."""
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", str(REPO / "tools" / "e0.py"), *argv],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )
    modules = {
        line.rsplit("|", 1)[1].strip()
        for line in proc.stderr.splitlines()
        if line.startswith("import time:") and "|" in line
    }
    return proc, modules


def test_writer_adjudicator_and_labeler_checks_never_load_the_instrument(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = pipeline(git_repo, commit, capsys)
    raws = sorted(map(str, paths["raw"].glob("*.json")))
    adjs = sorted(map(str, paths["adj"].glob("*.json")))
    labels = sorted(map(str, paths["labels"].glob("*.json")))
    for argv in (
        ["check-raw", "--packets", str(paths["packets"]), *raws],
        ["check-adjudication", "--packets", str(paths["adj_packets"]), *adjs],
        ["check-labels", "--packets", str(paths["label_packets"]), *labels],
    ):
        proc, modules = imported_modules(argv, git_repo)
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert proc.stdout.endswith("file(s), no problems\n")
        assert "receipts.evaluation.e0" in modules
        assert not [m for m in modules if m.startswith(INSTRUMENT_MODULES)]


def test_the_import_check_sees_the_instrument_when_it_is_loaded(tmp_path: Path) -> None:
    runs = make_world(tmp_path)
    out = tmp_path / "counts.json"
    argv = ["counts", "--method", "pattern-extractor", "--runs", str(runs), "--allow-dirty"]
    proc, modules = imported_modules([*argv, "--out", str(out)], tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "receipts.claims.extract" in modules and out.is_file()
