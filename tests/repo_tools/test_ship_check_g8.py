"""Gate G8 of tools/ship_check.py on synthetic E2 and E3 artifacts (H27, H30, the
pre-freeze item [24]: E3 judged its whole recorded sample, and review B5 of the 02bc774
review: each judge's counts are the tally of its labels, and both artifacts are what
their scripts write, DECISIONS D65).

Every run row, mechanism class, judge label, sample, call, and report here is SYNTHETIC,
made up only to exercise ``ship_check.g8``; nothing here is a model result or a
real-world result. The E3 sample is drawn by the real ``receipts.evaluation.e3``
sampler, so the gate's recount must agree with it, and each judge's counts are tallied
from its SYNTHETIC labels by the real ``receipts.evaluation.judges.score_detection``.
The E2 classes have no ledger behind them, so the re-derivation of both artifacts
(``python -m receipts.report.derived`` in the clone) is given its outcome
(:func:`artifacts`), except in the tests that run it on the SYNTHETIC studies of
tests/report/studies.py, whose artifacts the real tools wrote.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.evaluation.e3 import draw_sample
from receipts.evaluation.judges import score_detection
from tests.repo_tools.test_ship_check_g7 import derived_fails, derived_ok, given, run_for_real

GateError = ship_check.GateError
PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
CLASSES = sorted(ship_check.MECHANISM_CLASSES)
ARMS = ("ma-qwen7b", "ma-qwen1.5b", "ma-granite8b", "ma-granite2b")
FAMILY = {"ma-qwen7b": "qwen", "ma-qwen1.5b": "qwen", "ma-granite8b": "granite"}
JUDGES = ("judge-a", "judge-b")
RUNS = "artifacts/e1/runs.jsonl"
E2 = "artifacts/e2/mechanism.json"
E3 = "artifacts/e3/judges.json"
K, SEED = 8, 20261108  # two runs from each of the four SYNTHETIC arms
REPORT = """\
# Report (SYNTHETIC)

## E2: mechanisms of contradicted claims

The SYNTHETIC mechanism mix is reported here, including null results:
<!--n:e2.confusion-->5<!--/n--> claims from confusion.

## E3: judge validity

The SYNTHETIC judge precision is <!--n:e3.judge-a.precision-->0.75<!--/n--> for judge-a
and <!--n:e3.judge-b.precision-->0.75<!--/n--> for judge-b.
"""
# The SYNTHETIC registry entries the report's markers are bound to.
SOURCES = {
    "e2.confusion": "artifacts/e2/mechanism.json",
    "e3.judge-a.precision": "artifacts/e3/judges.json",
    "e3.judge-b.precision": "artifacts/e3/judges.json",
    "e1.rate": "artifacts/e1/results.json",
}

Edit = Callable[[dict[str, Any]], None]


def put(root: Path, rel: str, data: Any) -> None:
    """Write text, or JSON, creating parent directories."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2) + "\n", "utf-8")


def judge(judge_id: str, tp: object = 1, fp: object = 0, fn: object = 0) -> dict[str, Any]:
    """A SYNTHETIC E3 judge entry with the given counts, for the degenerate results the
    gate refuses before it tallies any label."""
    return {"judge_id": judge_id, "per_type": {"tests_pass": {"tp": tp, "fp": fp, "fn": fn}}}


#: How each SYNTHETIC judge labels a scored claim, given its ledger verdict: judge-a flags
#: exactly the contradicted claims, and judge-b labels every claim supported (it flags
#: nothing: a null result).
LABELS: dict[str, Callable[[str], str]] = {
    "judge-a": lambda truth: truth,
    "judge-b": lambda truth: "supported",
}


