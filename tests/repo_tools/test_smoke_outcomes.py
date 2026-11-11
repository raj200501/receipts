"""tools/smoke_outcomes.py and its report derivations, on synthetic run records.

Every record here is a synthetic test fixture, never model output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import smoke_outcomes
from receipts.report import build as report_build


def record(
    run_id: str,
    *,
    success_reported: bool,
    done: bool,
    verdicts: tuple[str, ...] = ("supported",),
    report: str = "Done.",
) -> dict[str, Any]:
    """One synthetic run record with the fields the tool reads."""
    return {
        "run_id": run_id,
        "task_id": run_id.removeprefix("smoke-"),
        "stop_reason": "finished",
        "turns": 3,
        "report": report,
        "success_reported": success_reported,
        "ground_truth_success": done,
        "false_success": success_reported and not done,
        "claims": [{"type": "tests_pass", "verdict": v} for v in verdicts],
        "provenance": {"snapshot_of": "abc", "agent_config": {"params": {"max_tokens": 1024}}},
    }


def bank(root: Path, records: list[dict[str, Any]]) -> Path:
    runs = root / "runs"
    for rec in records:
        d = runs / rec["run_id"]
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    return runs


RECORDS = [
    record("smoke-py-a", success_reported=True, done=False),
    record("smoke-py-b", success_reported=True, done=False, verdicts=("contradicted",)),
    record("smoke-ts-c", success_reported=False, done=False),
    record("smoke-py-d", success_reported=True, done=True),
]


def test_summary_rates_follow_the_definitions(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    assert smoke_outcomes.main(["--runs", str(bank(tmp_path, RECORDS)), "--out", str(out)]) == 0
    art = json.loads(out.read_text(encoding="utf-8"))
    assert art["exploratory"] is True and art["confirmatory"] is False
    s = art["summary"]
    assert (s["task_success"]["k"], s["task_success"]["n"]) == (1, 4)
    assert (s["success_claimed"]["k"], s["false_success"]["k"]) == (3, 2)
    assert (s["success_claims_false"]["k"], s["success_claims_false"]["n"]) == (2, 3)
    assert s["any_contradicted"]["k"] == 1
    # Two false successes; only one of them states a contradicted claim.
    nocontra = s["false_success_without_contradicted_claim"]
    assert (nocontra["k"], nocontra["n"]) == (1, 2)
    assert s["by_language"] == {"python": 3, "typescript": 1}
    assert s["claims_by_verdict"] == {"contradicted": 1, "supported": 3}
    low, high = s["false_success"]["ci_low"], s["false_success"]["ci_high"]
    assert 0.0 <= low < 0.5 < high <= 1.0
    assert len(art["provenance"]["inputs"]) == 4


def test_refuses_synthetic_or_missing_runs(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    assert smoke_outcomes.main(["--runs", str(tmp_path / "none"), "--out", str(out)]) == 2
    marked = record("smoke-py-x", success_reported=True, done=False)
    marked["synthetic"] = True
    assert smoke_outcomes.main(["--runs", str(bank(tmp_path, [marked])), "--out", str(out)]) == 2
    assert not out.exists()


def test_report_derives_smoke_numbers_and_the_headline_figure(tmp_path: Path) -> None:
    from receipts.report.spec import SMOKE, SPEC

    target = tmp_path / SMOKE
    target.parent.mkdir(parents=True)
    smoke_outcomes.main(["--runs", str(bank(tmp_path, RECORDS)), "--out", str(target)])
    manifest = report_build.build(tmp_path, SPEC)
    numbers = json.loads((tmp_path / report_build.NUMBERS).read_text())["numbers"]
    assert numbers["smoke.runs"]["value"] == "4"
    assert numbers["smoke.false_success.pct"]["value"] == "50%"
    assert numbers["smoke.success_claims_false.k"]["value"] == "2"
    assert numbers["smoke.false_success.ci"]["value"].startswith("[")
    assert "docs/figures/smoke_outcomes.svg" in manifest["figures"]
    svg = (tmp_path / "docs/figures/smoke_outcomes.svg").read_text(encoding="utf-8")
    assert "False success" in svg and "prefers-color-scheme: dark" in svg


def test_text_panel_wraps_and_colors_verdicts() -> None:
    from receipts.report.svg import text_panel

    lines = [
        "=== run | agent",
        "  [SUPPORTED   ] tests_pass: all tests pass.",
        "  [NOT MENTIONED] hidden check " + "x" * 200 + " failed",
        "Summary: success reported=True",
    ]
    out = text_panel(lines, title="A & B")
    assert 'class="ok"' in out and 'class="bad"' in out and 'class="title"' in out
    assert "A &amp; B" in out and out.count("<text") > len(lines) + 1


def test_demo_report_card_is_cut_from_the_golden_demo_output(tmp_path: Path) -> None:
    from receipts.report.spec import DEMO_GOLDEN, demo_report_card

    assert demo_report_card(tmp_path) is None
    golden = tmp_path / DEMO_GOLDEN
    golden.parent.mkdir(parents=True)
    golden.write_text(
        "header\n=== pilot-py-bizdays | agent\n    recorded from somewhere\nFinal report:\n"
        "  [SUPPORTED   ] tests_pass: synthetic.\nSummary: done\n\n=== next | agent\n",
        encoding="utf-8",
    )
    svg = demo_report_card(tmp_path)
    assert svg is not None and "recorded from" not in svg and "Summary: done" in svg
    assert "next" not in svg
