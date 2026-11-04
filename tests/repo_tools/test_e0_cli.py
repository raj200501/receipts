"""Tests for tools/e0.py, the E0 command line (gate G5).

Every run, report, writer output, adjudication, and transcript here is SYNTHETIC, built
by the helpers of tests/evaluation/test_e0.py under tmp_path; no number here is a result.
The blindness tests run the writer and adjudicator commands in a subprocess and check
that neither receipts.claims nor receipts.verify is ever imported.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import e0 as cli
from receipts.evaluation import e0
from receipts.evaluation.seeded import VERDICTS
from tests.evaluation.test_e0 import (
    make_world,
    raw_output,
    tool_use_line,
    write_agent,
    write_outputs,
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
    agents = write_transcripts(root / "agents")
    assert run(root, "counts", "--runs", str(runs)) == 0
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
        )
        == 0
    )
    assert run(root, "split", "--packets", str(packets)) == 0
    capsys.readouterr()
    return {
        "runs": runs,
        "packets": packets,
        "adj_packets": adj_packets,
        "raw": raw_dir,
        "adj": adj_dir,
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
    assert run(git_repo, "counts", "--runs", str(runs), "--out", str(git_repo / "c.json")) == 0
    assert capsys.readouterr().out == (
        "wrote c.json: 4 reports; top five: file_modified, ran_command, tests_pass, "
        "bug_fixed, task_complete\n"
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
        "anon.jsonl: 1 line(s) that are not JSON objects; merge refuses until it is scanned "
        "in full",
        "anon.jsonl: voids but declares no writer or adjudicator id; merge refuses",
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
    with pytest.raises(SystemExit):
        run(git_repo, "evaluate", "--split", "all")


def test_counts_and_completeness_default_to_the_smoke_runs(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    make_world(git_repo)
    commit(git_repo, "world")
    assert run(git_repo, "counts") == 0
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


# ---------------------------------------------------------------- the G5 contract


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
        "`report_id`, `claim_type`, `gold_verdict`, `pred_verdict`)",
        "`artifacts/e0/heldout_manifest.json` (`reports: {id: sha256}`)",
        "`artifacts/e0/seeded/heldout/<id>.json`",
        "`artifacts/e0/ledger_completeness.json` (`runs[]` with `transcript_commands`, "
        "`ledger_commands`)",
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
    for report_id, digest in manifest["reports"].items():
        assert e0.sha256_file(git_repo / e0.SEEDED / "heldout" / f"{report_id}.json") == digest
    assert all({"transcript_commands", "ledger_commands"} <= set(r) for r in completeness["runs"])
    # The gate's counts equal per_type once ignored items are skipped (harness request).
    plain = [i for i in evaluation["items"] if not i["ignored"]]
    for name, entry in evaluation["per_type"].items():
        assert gate_counts(plain, name) == (entry["correct"], entry["predicted"], entry["gold"])
    _, predicted, _ = gate_counts(evaluation["items"], "file_modified")
    assert predicted == evaluation["per_type"]["file_modified"]["predicted"] + 1


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


def test_writer_and_adjudicator_checks_never_load_the_instrument(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = pipeline(git_repo, commit, capsys)
    raws = sorted(map(str, paths["raw"].glob("*.json")))
    adjs = sorted(map(str, paths["adj"].glob("*.json")))
    for argv in (
        ["check-raw", "--packets", str(paths["packets"]), *raws],
        ["check-adjudication", "--packets", str(paths["adj_packets"]), *adjs],
    ):
        proc, modules = imported_modules(argv, git_repo)
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert proc.stdout.endswith("file(s), no problems\n")
        assert "receipts.evaluation.e0" in modules
        assert not [m for m in modules if m.startswith(INSTRUMENT_MODULES)]


def test_the_import_check_sees_the_instrument_when_it_is_loaded(tmp_path: Path) -> None:
    runs = make_world(tmp_path)
    out = tmp_path / "counts.json"
    proc, modules = imported_modules(
        ["counts", "--runs", str(runs), "--allow-dirty", "--out", str(out)], tmp_path
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "receipts.claims.extract" in modules and out.is_file()