def judge_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each judge's entry as receipts.evaluation.e3 writes it from the scored items: its
    per-type counts tallied from its labels (``score_detection``)."""
    return [
        {
            "judge_id": j,
            "per_type": {
                ctype: counts.to_dict()
                for ctype, counts in score_detection(
                    (i["claim_type"], i["truth"], i["labels"].get(j)) for i in items
                ).items()
            },
        }
        for j in JUDGES
    ]


def contradicted_every_other(n: int) -> str:
    """The SYNTHETIC verdict of run ``n`` of an arm: contradicted in every other run."""
    return "contradicted" if n % 2 == 0 else "supported"


def e1_rows(verdict: Callable[[int], str] = contradicted_every_other) -> list[dict[str, Any]]:
    """SYNTHETIC E1 rows: five runs per arm, the last of each without a report, every
    report with one claim (its verdict ``verdict(n)``)."""
    rows = []
    for arm in ARMS:
        for n in range(5):
            included = n < 4
            rows.append(
                {
                    "run_id": f"e1-{arm}-{n:03d}",
                    "config_id": arm,
                    "task_id": f"task{n:02d}",
                    "model_family": FAMILY.get(arm, "granite"),
                    "included": included,
                    "synthetic": False,
                    "instrument": {"trees": {}},
                    "instrument_dirty": False,
                    "claims": [
                        {
                            "claim_id": "c0",
                            "claim_type": "tests_pass",
                            "text": "all tests pass",
                            "verdict": verdict(n),
                        }
                    ]
                    if included
                    else [],
                }
            )
    return rows


def judges_artifact(rows: list[dict[str, Any]], runs_sha: str) -> dict[str, Any]:
    """A SYNTHETIC artifacts/e3/judges.json in the shape receipts.evaluation.e3 writes:
    the sample of K runs, every sampled run judged by both judges."""
    sample = draw_sample(rows, K, SEED).as_dict()
    by_id = {str(r["run_id"]): r for r in rows}
    judged = sample["sampled_run_ids"]
    items = [
        {
            "run_id": run_id,
            "task_id": by_id[run_id]["task_id"],
            "config_id": by_id[run_id]["config_id"],
            "claim_id": claim["claim_id"],
            "claim_type": claim["claim_type"],
            "truth": claim["verdict"],
            "labels": {j: LABELS[j](claim["verdict"]) for j in JUDGES},
        }
        for run_id in judged
        for claim in by_id[run_id]["claims"]
    ]
    calls = [
        {"judge_id": j, "run_id": run_id, "status": "ok", "served": True, "cache_key": "SYN"}
        for j in JUDGES
        for run_id in judged
    ]
    return {
        "schema": "receipts.e3.judges/2",
        "confirmatory": False,
        "sample": {**sample, "preregistered": True},
        "runs": {
            "sampled": len(judged),
            "judged": len(judged),
            "excluded": [],
            "limit": None,
            "judges": list(JUDGES),
            "complete": True,
        },
        "judges": judge_entries(items),
        "items": items,
        "calls": calls,
        "provenance": {**PROV, "inputs": {RUNS: runs_sha}},
    }


def artifacts(
    root: Path,
    *,
    judges: list[dict[str, Any]] | None = None,
    report: str = REPORT,
    mechanism: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    e3: Edit | None = None,
    verdict: Callable[[int], str] = contradicted_every_other,
) -> ship_check.Context:
    """SYNTHETIC E1 rows with contradicted claims (``verdict``), their E2 classes, an E3
    artifact of two judges over the sample (``e3`` edits it), and a report. The clone
    holds no project for ``make setup`` and the re-derivations to run in, so their
    outcomes are given (each artifact equals a fresh derivation); a test replaces them in
    ``ctx.results``."""
    rows = e1_rows(verdict)
    put(root, RUNS, "".join(json.dumps(r) + "\n" for r in rows))
    claims = [
        {"run_id": r["run_id"], "claim_id": "c0", "class": CLASSES[n % 3]}
        for n, r in enumerate(rows)
        if r["included"] and r["claims"][0]["verdict"] == "contradicted"
    ]
    rows_e2 = claims if mechanism is None else mechanism(claims)
    put(root, "artifacts/e2/mechanism.json", {"claims": rows_e2, "provenance": PROV})
    runs_sha = hashlib.sha256((root / RUNS).read_bytes()).hexdigest()
    data = judges_artifact(rows, runs_sha)
    if judges is not None:
        data["judges"] = judges
    if e3 is not None:
        e3(data)
    put(root, "artifacts/e3/judges.json", data)
    put(root, "docs/REPORT.md", report)
    numbers = {key: {"value": "0", "source": src} for key, src in SOURCES.items()}
    put(root, "artifacts/report/numbers.json", {"numbers": numbers})
    ctx = ship_check.Context(orig=root, clone=root, logs=root, fast=False, sha="0" * 40)
    ctx.results["make-setup"] = given("make-setup")
    ctx.results[f"derived-{E2}"] = derived_ok(E2, "python tools/analyze.py e2")
    ctx.results[f"derived-{E3}"] = derived_ok(E3, "python tools/run_judges.py --rescore")
    return ctx


def test_e2_and_e3_reported_pass(tmp_path: Path) -> None:
    evidence = ship_check.g8(artifacts(tmp_path))
    assert "E2 classified 8 claims" in evidence and "E3 2 judges" in evidence
    assert "sample of 8 runs, 8 judged by every judge, 0 excluded" in evidence
    assert f"{E2} re-derived by tools/analyze.py e2" in evidence
    assert f"{E3} re-derived by tools/run_judges.py --rescore from the banked replies" in evidence


def test_the_gate_draws_the_sample_the_e3_sampler_draws() -> None:
    # The row order of runs.jsonl must not matter: both sort each arm's run ids.
    rows = e1_rows()
    shuffled = list(rows)
    random.Random(5).shuffle(shuffled)
    for k, seed in ((4, 1), (8, SEED), (12, 7), (40, 3)):
        expected = list(draw_sample(rows, k, seed).run_ids)
        assert ship_check.e3_sample(rows, k, seed) == expected
        assert ship_check.e3_sample(shuffled, k, seed) == expected


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
    # Every SYNTHETIC claim is supported, so each judge's counts are true negatives only.
    ctx = artifacts(tmp_path, verdict=lambda n: "supported")
    judges = json.loads((tmp_path / E3).read_text(encoding="utf-8"))["judges"]
    assert {j["judge_id"]: j["per_type"]["tests_pass"] for j in judges} == {
        "judge-a": {"tp": 0, "fp": 0, "fn": 0, "tn": 8},
        "judge-b": {"tp": 0, "fp": 0, "fn": 0, "tn": 8},
    }
    assert "E2 classified 0 claims" in ship_check.g8(ctx)


def test_the_fixture_judges_flag_and_miss_as_their_labels_say(tmp_path: Path) -> None:
    ship_check.g8(artifacts(tmp_path))
    judges = json.loads((tmp_path / E3).read_text(encoding="utf-8"))["judges"]
    counts = {j["judge_id"]: j["per_type"]["tests_pass"] for j in judges}
    contradicted = counts["judge-a"]["tp"]
    assert contradicted > 0 and counts["judge-a"]["fp"] == counts["judge-a"]["fn"] == 0
    assert counts["judge-b"] == {"tp": 0, "fp": 0, "fn": contradicted, "tn": 8 - contradicted}


# ---------------------------------------------------------------- the counts (review B5)


def typed_counts(**counts: int) -> Edit:
    """Type ``counts`` into every judge's ``tests_pass`` counts, as a hand edit would."""

    def apply(data: dict[str, Any]) -> None:
        for entry in data["judges"]:
            entry["per_type"]["tests_pass"].update(counts)

    return apply


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        pytest.param(typed_counts(tp=999), "judge judge-a's per-type counts", id="tp-999"),
        pytest.param(typed_counts(fp=1), "judge judge-a's per-type counts", id="a-false-positive"),
        pytest.param(
            lambda d: d["judges"][1]["per_type"]["tests_pass"].update(fn=0, tn=8),
            "judge judge-b's per-type counts .* tests_pass",
            id="misses-moved-to-true-negatives",
        ),
        pytest.param(
            lambda d: d["judges"][0]["per_type"]["tests_pass"].pop("tn"),
            "judge judge-a's per-type counts",
            id="no-true-negatives",
        ),
        pytest.param(
            lambda d: d["judges"][1]["per_type"].update(
                file_modified={"tp": 0, "fp": 0, "fn": 0, "tn": 1}
            ),
            "judge judge-b's per-type counts .* file_modified",
            id="a-type-no-item-has",
        ),
    ],
)
def test_counts_that_the_labels_do_not_give_fail(tmp_path: Path, edit: Edit, match: str) -> None:
    # The review's probe typed tp=999 for both judges: a count is the tally of the
    # artifact's own items, contradicted the positive class, before any re-derivation.
    with pytest.raises(GateError, match=match):
        ship_check.g8(artifacts(tmp_path, e3=edit))


