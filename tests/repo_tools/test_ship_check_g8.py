"""Gate G8 of tools/ship_check.py on synthetic E2 and E3 artifacts (H27, H30).

Every run row, mechanism class, judge count, and report here is SYNTHETIC, made up only
to exercise ``ship_check.g8``; nothing here is a model result or a real-world result.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import ship_check

GateError = ship_check.GateError
PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
CLASSES = sorted(ship_check.MECHANISM_CLASSES)
REPORT = """\
# Report (SYNTHETIC)

## E2: mechanisms of contradicted claims

The SYNTHETIC mechanism mix is reported here, including null results.

## E3: judge validity

The SYNTHETIC judge precision and recall are reported here.
"""


def put(root: Path, rel: str, data: Any) -> None:
    """Write text, or JSON, creating parent directories."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2) + "\n", "utf-8")


def judge(judge_id: str, tp: object = 3, fp: object = 1, fn: object = 0) -> dict[str, Any]:
    """A SYNTHETIC E3 judge entry."""
    return {"judge_id": judge_id, "per_type": {"tests_pass": {"tp": tp, "fp": fp, "fn": fn}}}


def artifacts(
    root: Path,
    *,
    judges: list[dict[str, Any]] | None = None,
    report: str = REPORT,
    mechanism: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> ship_check.Context:
    """SYNTHETIC E1 rows with contradicted claims, their E2 classes, two judges, a report."""
    rows = []
    claims = []
    for n in range(6):
        verdict = "contradicted" if n % 2 == 0 else "supported"
        rows.append(
            {
                "run_id": f"e1-{n:03d}",
                "included": True,
                "claims": [{"claim_id": "c0", "claim_type": "tests_pass", "verdict": verdict}],
            }
        )
        if verdict == "contradicted":
            claims.append({"run_id": f"e1-{n:03d}", "claim_id": "c0", "class": CLASSES[n % 3]})
    put(root, "artifacts/e1/runs.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
    rows_e2 = claims if mechanism is None else mechanism(claims)
    put(root, "artifacts/e2/mechanism.json", {"claims": rows_e2, "provenance": PROV})
    chosen = [judge("judge-a"), judge("judge-b")] if judges is None else judges
    put(root, "artifacts/e3/judges.json", {"judges": chosen, "provenance": PROV})
    put(root, "docs/REPORT.md", report)
    return ship_check.Context(orig=root, clone=root, logs=root, fast=False, sha="0" * 40)


def test_e2_and_e3_reported_pass(tmp_path: Path) -> None:
    evidence = ship_check.g8(artifacts(tmp_path))
    assert "E2 classified 3 claims" in evidence and "E3 2 judges" in evidence


# ---------------------------------------------------------------- H27 (old code: PASS)


@pytest.mark.parametrize(
    "judges",
    [
        pytest.param([judge("judge-a"), judge("judge-a")], id="same-judge-twice"),
        pytest.param([judge("judge-a", 0, 0, 0), judge("judge-b", 0, 0, 0)], id="all-zero"),
        pytest.param([judge("judge-a", True, False, False), judge("judge-b")], id="booleans"),
        pytest.param([judge("judge-a", -3, 1, 0), judge("judge-b")], id="negative"),
        pytest.param([judge("judge-a", 2.5, 1, 0), judge("judge-b")], id="fraction"),
        pytest.param([judge(""), judge("judge-b")], id="no-id"),
    ],
)
def test_degenerate_judge_results_fail(tmp_path: Path, judges: list[dict[str, Any]]) -> None:
    with pytest.raises(GateError, match="judge"):
        ship_check.g8(artifacts(tmp_path, judges=judges))


def test_a_judge_with_only_true_negatives_is_a_reported_null_result(tmp_path: Path) -> None:
    quiet = judge("judge-b", 0, 0, 0)
    quiet["per_type"]["tests_pass"]["tn"] = 5
    assert "E3 2 judges" in ship_check.g8(artifacts(tmp_path, judges=[judge("judge-a"), quiet]))


# ---------------------------------------------------------------- H30 (old code: PASS)


def test_a_claim_classified_twice_fails(tmp_path: Path) -> None:
    def twice(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        other = [dict(c, **{"class": CLASSES[(CLASSES.index(c["class"]) + 1) % 3]}) for c in claims]
        return claims + other

    with pytest.raises(GateError, match="more than once"):
        ship_check.g8(artifacts(tmp_path, mechanism=twice))


@pytest.mark.parametrize(
    "report",
    [
        pytest.param(
            "## Results\n\n```bash\n# e2 and e3 are not run yet\n# judges: todo\n```\n",
            id="comments-in-code",
        ),
        pytest.param(
            "## Free2 notes\n\nSynthetic text.\n\n## Judgement calls\n\nSynthetic text.\n",
            id="substring-headings",
        ),
        pytest.param("## E2\n\n## E3\n\n<!-- todo -->\n", id="empty-sections"),
        pytest.param("## E2 mechanisms\n\nText.\n\n```\n## E3 judges\n```\n", id="e3-in-code"),
    ],
)
def test_report_sections_must_exist_and_say_something(tmp_path: Path, report: str) -> None:
    with pytest.raises(GateError, match=r"REPORT\.md has no E[23] section"):
        ship_check.g8(artifacts(tmp_path, report=report))