@pytest.mark.parametrize(
    ("rel", "outcome", "match"),
    [
        pytest.param(
            E2,
            derived_fails(E2, "claims.0.class, claims.3.class", "tools/analyze.py"),
            rf"{E2} is not a fresh derivation in the clone .*\(claims\.0\.class, claims\.3",
            id="hand-set-e2-classes",
        ),
        pytest.param(
            E3,
            derived_fails(E3, "judges.0.per_type.tests_pass.precision", "tools/run_judges.py"),
            rf"{E3} is not a fresh derivation .*judges\.0\.per_type\.tests_pass\.precision",
            id="a-hand-set-e3-score",
        ),
        pytest.param(
            E3,
            given(
                f"derived-{E3}",
                1,
                stdout=f"problem: {E3}: tools/run_judges.py failed: E3: artifacts/e3/replies"
                ".jsonl has no banked reply of judge judge-a to request SYNTHETIC; a re-score "
                "never calls a model\nDERIVED: FAIL 1\n",
            ),
            "has no banked reply of judge judge-a",
            id="a-reply-the-replies-lack",
        ),
    ],
)
def test_artifacts_that_are_not_a_fresh_derivation_fail(
    tmp_path: Path, rel: str, outcome: Any, match: str
) -> None:
    # The review's probe set every E2 class to never_saw: the classes need the ledgers and
    # the E2 code, and an E3 score needs the analysis, so g8 has python -m
    # receipts.report.derived derive both again in the clone (DECISIONS D65).
    ctx = artifacts(tmp_path)
    ctx.results[f"derived-{rel}"] = outcome
    with pytest.raises(GateError, match=match):
        ship_check.g8(ctx)


def gate_context(root: Path, logs: Path, monkeypatch: pytest.MonkeyPatch) -> ship_check.Context:
    """A Context whose clone is ``root`` and whose python steps run for real."""
    ctx = ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha="0" * 40)
    ctx.results["make-setup"] = given("make-setup")
    run_for_real(ctx, monkeypatch)
    return ctx


def test_the_gate_re_scores_e3_and_a_hand_set_count_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's step itself, on the SYNTHETIC study whose E3 artifact tools/run_judges.py
    wrote with SYNTHETIC judges: it re-scores from the banked replies with no model, and
    a typed count fails with the path that differs."""
    from tests.report import studies

    root = studies.e3_study(tmp_path / "e3", monkeypatch)
    first = gate_context(root, tmp_path, monkeypatch)
    ship_check.check_derivation(first, E3)
    step = first.results[f"derived-{E3}"].stdout
    assert "re-derived by python tools/run_judges.py --rescore" in step

    def add_a_true_positive(data: dict[str, Any]) -> None:
        per_type = data["judges"][0]["per_type"]
        per_type[sorted(per_type)[0]]["tp"] += 1

    studies.edit(root, E3, add_a_true_positive)
    with pytest.raises(GateError, match=r"differs from a fresh derivation .*judges\.0\.per_type"):
        ship_check.check_derivation(gate_context(root, tmp_path, monkeypatch), E3)


@pytest.mark.slow  # the SYNTHETIC E1 study is analyzed first
def test_the_gate_re_derives_e2_and_hand_set_classes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's probe on a real E2 artifact: every class set to never_saw."""
    from tests.report import studies

    root = studies.e1_study(tmp_path / "e1")
    ship_check.check_derivation(gate_context(root, tmp_path, monkeypatch), E2)

    def never_saw(data: dict[str, Any]) -> None:
        for claim in data["claims"]:
            claim["class"] = "never_saw"

    classes = json.loads((root / E2).read_text(encoding="utf-8"))["claims"]
    assert {c["class"] for c in classes} != {"never_saw"}
    studies.edit(root, E2, never_saw)
    with pytest.raises(GateError, match=r"differs from a fresh derivation .*claims\.\d+\.class"):
        ship_check.check_derivation(gate_context(root, tmp_path, monkeypatch), E2)


# ---------------------------------------------------------------- the whole sample [24]


def runs(**change: Any) -> Edit:
    """Change fields of the artifact's ``runs`` section."""

    def apply(data: dict[str, Any]) -> None:
        data["runs"].update(change)

    return apply


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(runs(complete=False), id="incomplete"),
        pytest.param(runs(complete="yes"), id="not-a-boolean"),
        pytest.param(lambda d: d.pop("runs"), id="no-runs-section"),
    ],
)
def test_e3_must_say_it_judged_its_whole_sample(tmp_path: Path, edit: Edit) -> None:
    with pytest.raises(GateError, match=r"runs\.complete"):
        ship_check.g8(artifacts(tmp_path, e3=edit))


def swap_sampled(data: dict[str, Any]) -> None:
    """Replace one sampled run by an eligible run the draw did not pick, everywhere."""
    sampled = set(data["sample"]["sampled_run_ids"])
    old = data["sample"]["sampled_run_ids"][0]
    arm = old.rsplit("-", 1)[0]
    new = next(f"{arm}-{n:03d}" for n in range(4) if f"{arm}-{n:03d}" not in sampled)
    data["sample"]["sampled_run_ids"] = sorted(sampled - {old} | {new})
    for entry in (*data["items"], *data["calls"]):
        if entry["run_id"] == old:
            entry["run_id"] = new


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        pytest.param(swap_sampled, "is not the prereg 0003 section 3 draw", id="hand-picked"),
        pytest.param(
            lambda d: d["sample"].update(seed=SEED + 1),
            "is not the prereg 0003 section 3 draw",
            id="another-seed",
        ),
        pytest.param(
            lambda d: d["sample"].update(sample_runs=6), "positive multiple of 4", id="k-of-6"
        ),
        pytest.param(lambda d: d.pop("sample"), "records no sample size", id="no-sample"),
        pytest.param(
            lambda d: d["sample"].update(sampled_run_ids=[]),
            "records no sample of run ids",
            id="an-empty-sample",
        ),
    ],
)
def test_the_recorded_sample_must_be_the_preregistered_draw(
    tmp_path: Path, edit: Edit, match: str
) -> None:
    with pytest.raises(GateError, match=match):
        ship_check.g8(artifacts(tmp_path, e3=edit))


def drop_run(data: dict[str, Any]) -> None:
    """Leave the first sampled run unscored (no items), as a partial run would."""
    first = data["sample"]["sampled_run_ids"][0]
    data["items"] = [i for i in data["items"] if i["run_id"] != first]


def extra_item(data: dict[str, Any]) -> None:
    """Score a run that is not in the sample."""
    data["items"].append(dict(data["items"][0], run_id="e1-ma-qwen7b-004"))


def unserved(data: dict[str, Any]) -> None:
    """judge-b's call for one sampled run was never served."""
    data["calls"][-1]["served"] = False


def wrong_truth(data: dict[str, Any]) -> None:
    """Score one claim against a verdict other than its row's (the run-time verdict)."""
    item = data["items"][0]
    item["truth"] = "supported" if item["truth"] == "contradicted" else "contradicted"


def foreign_exclusion(data: dict[str, Any]) -> None:
    """Exclude a run that is not in the sample."""
    data["runs"]["excluded"] = ["e1-ma-qwen7b-004"]


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        pytest.param(drop_run, "do not cover exactly the sampled runs", id="a-run-unscored"),
        pytest.param(extra_item, "do not cover exactly the sampled runs", id="an-unsampled-run"),
        pytest.param(unserved, "did not judge 1 sampled run", id="a-call-unserved"),
        pytest.param(wrong_truth, "ground truth is not the verdict", id="another-verdict"),
        pytest.param(foreign_exclusion, "excludes runs that are not in its sample", id="excl"),
    ],
)
def test_completeness_is_counted_against_the_sample(tmp_path: Path, edit: Edit, match: str) -> None:
    # runs.complete still says true; the recount does not.
    with pytest.raises(GateError, match=match):
        ship_check.g8(artifacts(tmp_path, e3=edit))


def test_a_judged_run_must_have_every_claim_scored(tmp_path: Path) -> None:
    def two_claims(data: dict[str, Any]) -> None:
        # The first sampled run's row gets a second claim that no item scores.
        first = data["sample"]["sampled_run_ids"][0]
        rows = [json.loads(line) for line in (tmp_path / RUNS).read_text("utf-8").splitlines()]
        for row in rows:
            if row["run_id"] == first:
                row["claims"].append(dict(row["claims"][0], claim_id="c1", verdict="supported"))
        put(tmp_path, RUNS, "".join(json.dumps(r) + "\n" for r in rows))
        digest = hashlib.sha256((tmp_path / RUNS).read_bytes()).hexdigest()
        data["provenance"]["inputs"][RUNS] = digest

    with pytest.raises(GateError, match="not every claim of the judged runs"):
        ship_check.g8(artifacts(tmp_path, e3=two_claims))


def exclude_first(data: dict[str, Any]) -> None:
    """Exclude the first sampled run as e3 records it (section 7): SYNTHETIC failed
    attempts of one judge's call, an excluded_unservable deviation, unserved calls."""
    first = data["sample"]["sampled_run_ids"][0]
    data["runs"]["excluded"] = [first]
    data["items"] = [i for i in data["items"] if i["run_id"] != first]
    for call in data["calls"]:
        if call["run_id"] == first:
            call.update(served=False, status="excluded")
    data["judges"] = judge_entries(data["items"])  # the scored items only, as e3 counts
    errors = [{"attempt": n, "time": "SYNTHETIC", "error": "SYNTHETIC dropped"} for n in (1, 2, 3)]
    data["exclusions"] = [
        {
            "run_id": first,
            "calls": [{"judge_id": JUDGES[0], "cache_key": "SYN", "attempts": 3, "errors": errors}],
        }
    ]
    data["deviations"] = [{"kind": "excluded_unservable", "prereg_section": "7", "run_id": first}]


def test_an_excluded_run_needs_no_judgment(tmp_path: Path) -> None:
    # Section 7: a sampled run whose call could not be served is excluded for both
    # judges and reported; the rest of the sample is still complete.
    evidence = ship_check.g8(artifacts(tmp_path, e3=exclude_first))
    assert "sample of 8 runs, 7 judged by every judge, 1 excluded" in evidence


def test_an_exclusion_without_its_failed_attempts_fails(tmp_path: Path) -> None:
    def bare(data: dict[str, Any]) -> None:
        exclude_first(data)
        del data["exclusions"]

    with pytest.raises(GateError, match="no exclusions record"):
        ship_check.g8(artifacts(tmp_path / "a", e3=bare))

    def two_attempts(data: dict[str, Any]) -> None:
        exclude_first(data)
        call = data["exclusions"][0]["calls"][0]
        call["attempts"], call["errors"] = 2, call["errors"][:2]

    with pytest.raises(GateError, match="failed 3 logged attempts"):
        ship_check.g8(artifacts(tmp_path / "b", e3=two_attempts))

    def unlogged(data: dict[str, Any]) -> None:
        exclude_first(data)
        data["exclusions"][0]["calls"][0]["errors"] = []

    with pytest.raises(GateError, match="failed 3 logged attempts"):
        ship_check.g8(artifacts(tmp_path / "c", e3=unlogged))

    def undeclared(data: dict[str, Any]) -> None:
        exclude_first(data)
        data["deviations"] = []

    with pytest.raises(GateError, match="excluded_unservable"):
        ship_check.g8(artifacts(tmp_path / "d", e3=undeclared))


def test_most_of_the_sample_cannot_be_excluded_by_listing_it(tmp_path: Path) -> None:
    # The review probe: 7 of 8 sampled runs listed as excluded, their items and calls
    # removed, and nothing recorded to justify it.
    def seven(data: dict[str, Any]) -> None:
        drop = set(data["sample"]["sampled_run_ids"][1:])
        data["runs"]["excluded"] = sorted(drop)
        data["items"] = [i for i in data["items"] if i["run_id"] not in drop]
        data["calls"] = [c for c in data["calls"] if c["run_id"] not in drop]

    with pytest.raises(GateError, match="no exclusions record"):
        ship_check.g8(artifacts(tmp_path, e3=seven))


def test_an_exclusion_record_of_a_judged_run_fails(tmp_path: Path) -> None:
    def stray(data: dict[str, Any]) -> None:
        exclude_first(data)
        data["exclusions"].append(
            dict(data["exclusions"][0], run_id=data["sample"]["sampled_run_ids"][1])
        )

    with pytest.raises(GateError, match=r"runs\.excluded omits"):
        ship_check.g8(artifacts(tmp_path, e3=stray))


def test_e3_must_be_computed_from_the_committed_rows(tmp_path: Path) -> None:
    def stale(data: dict[str, Any]) -> None:
        data["provenance"]["inputs"][RUNS] = "0" * 64

    with pytest.raises(GateError, match=r"not computed from the committed artifacts/e1/runs"):
        ship_check.g8(artifacts(tmp_path, e3=stale))


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


E2_BODY = "The SYNTHETIC mix: <!--n:e2.confusion-->5<!--/n--> from confusion.\n"
E3_BODY = (
    "SYNTHETIC precision <!--n:e3.judge-a.precision-->0.75<!--/n--> (judge-a) and "
    "<!--n:e3.judge-b.precision-->0.75<!--/n--> (judge-b).\n"
)


@pytest.mark.parametrize(
    ("report", "match"),
    [
        pytest.param(
            "## E2: mechanisms\n\nThe design: each contradicted claim gets a class.\n\n"
            f"## E3: judges\n\n{E3_BODY}",
            r"no E2 section that binds a number from artifacts/e2/mechanism\.json",
            id="e2-design-text-only",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\nThe design: two judges.\n",
            r"no E3 section that binds a number from artifacts/e3/judges\.json",
            id="e3-design-text-only",
        ),
        pytest.param(
            "## E2: mechanisms\n\nRate <!--n:e1.rate-->0.2<!--/n--> from E1.\n\n"
            f"## E3: judges\n\n{E3_BODY}",
            r"no E2 section that binds a number from",
            id="e2-binds-another-artifact",
        ),
        pytest.param(
            f"## E2: mechanisms\n\nText.\n\n## Other\n\n{E2_BODY}\n## E3: judges\n\n{E3_BODY}",
            r"no E2 section that binds a number from",
            id="e2-number-outside-its-section",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n"
            "Precision <!--n:e3.judge-a.precision-->0.75<!--/n--> for judge-a only.\n",
            r"do not name judge configuration\(s\) judge-b",
            id="a-judge-left-out",
        ),
    ],
)
def test_design_text_is_not_a_report_of_results(tmp_path: Path, report: str, match: str) -> None:
    with pytest.raises(GateError, match=match):
        ship_check.g8(artifacts(tmp_path, report=f"# SYNTHETIC\n\n{report}"))


# The E3 numbers, bound in visible prose, without naming either judge.
E3_NUMBERS = (
    "SYNTHETIC precision <!--n:e3.judge-a.precision-->0.75<!--/n--> and "
    "<!--n:e3.judge-b.precision-->0.75<!--/n-->"
)


@pytest.mark.parametrize(
    ("report", "match"),
    [
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\nThe design: judge-a and "
            f"judge-b.\n\n<!--\n{E3_BODY}-->\n",
            r"no E3 section that binds a number from artifacts/e3/judges\.json",
            id="e3-numbers-in-a-comment",
        ),
        pytest.param(
            f"## E2: mechanisms\n\nThe design. <!-- {E2_BODY.strip()} -->\n\n"
            f"## E3: judges\n\n{E3_BODY}",
            r"no E2 section that binds a number from artifacts/e2/mechanism\.json",
            id="e2-numbers-in-a-one-line-comment",
        ),
        pytest.param(
            f"## E2: mechanisms\n\nThe design.\n\n```text\n{E2_BODY}```\n\n"
            f"## E3: judges\n\n{E3_BODY}",
            r"no E2 section that binds a number from artifacts/e2/mechanism\.json",
            id="e2-numbers-in-code",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n{E3_NUMBERS} (judge-a).\n",
            r"do not name judge configuration\(s\) judge-b",
            id="judge-only-in-a-marker-key",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n{E3_NUMBERS} (judge-a)."
            "\n<!-- judge-b -->\n",
            r"do not name judge configuration\(s\) judge-b",
            id="judge-only-in-a-comment",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n{E3_NUMBERS} (judge-a). <!--"
            "\njudge-b\n-->\n",
            r"do not name judge configuration\(s\) judge-b",
            id="judge-only-in-a-multi-line-comment",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n{E3_NUMBERS} (judge-a)."
            "\n\n```text\njudge-b\n```\n",
            r"do not name judge configuration\(s\) judge-b",
            id="judge-only-in-code",
        ),
        pytest.param(
            f"## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n{E3_NUMBERS} (judge-a and "
            "judge-b-v2, judge-b.v2, and xjudge-b).\n",
            r"do not name judge configuration\(s\) judge-b",
            id="judge-only-inside-longer-ids",
        ),
    ],
)
def test_only_visible_prose_reports_and_names_the_judges(
    tmp_path: Path, report: str, match: str
) -> None:
    with pytest.raises(GateError, match=match):
        ship_check.g8(artifacts(tmp_path, report=f"# SYNTHETIC\n\n{report}"))


def test_a_judge_named_as_a_whole_word_in_visible_prose_passes(tmp_path: Path) -> None:
    report = (
        f"# SYNTHETIC\n\n## E2: mechanisms\n\n{E2_BODY}\n## E3: judges\n\n{E3_NUMBERS}"
        " for `judge-a` and **judge-b**, the two judges.\n"
    )
    assert "E3 2 judges" in ship_check.g8(artifacts(tmp_path, report=report))


def test_the_report_needs_the_numbers_registry(tmp_path: Path) -> None:
    ctx = artifacts(tmp_path)
    (tmp_path / "artifacts" / "report" / "numbers.json").unlink()
    with pytest.raises(GateError, match=r"artifacts/report/numbers\.json"):
        ship_check.g8(ctx)
