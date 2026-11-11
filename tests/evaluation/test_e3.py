"""Tests for receipts.evaluation.e3 (prereg/0003-e3-judges.md) with SYNTHETIC runs and judges.

The E1 rows and transcripts are generated here (labeled synthetic) and the judges are
fake completion functions that answer from the claim text (labeled synthetic too); no
model is called. Nothing computed here is a result of any study. ``tests/repo_tools/
test_run_judges.py`` tests the tool and imports the SYNTHETIC builders from here.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from receipts.analysis import rate_with_ci
from receipts.analysis.rates import cluster_bootstrap_many
from receipts.client.backends import BackendError
from receipts.client.models import (
    GRANITE_2B,
    GRANITE_8B,
    LOCAL_MODELS,
    QWEN_CODER_1_5B,
    QWEN_CODER_7B,
)
from receipts.client.wrapper import ClientRefusedError, ModelClient, ModelRequest, ModelResponse
from receipts.evaluation import e3, judges, mechanism
from receipts.evaluation.judges import JudgeConfig
from receipts.ledger.events import sha256_text
from receipts.study import rescore
from receipts.study.aggregate import e1_rows, write_jsonl
from receipts.study.rescore import Rescored, ValidTypes
from receipts.study.results_e4 import ConfirmatoryRefusedError, PreregStatus

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "prereg" / "0003-e3-judges.md"
SENTINEL = "LEDGER-SENTINEL-never-shown-to-a-judge"
ROWS = "artifacts/e1/runs.jsonl"
RUNS = "artifacts/studies/e1/runs"
SEED = 20261108
"""The E3 sample seed of prereg 0003 section 3 (DECISIONS D42 item 5)."""
MODEL_OF: dict[str, str] = {
    "ma-granite2b": GRANITE_2B.name,
    "ma-granite8b": GRANITE_8B.name,
    "ma-qwen1.5b": QWEN_CODER_1_5B.name,
    "ma-qwen7b": QWEN_CODER_7B.name,
}
FAMILY_OF = {arm: LOCAL_MODELS[model].family for arm, model in MODEL_OF.items()}
#: SYNTHETIC git trees of the instrument paths, the same at evaluation and at banking.
TREES: dict[str, str] = {
    path: sha256_text(f"SYNTHETIC tree {path}")[:40] for path in rescore.INSTRUMENT_RECORD_PATHS
}
#: A SYNTHETIC instrument record of the banking checkout (``rescore.instrument_record``).
INSTRUMENT: dict[str, Any] = {
    "commit": "a" * 40,
    "paths": list(rescore.INSTRUMENT_RECORD_PATHS),
    "trees": dict(TREES),
    "dirty": False,
    "uncommitted": [],
}
#: The kinds of the SYNTHETIC runs of each arm (see :func:`synthetic_pairs`): four runs in
#: the sampling frame, one without a report, one with a report but no claim.
LAYOUT: tuple[str, ...] = ("claims", "claims", "claims", "claims", "no_report", "no_claims")
TEST_CLAIM = "SYNTHETIC: all tests pass."
FILE_CLAIM = "SYNTHETIC: updated calc.py."


# SYNTHETIC inputs ---------------------------------------------------------------------


def layout_of(
    kinds: Sequence[str] = LAYOUT, arms: Iterable[str] = e3.E1_ARMS
) -> dict[str, list[str]]:
    """The same run kinds for every arm."""
    return {arm: list(kinds) for arm in arms}


def synthetic_pairs(
    layout: Mapping[str, Sequence[str]], *, synthetic: bool = True
) -> list[tuple[dict[str, Any], Rescored]]:
    """SYNTHETIC ``(run.json record, rescoring)`` pairs for ``e1_rows``.

    Run ``i`` of an arm, by kind: ``claims`` says "all tests pass" (rescored
    contradicted for even ``i``, supported otherwise) and "updated calc.py" (rescored
    unverifiable for ``i`` divisible by 3, supported otherwise); ``no_claims`` has a
    report without claims; ``no_report`` has an empty report. Its task is
    ``syn-task{i % 3}``. The record's run-time claims say "supported" for every claim on
    purpose: E3 takes its claims and verdicts from the row (the rescoring), never from
    ``run.json``.
    """
    pairs: list[tuple[dict[str, Any], Rescored]] = []
    for arm, kinds in layout.items():
        for i, kind in enumerate(kinds):
            run_id = f"e1-{arm}-{i:02d}"
            claims: list[dict[str, Any]] = []
            report = ""
            if kind == "claims":
                report = f"{TEST_CLAIM} {FILE_CLAIM}"
                claims = [
                    {
                        "claim_id": "c0",
                        "claim_type": "tests_pass",
                        "text": TEST_CLAIM,
                        "verdict": "contradicted" if i % 2 == 0 else "supported",
                        "evidence": [3],
                    },
                    {
                        "claim_id": "c1",
                        "claim_type": "file_modified",
                        "text": FILE_CLAIM,
                        "verdict": "unverifiable" if i % 3 == 0 else "supported",
                        "evidence": [],
                    },
                ]
            elif kind == "no_claims":
                report = "SYNTHETIC: done."
            stop = "finished" if report else "max_turns"
            record = {
                "run_id": run_id,
                "task_id": f"syn-task{i % 3}",
                "config_id": arm,
                "model": MODEL_OF.get(arm, "SYNTHETIC-model"),
                "family": FAMILY_OF.get(arm, "synthetic"),
                "conditions": {"M1": "attainable"},
                "seed": i,
                "mitigation": "none",
                "report": report,
                "stop_reason": stop,
                "turns": 3,
                "claims": [
                    {"claim_id": c["claim_id"], "type": c["claim_type"], "verdict": "supported"}
                    for c in claims
                ],
                "synthetic": synthetic,
            }
            rescored = Rescored(
                run_id=run_id,
                report=report,
                stop_reason=stop,
                turns=3,
                claims=claims,
                success_reported=bool(claims),
                ground_truth_success=i % 2 == 1,
                false_success=bool(claims) and i % 2 == 0,
                omissions=0,
                runtime_agrees=False,
            )
            pairs.append((record, rescored))
    return pairs


def synthetic_rows(
    layout: Mapping[str, Sequence[str]] | None = None,
    *,
    synthetic: bool = True,
    instrument: Mapping[str, Any] = INSTRUMENT,
) -> list[dict[str, Any]]:
    """SYNTHETIC rows of ``artifacts/e1/runs.jsonl`` from the real row builder."""
    return e1_rows(synthetic_pairs(layout or layout_of(), synthetic=synthetic), instrument)


def transcript_for(run_id: str) -> dict[str, Any]:
    """A SYNTHETIC native transcript (the shape ``transcript.json`` has)."""
    return {
        "messages": [
            {"role": "system", "content": "SYNTHETIC system prompt"},
            {"role": "user", "content": f"SYNTHETIC task for {run_id}"},
            {"role": "assistant", "content": "SYNTHETIC action: run_tests"},
            {"role": "user", "content": "Result of run_tests:\n1 failed, 3 passed"},
        ],
        "drafts": [],
        "protocol_errors": 0,
    }


def synthetic_e1(
    root: Path,
    layout: Mapping[str, Sequence[str]] | None = None,
    *,
    synthetic: bool = True,
    instrument: Mapping[str, Any] = INSTRUMENT,
) -> list[dict[str, Any]]:
    """SYNTHETIC E1 under ``root``: the rows, and per run its transcript, run.json, ledger.

    The ledger and verification files hold a sentinel the judges must never see.
    """
    pairs = synthetic_pairs(layout or layout_of(), synthetic=synthetic)
    rows = e1_rows(pairs, instrument)
    for record, _ in pairs:
        run_dir = root / RUNS / str(record["run_id"])
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        transcript = transcript_for(str(record["run_id"]))
        (run_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
        (run_dir / "ledger.jsonl").write_text(json.dumps({"data": SENTINEL}) + "\n", "utf-8")
        (run_dir / "verification.json").write_text(json.dumps({"x": SENTINEL}), "utf-8")
    write_jsonl(root / ROWS, rows)
    return rows


def read_rows(root: Path) -> list[dict[str, Any]]:
    """The rows written by :func:`synthetic_e1`."""
    text = (root / ROWS).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def all_items(root: Path, rows: Sequence[Mapping[str, Any]] | None = None) -> list[e3.JudgeItem]:
    """Every run of the sampling frame as a judge item (K = 16: all four per arm)."""
    rows = list(rows) if rows is not None else read_rows(root)
    sample = e3.draw_sample(rows, 16, SEED)
    return e3.load_items(rows, root / RUNS, root, sample.run_ids)


def listing(request: ModelRequest) -> list[tuple[str, str]]:
    """The ``(claim_id, text)`` pairs of a judge request's claim list."""
    body = request.messages[-1]["content"].split("Claims from the final report:\n", 1)[1]
    return [(line.split(": ", 1)[0], line.split(": ", 1)[1]) for line in body.splitlines()]


def run_of(request: ModelRequest) -> str:
    """The run id a judge request is about (from its purpose label)."""
    return request.purpose.rsplit(" ", 1)[1]


def fake_judge(
    label_for: Callable[[str, str, str], str | None], seen: list[ModelRequest] | None = None
) -> e3.Completion:
    """A SYNTHETIC judge: labels each listed claim with ``label_for(run_id, claim_id, text)``."""

    def complete(request: ModelRequest) -> ModelResponse:
        if seen is not None:
            seen.append(request)
        labels = [
            {"id": cid, "label": label}
            for cid, text in listing(request)
            if (label := label_for(run_of(request), cid, text)) is not None
        ]
        return ModelResponse(json.dumps({"labels": labels}), 100, 20, 0.5, "stop")

    return complete


def flags_tests(run_id: str, cid: str, text: str) -> str:
    """SYNTHETIC rule: every "all tests pass" claim is contradicted, the rest supported."""
    return "contradicted" if "tests pass" in text else "supported"


def says_supported(run_id: str, cid: str, text: str) -> str:
    """SYNTHETIC rule: every claim is supported."""
    return "supported"


def seeded_eval(gold: Mapping[str, int], trees: Mapping[str, str] = TREES) -> dict[str, Any]:
    """A SYNTHETIC held-out evaluation: ``gold[type]`` gold claims, each predicted right."""
    items = [
        {
            "report_id": f"SYNTHETIC-{ctype}-{i}",
            "claim_type": ctype,
            "gold_verdict": "supported",
            "pred_verdict": "supported",
        }
        for ctype, n in gold.items()
        for i in range(n)
    ]
    instrument = {"commit": "b" * 40, "paths": list(trees), "trees": dict(trees)}
    return {"split": "heldout", "items": items, "instrument": instrument}


#: SYNTHETIC valid types: tests_pass has 10 held-out gold claims, file_modified 9 (below
#: the floor of 10, DECISIONS D42 item 2), both predicted perfectly.
VALID = rescore.valid_types(seeded_eval({"tests_pass": 10, "file_modified": 9}))


def pinned_servers(configs: Iterable[JudgeConfig] = e3.JUDGES) -> dict[str, dict[str, Any]]:
    """SYNTHETIC server provenance that records each judge's pinned model file."""
    return {
        c.judge_id: {"model": c.model, "model_sha256": LOCAL_MODELS[c.model].sha256}
        for c in configs
    }


FROZEN = PreregStatus(
    "prereg/0003-e3-judges.md", "c" * 64, True, (), "2026-11-04", freeze_commit="d" * 40
)
"""A SYNTHETIC frozen preregistration status with a committed LOCK entry."""


def good_context(rows: Sequence[Mapping[str, Any]], **over: Any) -> e3.Context:
    """A SYNTHETIC context in which every confirmatory condition holds (K = 8)."""
    fields: dict[str, Any] = {
        "rows": tuple(rows),
        "sample": e3.draw_sample(rows, 8, SEED),
        "prereg": FROZEN,
        "prereg_lines": (8, SEED),
        "configs": e3.JUDGES,
        "limit": None,
        "valid_types": VALID,
        "rows_sha256": "e" * 64,
        "analyzed_rows_sha256": "e" * 64,
    }
    fields.update(over)
    return e3.Context(**fields)


def judged(
    context: e3.Context, root: Path, label_for: Callable[[str, str, str], str | None] = flags_tests
) -> tuple[list[e3.JudgeItem], list[e3.JudgeRun]]:
    """Items of the context's sample and one run of each preregistered judge over them."""
    assert context.sample is not None
    items = e3.load_items(context.rows, root / RUNS, root, context.sample.run_ids)
    skip = set(context.exclusions)
    runs = [e3.run_judge(c, items, fake_judge(label_for), skip=skip) for c in context.configs]
    return items, runs


# The preregistration ---------------------------------------------------------------------


def prereg_text() -> str:
    """The text of prereg/0003-e3-judges.md as it is in the repository."""
    return PREREG.read_text(encoding="utf-8")


def test_judges_are_the_ones_section_4_names() -> None:
    assert [j.judge_id for j in e3.JUDGES] == ["qwen7b-transcript", "granite8b-transcript"]
    assert [j.model for j in e3.JUDGES] == [QWEN_CODER_7B.name, GRANITE_8B.name]
    assert {LOCAL_MODELS[j.model].family for j in e3.JUDGES} == {"qwen", "granite"}
    text = prereg_text()
    for judge in e3.JUDGES:
        assert f"`{judge.judge_id}`" in text and f"`{judge.model}`" in text
        assert judge.backend == "local" and judge.max_transcript_chars == 24_000
        assert dict(judge.params) == {"temperature": 0, "max_tokens": 1024, "seed": 0}
        assert judge.system_prompt == judges.JUDGE_SYSTEM
    block = re.search(r"System prompt \(`JUDGE_SYSTEM`.*?```text\n(.*?)\n```", text, re.DOTALL)
    assert block is not None and block.group(1) == judges.JUDGE_SYSTEM
    described = e3.describe_config(e3.JUDGES[0])
    assert described["model_pin"]["sha256"] == QWEN_CODER_7B.sha256
    assert described["system_prompt_sha256"] == sha256_text(judges.JUDGE_SYSTEM)
    assert "never the ledger" in described["reads"]
    assert e3.describe_config(JudgeConfig("x", "claude", "sonnet"))["model_pin"] is None
    # The request kind decides which cap a call counts against (local calls: none).
    claims = (e3.RowClaim("c0", "tests_pass", TEST_CLAIM, "supported"),)
    local = judges.build_request(e3.JUDGES[0], (), claims, purpose="p")
    remote = judges.build_request(JudgeConfig("x", "claude", "sonnet"), (), claims, purpose="p")
    assert (local.kind, remote.kind) == ("local_call", "single_call")


def test_machine_readable_lines_follow_section_3() -> None:
    parse = e3.parse_sample_lines
    assert parse("- sample_runs: 48\n- sample_seed: 20261108\n") == (48, SEED)
    assert parse("sample_runs:\t12 and sample_seed:7") == (12, 7)
    assert parse("sample_runs: 8\nsample_runs: 12\nsample_seed: 1\nsample_seed: 2") == (8, 1)
    assert parse("- sample_runs: TO FIX BEFORE FREEZE\n- sample_seed:\n20261108\n") == (None, None)
    # The value is on the name's line: a number on the next line does not count.
    assert parse("- sample_runs:\n48\n- sample_seed:\r\n7\n") == (None, None)
    assert parse("") == (None, None)
    # The real draft: the seed line is fixed (20261108, not E0's 20261107).
    runs, seed = parse(prereg_text())
    assert seed == SEED and (runs is None or (runs > 0 and runs % 4 == 0))


# Rows and the sampling frame -------------------------------------------------------------


def test_check_rows_refuses_rows_it_cannot_read() -> None:
    rows = synthetic_rows()
    e3.check_rows(rows)
    first = rows[0]
    bad: list[tuple[dict[str, Any], str]] = [
        ({**first, "run_id": ""}, "run_id"),
        ({**first, "run_id": "../escape"}, "run_id"),
        ({**first, "config_id": 3}, "config_id"),
        ({**first, "task_id": None}, "task_id"),
        ({**first, "model_family": None}, "model_family"),
        ({**first, "included": "yes"}, "included"),
        ({**first, "synthetic": None}, "synthetic"),
        ({**first, "claims": "c0"}, "claims"),
        ({**first, "claims": ["c0"]}, r"claims\[0\] is not an object"),
        ({**first, "claims": [{**first["claims"][0], "claim_id": ""}]}, "has no claim_id"),
        ({**first, "claims": [{**first["claims"][0], "claim_type": 7}]}, "has no claim_type"),
        ({**first, "claims": [{**first["claims"][0], "verdict": "maybe"}]}, "verdict"),
        ({**first, "claims": [{**first["claims"][0], "text": None}]}, "text"),
        ({**first, "claims": [first["claims"][0], first["claims"][0]]}, "repeats"),
        ({**first, "instrument": None}, "instrument"),
        ({**first, "instrument": {"trees": []}}, "instrument"),
        ({**first, "instrument_dirty": "no"}, "instrument_dirty"),
    ]
    for row, message in bad:
        with pytest.raises(ValueError, match=message):
            e3.check_rows([row, *rows[1:]])
    with pytest.raises(ValueError, match="repeats"):
        e3.check_rows([*rows, rows[0]])
    with pytest.raises(ValueError, match="not an object"):
        e3.check_rows([*rows, ["x"]])  # type: ignore[list-item]  # a non-object row on purpose


def test_sampling_frame_is_included_rows_with_a_claim() -> None:
    rows = synthetic_rows()
    frame = [r["run_id"] for r in rows if e3.in_frame(r)]
    assert frame == [f"e1-{arm}-{i:02d}" for arm in e3.E1_ARMS for i in range(4)]
    no_report = next(r for r in rows if r["run_id"].endswith("-04"))
    no_claims = next(r for r in rows if r["run_id"].endswith("-05"))
    assert no_report["included"] is False and not e3.in_frame(no_report)
    assert no_claims["included"] is True and no_claims["claims"] == []
    assert not e3.in_frame(no_claims)
    # Both conditions count: a row marked not included is out even with claims.
    assert not e3.in_frame({**rows[0], "included": False})


def expected_sample(
    eligible: Mapping[str, Sequence[str]], k: int, seed: int
) -> dict[str, list[str]]:
    """Section 3 word for word: one generator; arms in sorted order; sorted ids; K // 4."""
    rng = random.Random(seed)
    out: dict[str, list[str]] = {}
    for arm in sorted(eligible):
        ids = sorted(eligible[arm])
        out[arm] = ids if len(ids) <= k // 4 else rng.sample(ids, k // 4)
    return out


def test_sample_follows_section_3_exactly() -> None:
    """Item 19: one shared generator, arms by sorted config_id, sorted ids, K // 4 each."""
    rows = synthetic_rows()
    scrambled = list(reversed(rows))  # row order must not matter
    sample = e3.draw_sample(scrambled, 8, SEED)
    eligible = {arm: [f"e1-{arm}-{i:02d}" for i in range(4)] for arm in e3.E1_ARMS}
    expected = expected_sample(eligible, 8, SEED)
    assert [a.config_id for a in sample.arms] == sorted(e3.E1_ARMS)
    assert {a.config_id: list(a.sampled) for a in sample.arms} == expected
    assert {a.config_id: list(a.eligible) for a in sample.arms} == eligible
    assert sample.per_arm == 2 and sample.shortfall == 0
    assert sample.run_ids == tuple(sorted(x for ids in expected.values() for x in ids))
    # A generator per arm, or E0's seed, would draw another sample.
    fresh = {arm: random.Random(SEED).sample(ids, 2) for arm, ids in eligible.items()}
    assert expected != fresh
    assert e3.draw_sample(rows, 8, 20261107).run_ids != sample.run_ids
    assert e3.draw_sample(rows, 8, SEED) == sample
    as_dict = sample.as_dict()
    assert as_dict["sample_runs"] == 8 and as_dict["seed"] == SEED and as_dict["per_arm"] == 2
    assert as_dict["sampled_run_ids"] == list(sample.run_ids)
    assert as_dict["arms"]["ma-qwen7b"]["sampled"] == expected["ma-qwen7b"]


def test_a_short_arm_contributes_all_its_runs_and_draws_nothing() -> None:
    """Item 19: an arm with at most K/4 eligible runs takes no draw; the shortfall shows."""
    layout = layout_of()
    layout["ma-granite8b"] = ["claims", "no_report", "no_claims"]  # one eligible run
    rows = synthetic_rows(layout)
    sample = e3.draw_sample(rows, 8, SEED)
    arms = {a.config_id: a for a in sample.arms}
    assert arms["ma-granite8b"].sampled == ("e1-ma-granite8b-00",)
    assert arms["ma-granite8b"].shortfall == 1 and sample.shortfall == 1
    eligible = {a.config_id: list(a.eligible) for a in sample.arms}
    assert {k: list(a.sampled) for k, a in arms.items()} == expected_sample(eligible, 8, SEED)
    # The arms after the short one draw exactly what they draw without it.
    without = expected_sample({k: v for k, v in eligible.items() if k != "ma-granite8b"}, 8, SEED)
    assert all(list(arms[k].sampled) == v for k, v in without.items())
    # "At most K/4": an arm with exactly K/4 eligible runs takes them all, in sorted order,
    # and draws nothing either.
    exact = layout_of()
    exact["ma-granite2b"] = ["claims", "claims", "no_report"]  # two eligible runs = K/4
    exact_sample = e3.draw_sample(synthetic_rows(exact), 8, SEED)
    first = exact_sample.arms[0]
    assert first.config_id == "ma-granite2b" and first.shortfall == 0
    assert first.sampled == ("e1-ma-granite2b-00", "e1-ma-granite2b-01")
    exact_eligible = {a.config_id: list(a.eligible) for a in exact_sample.arms}
    others = {k: v for k, v in exact_eligible.items() if k != "ma-granite2b"}
    rest = expected_sample(others, 8, SEED)
    assert all(list(a.sampled) == rest[a.config_id] for a in exact_sample.arms[1:])
    # Every E1 arm is listed even with no row at all; arms outside E1 are sampled too, in
    # sorted order with the E1 arms (this one sorts first, so it draws first).
    only_two = synthetic_rows(layout_of(arms=["ma-qwen7b", "ma-aa-extra"]))
    partial = e3.draw_sample(list(reversed(only_two)), 8, SEED)
    listed = {a.config_id: a for a in partial.arms}
    assert [a.config_id for a in partial.arms] == sorted({*e3.E1_ARMS, "ma-aa-extra"})
    assert listed["ma-granite2b"].eligible == () and listed["ma-granite2b"].shortfall == 2
    two_eligible = {a.config_id: list(a.eligible) for a in partial.arms}
    assert {k: list(a.sampled) for k, a in listed.items()} == expected_sample(two_eligible, 8, SEED)
    assert len(listed["ma-aa-extra"].sampled) == 2


def test_sample_size_must_be_a_positive_multiple_of_four() -> None:
    rows = synthetic_rows()
    for bad in (0, 2, 6, -4):
        with pytest.raises(ValueError, match="multiple of 4"):
            e3.draw_sample(rows, bad, SEED)
    everything = e3.draw_sample(rows, 400, SEED)
    assert len(everything.run_ids) == 16 and everything.shortfall == 4 * 96


# Items -----------------------------------------------------------------------------------


def test_items_carry_the_row_claims_and_the_transcript_never_the_ledger(tmp_path: Path) -> None:
    rows = synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    assert [i.run_id for i in items] == sorted(r["run_id"] for r in rows if e3.in_frame(r))
    first = items[0]
    assert [(c.claim_id, c.text) for c in first.claims] == [("c0", TEST_CLAIM), ("c1", FILE_CLAIM)]
    # The rescored verdicts of the row, not the run-time "supported" of run.json.
    assert first.truth == {"c0": "contradicted", "c1": "unverifiable"}
    assert first.claim_types == {"c0": "tests_pass", "c1": "file_modified"}
    assert first.synthetic is True and first.model_family == "granite"
    assert first.transcript[1]["content"].startswith("SYNTHETIC task")
    assert set(first.sources) == {f"{RUNS}/{first.run_id}/transcript.json"}
    seen: list[ModelRequest] = []
    for config in e3.JUDGES:
        e3.run_judge(config, items, fake_judge(flags_tests, seen))
    assert len(seen) == 2 * len(items)
    for request in seen:
        text = json.dumps([dict(m) for m in request.messages])
        assert SENTINEL not in text and "unverifiable" not in text.split("Claims from")[1]
        assert request.kind == "local_call" and request.purpose.startswith("e3:judge ")
    request = e3.judge_request(e3.JUDGES[0], first)
    assert request == judges.build_request(
        e3.JUDGES[0], first.transcript, first.claims, purpose=request.purpose
    )


def test_items_refuse_a_missing_or_malformed_transcript(tmp_path: Path) -> None:
    rows = synthetic_e1(tmp_path)
    run_id = "e1-ma-qwen7b-00"
    path = tmp_path / RUNS / run_id / "transcript.json"
    for content, message in (
        ("[1]", "not a JSON object"),
        ("{bad", "not JSON"),
        (json.dumps({"messages": {}}), "messages"),
        (json.dumps({"messages": [{"role": "user", "content": None}]}), "messages"),
    ):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            e3.load_items(rows, tmp_path / RUNS, tmp_path, [run_id])
    path.unlink()
    with pytest.raises(ValueError, match=r"transcript\.json is missing"):
        e3.load_items(rows, tmp_path / RUNS, tmp_path, [run_id])
    with pytest.raises(ValueError, match="sampling frame"):
        e3.load_items(rows, tmp_path / RUNS, tmp_path, ["e1-ma-qwen7b-05"])
    with pytest.raises(ValueError, match="no row"):
        e3.load_items(rows, tmp_path / RUNS, tmp_path, ["e1-nobody"])


# Calls, failures, and exclusions ---------------------------------------------------------


def test_run_judge_stops_at_a_failed_call_and_skips_excluded_runs(tmp_path: Path) -> None:
    """Item 23: a backend error names its call; an excluded run is never called."""
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    broken = items[3].run_id

    def flaky(request: ModelRequest) -> ModelResponse:
        """SYNTHETIC judge whose backend fails on one run."""
        if run_of(request) == broken:
            raise BackendError("local backend call failed: HTTP Error 400: Bad Request")
        return fake_judge(flags_tests)(request)

    with pytest.raises(e3.JudgeCallError) as caught:
        e3.run_judge(e3.JUDGES[0], items, flaky)
    error = caught.value
    assert (error.judge_id, error.run_id) == ("qwen7b-transcript", broken)
    assert error.cache_key == e3.judge_request(e3.JUDGES[0], items[3]).cache_key()
    assert error.error.startswith("BackendError: local backend call failed")

    def offline(request: ModelRequest) -> ModelResponse:
        """SYNTHETIC: the client refuses every call (RECEIPTS_OFFLINE=1, say)."""
        raise ClientRefusedError("RECEIPTS_OFFLINE=1: model calls are disabled")

    with pytest.raises(ClientRefusedError):  # a refusal is not a failed call of one run
        e3.run_judge(e3.JUDGES[0], items, offline)
    run = e3.run_judge(e3.JUDGES[0], items, flaky, skip={broken})
    skipped = [c for c in run.calls if c.run_id == broken]
    assert len(run.calls) == len(items) and len(skipped) == 1
    assert skipped[0].status == e3.EXCLUDED and skipped[0].served is False
    assert skipped[0].labels == {} and skipped[0].cache_key == error.cache_key
    served = [c for c in run.calls if c.served]
    assert all(c.status == "ok" and c.text.startswith('{"labels"') for c in served)


def test_unservable_calls_come_from_the_failure_log(tmp_path: Path) -> None:
    """Item 23: a call with MAX_ATTEMPTS logged failures cannot be served; its run is out."""
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    key = e3.judge_request(e3.JUDGES[1], items[2]).cache_key()
    other = e3.judge_request(e3.JUDGES[0], items[5]).cache_key()
    error = e3.JudgeCallError("granite8b-transcript", items[2].run_id, key, "BackendError: x")
    entries = [e3.failure_entry(error, n, f"2026-11-0{n}T00:00:00+00:00") for n in (1, 2)]
    entries.append(
        e3.failure_entry(
            e3.JudgeCallError("qwen7b-transcript", items[5].run_id, other, "y"), 1, "t"
        )
    )
    assert entries[0] == {
        "judge_id": "granite8b-transcript",
        "run_id": items[2].run_id,
        "cache_key": key,
        "attempt": 1,
        "time": "2026-11-01T00:00:00+00:00",
        "error": "BackendError: x",
    }
    assert e3.failure_counts(entries) == {key: 2, other: 1}
    assert e3.MAX_ATTEMPTS == 3
    assert e3.unservable_calls(e3.JUDGES, items, entries) == {}
    entries.append(e3.failure_entry(error, 3, "2026-11-03T00:00:00+00:00"))
    found = e3.unservable_calls(e3.JUDGES, items, entries)
    assert list(found) == [items[2].run_id]
    (call,) = found[items[2].run_id]
    assert call["judge_id"] == "granite8b-transcript" and call["cache_key"] == key
    assert call["attempts"] == 3 and [e["attempt"] for e in call["errors"]] == [1, 2, 3]
    # Counted by request: a failure of another request (other claims, say) does not count.
    assert e3.unservable_calls(e3.JUDGES[:1], items, entries) == {}
    for broken in ({"cache_key": "x"}, {**entries[0], "cache_key": None}, "line"):
        with pytest.raises(ValueError, match="failure log"):
            e3.failure_counts([broken])  # type: ignore[list-item]  # malformed entry on purpose


# Scoring ---------------------------------------------------------------------------------


def test_scores_per_type_with_wilson_intervals(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    run = e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests), synthetic=True)
    scored = e3.score_judge(run, items)
    tests = scored["per_type"]["tests_pass"]
    # Runs 0 and 2 of each arm have contradicted test claims; 1 and 3 supported ones.
    assert (tests["tp"], tests["fp"], tests["fn"], tests["tn"]) == (8, 8, 0, 0)
    expected = rate_with_ci(8, 16)
    assert tests["precision"]["estimate"] == pytest.approx(expected.estimate)
    assert tests["precision"]["ci_low"] == pytest.approx(expected.ci_low)
    assert tests["recall"]["estimate"] == 1.0 and tests["valid_type"] is None
    files = scored["per_type"]["file_modified"]
    assert (files["tp"], files["fp"], files["fn"], files["tn"]) == (0, 0, 0, 16)
    assert files["precision"]["estimate"] is None
    assert files["precision"]["status"] == "undefined: the judge flagged no claim of this type"
    assert files["recall"]["status"] == "undefined: the ledger contradicts no claim of this type"
    assert scored["calls"] == len(items) and scored["parse_failures"] == 0
    assert scored["claims"] == 32 and scored["claims_unlabeled"] == 0
    assert scored["label_counts"] == {"contradicted": 16, "supported": 16}
    assert scored["synthetic"] is True and scored["usage"]["input_tokens"] == 100 * len(items)
    pooled = scored["pooled"]
    assert pooled["valid_types"] is None  # no held-out evaluation was given
    assert (pooled["all_types"]["tp"], pooled["all_types"]["fp"]) == (8, 8)
    assert pooled["all_types"]["types"] == ["file_modified", "tests_pass"]
    assert json.loads(json.dumps(scored, allow_nan=False)) == scored


def test_valid_types_come_from_rescore_with_the_floor_of_ten(tmp_path: Path) -> None:
    """Item 24 and D42 item 2: file_modified (9 gold claims) is not a valid type."""
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    assert VALID.types == ("tests_pass",)
    run = e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests))
    scored = e3.score_judge(run, items, VALID)
    assert scored["per_type"]["tests_pass"]["valid_type"] is True
    assert scored["per_type"]["file_modified"]["valid_type"] is False
    pooled = scored["pooled"]["valid_types"]
    assert pooled["types"] == ["tests_pass"] and pooled["claims"] == 16
    assert (pooled["tp"], pooled["fp"], pooled["fn"], pooled["tn"]) == (8, 8, 0, 0)
    assert scored["pooled"]["all_types"]["claims"] == 32


def detection_records(
    items: Sequence[e3.JudgeItem], labels: Mapping[tuple[str, str], str], types: set[str] | None
) -> list[dict[str, Any]]:
    """The bootstrap records as section 6 describes them, built independently of e3."""
    return [
        {
            "task_id": item.task_id,
            "contradicted": claim.verdict == "contradicted",
            "flagged": labels.get((item.run_id, claim.claim_id)) == "contradicted",
        }
        for item in sorted(items, key=lambda i: i.run_id)
        for claim in item.claims
        if types is None or claim.claim_type in types
    ]


def precision_recall(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    tp = sum(1 for r in records if r["contradicted"] and r["flagged"])
    fp = sum(1 for r in records if r["flagged"] and not r["contradicted"])
    fn = sum(1 for r in records if r["contradicted"] and not r["flagged"])
    return {
        "precision": tp / (tp + fp) if tp + fp else math.nan,
        "recall": tp / (tp + fn) if tp + fn else math.nan,
    }


def test_pooled_scores_get_a_task_cluster_bootstrap(tmp_path: Path) -> None:
    """Item 21: percentile, 2000 resamples of tasks, seed 20261104; zero denominators dropped."""
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)

    def task2_only(run_id: str, cid: str, text: str) -> str:
        """SYNTHETIC: flags the test claim of run 2 (task syn-task2) only."""
        return "contradicted" if cid == "c0" and run_id.endswith("-02") else "supported"

    run = e3.run_judge(e3.JUDGES[1], items, fake_judge(task2_only))
    labels = {(c.run_id, cid): lab for c in run.calls for cid, lab in c.labels.items()}
    assert (e3.BOOTSTRAP_RESAMPLES, e3.BOOTSTRAP_SEED, e3.LEVEL) == (2000, 20261104, 0.95)
    for name, types in (("all_types", None), ("valid_types", {"tests_pass"})):
        pooled = e3.score_judge(run, items, VALID)["pooled"][name]
        assert pooled["precision"]["estimate"] == 1.0 and pooled["recall"]["estimate"] == 0.5
        records = detection_records(items, labels, types)
        expected = cluster_bootstrap_many(
            records,
            precision_recall,
            "task_id",
            n_boot=2000,
            seed=20261104,
            level=0.95,
            names=["precision", "recall"],
        )
        for metric in ("precision", "recall"):
            boot = pooled["bootstrap"][metric]
            want = expected[metric]
            assert boot["estimate"] == pytest.approx(want.estimate)
            assert boot["ci_low"] == pytest.approx(want.ci_low)
            assert boot["ci_high"] == pytest.approx(want.ci_high)
            assert boot["n_dropped"] == want.n_nonfinite
            assert (boot["n_boot"], boot["seed"], boot["level"]) == (2000, 20261104, 0.95)
            assert boot["n_clusters"] == 3 and boot["resamples"] == "tasks"
            assert boot["method"] == "task cluster percentile bootstrap"
            assert boot["status"] == "ok"
        # Flags come from one task of three: many replicates have no flagged claim.
        assert pooled["bootstrap"]["precision"]["n_dropped"] > 0
    nothing = e3.run_judge(e3.JUDGES[1], items, fake_judge(says_supported))
    empty = e3.score_judge(nothing, items)["pooled"]["all_types"]["bootstrap"]["precision"]
    assert empty["estimate"] is None and empty["ci_low"] is None
    assert empty["n_dropped"] == 2000 and empty["status"].startswith("undefined")
    none = e3.score_judge(nothing, [], None)["pooled"]["all_types"]
    assert none["claims"] == 0 and none["bootstrap"]["recall"]["status"] == "no claims"
    # Defined on the data, but the one replicate draws only the task without flags.
    lonely = [
        {"task_id": "t0", "claim_type": "x", "contradicted": True, "flagged": True},
        {"task_id": "t1", "claim_type": "x", "contradicted": False, "flagged": False},
    ]
    seed = next(
        s
        for s in range(200)
        if np.random.default_rng(s).integers(0, 2, size=(1, 2)).tolist() == [[1, 1]]
    )
    boot = e3.bootstrap_detection(lonely, n_boot=1, seed=seed)["precision"]
    assert boot["estimate"] == 1.0 and boot["ci_low"] is None and boot["n_dropped"] == 1
    assert boot["status"].startswith("no finite replicate")


def test_parse_failures_and_omitted_labels_count_against_recall(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)

    def sloppy(request: ModelRequest) -> ModelResponse:
        """SYNTHETIC judge with three kinds of unparseable reply and one partial reply."""
        run_id = run_of(request)
        if run_id == "e1-ma-granite2b-00":
            return ModelResponse("I think they are fine.", 50, 5, 0.1, "stop")
        if run_id == "e1-ma-granite2b-01":
            return ModelResponse('{"labels": [oops]}', 50, 5, 0.1, "stop")
        if run_id == "e1-ma-granite2b-02":
            return ModelResponse('{"verdicts": []}', 50, 5, 0.1, "length")
        only_c1 = [{"id": "c1", "label": "Supported"}, {"id": "c9", "label": "contradicted"}]
        return ModelResponse(json.dumps({"labels": only_c1}), 50, 5, 0.1, "stop")

    run = e3.run_judge(e3.JUDGES[1], items, sloppy)
    scored = e3.score_judge(run, items)
    assert scored["parse_failures"] == 3
    assert scored["parse_failure_kinds"] == {
        "invalid_json": 1,
        "no_json_object": 1,
        "no_labels_list": 1,
    }
    assert scored["claims_unlabeled"] == 3 * 2 + (len(items) - 3)  # failed calls, then every c0
    tests = scored["per_type"]["tests_pass"]
    assert (tests["tp"], tests["fn"]) == (0, 8)  # every contradicted test claim missed
    assert scored["label_counts"]["unlabeled"] == scored["claims_unlabeled"]


def test_reply_status() -> None:
    assert e3.reply_status('Sure: {"labels": []}') == "ok"
    assert e3.reply_status("no json") == "no_json_object"
    assert e3.reply_status("{bad}") == "invalid_json"
    assert e3.reply_status('{"labels": {}}') == "no_labels_list"
    assert e3.reply_status("[1, 2]") == "no_json_object"


# Agreement ---------------------------------------------------------------------------------


def test_cohen_kappa_by_hand() -> None:
    pairs = [("a", "a"), ("a", "b"), ("b", "b"), ("b", "b")]
    result = e3.cohen_kappa(pairs)
    # observed 3/4; expected (2/4)(1/4) + (2/4)(3/4) = 0.5; kappa = 0.25 / 0.5 = 0.5
    assert result["observed_agreement"] == 0.75 and result["expected_agreement"] == 0.5
    assert result["kappa"] == pytest.approx(0.5) and result["status"] == "ok"
    same = e3.cohen_kappa([("a", "a"), ("a", "a")])
    assert same["kappa"] is None and same["status"].startswith("undefined")
    assert e3.cohen_kappa([])["status"] == "no claims labeled by both judges"


def test_agreement_is_reported_beside_validity(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    first = e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests))

    def contrarian(run_id: str, cid: str, text: str) -> str | None:
        """SYNTHETIC: flags nothing and omits every file claim."""
        return "supported" if "tests" in text else None

    second = e3.run_judge(e3.JUDGES[1], items, fake_judge(contrarian))
    agreement = e3.agreement([first, second], items)
    assert "never instead" in agreement["note"]
    (pair,) = agreement["pairs"]
    assert pair["judges"] == ["qwen7b-transcript", "granite8b-transcript"]
    assert pair["n_claims"] == 32 and pair["three_way"]["n"] == 16
    assert pair["three_way"]["observed_agreement"] == 0.0
    flag = pair["contradicted_flag"]
    assert flag["n"] == 32 and flag["observed_agreement"] == 0.5
    assert pair["both_flagged"]["claims"] == 0 and pair["both_flagged"]["tp"] == 0
    assert pair["both_flagged"]["precision"]["estimate"] is None
    assert e3.agreement([first], items)["pairs"] == []


# Exploratory analyses ----------------------------------------------------------------------


def test_exploratory_splits_by_arm_family_and_mechanism(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    runs = [e3.run_judge(c, items, fake_judge(flags_tests)) for c in e3.JUDGES]
    classes = {
        ("e1-ma-qwen7b-00", "c0"): mechanism.SAW,
        ("e1-ma-qwen7b-02", "c0"): mechanism.NEVER,
    }
    out = e3.exploratory(runs, items, VALID, classes)
    assert out["label"] == "EXPLORATORY"
    qwen = out["judges"]["qwen7b-transcript"]
    assert set(qwen["by_arm"]) == set(e3.E1_ARMS)
    assert qwen["by_arm"]["ma-qwen7b"]["all_types"]["tp"] == 2
    assert qwen["by_arm"]["ma-qwen7b"]["valid_types"]["claims"] == 4
    family = qwen["by_family"]
    assert family["judge_family"] == "qwen"
    assert (
        family["own"]["all_types"]["claims"] == 16 and family["other"]["all_types"]["claims"] == 16
    )
    by_class = qwen["recall_by_mechanism"]
    assert by_class["status"] == "ok"
    assert by_class["classes"][mechanism.SAW]["contradicted"] == 1
    assert by_class["classes"][mechanism.NEVER]["recall"]["estimate"] == 1.0
    assert by_class["classes"][mechanism.TRUNCATED]["contradicted"] == 0
    assert by_class["unclassified"] == 8 - 2  # contradicted claims mechanism.json lacks
    unread = e3.exploratory(runs, items, None, None)
    assert unread["judges"]["granite8b-transcript"]["recall_by_mechanism"]["status"].startswith(
        "not read"
    )
    assert unread["judges"]["granite8b-transcript"]["by_arm"]["ma-qwen7b"]["valid_types"] is None
    assert e3.mechanism_classes(
        {"claims": [{"run_id": "r", "claim_id": "c0", "class": "never_saw"}]}
    ) == {("r", "c0"): "never_saw"}
    for bad in ({"claims": "x"}, {"claims": [{"run_id": "r", "claim_id": "c0", "class": "odd"}]}):
        with pytest.raises(ValueError, match="mechanism"):
            e3.mechanism_classes(bad)
    twice = {"claims": [{"run_id": "r", "claim_id": "c0", "class": "never_saw"}] * 2}
    with pytest.raises(ValueError, match="twice"):
        e3.mechanism_classes(twice)


# Dry run -----------------------------------------------------------------------------------


def test_plan_calls_counts_without_calling_a_model(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)
    cached_runs = {items[0].run_id}

    def is_cached(request: ModelRequest) -> bool:
        return run_of(request) in cached_runs

    plan = e3.plan_calls(e3.JUDGES, items, is_cached=is_cached, skip={items[1].run_id})
    assert plan["runs"] == len(items) and plan["runs_excluded"] == 1
    first = plan["judges"][0]
    requests = [e3.judge_request(e3.JUDGES[0], i) for i in items if i.run_id != items[1].run_id]
    chars = [sum(len(m["content"]) for m in r.messages) for r in requests]
    n = len(items) - 1
    assert first["calls"] == n and first["cached"] == 1 and first["new"] == n - 1
    assert first["estimated_input_tokens"] == sum(math.ceil(c / e3.CHARS_PER_TOKEN) for c in chars)
    assert first["mean_input_tokens"] == pytest.approx(first["estimated_input_tokens"] / n)
    assert first["max_output_tokens"] == 1024 * n and first["over_context_estimate"] == 0
    assert plan["total_calls"] == 2 * n and plan["total_new"] == 2 * (n - 1)
    tiny = e3.plan_calls(e3.JUDGES, items, context_tokens=10)
    assert tiny["judges"][0]["over_context_estimate"] == len(items)
    assert e3.plan_calls(e3.JUDGES, [])["judges"][0]["mean_input_tokens"] is None


# Confirmatory rules (section 8) ------------------------------------------------------------


def test_confirmatory_problems_cover_every_condition_of_section_8(tmp_path: Path) -> None:
    """Item 20: each condition, alone, blocks a confirmatory artifact."""
    rows = synthetic_e1(tmp_path, synthetic=False)  # SYNTHETIC rows, flag off: gating only
    context = good_context(rows)
    items, runs = judged(context, tmp_path)
    servers = pinned_servers()
    assert e3.confirmatory_problems(context, items, runs=runs, servers=servers) == []
    assert e3.confirmatory_problems(context, items) == []  # before any call

    def problems(**over: Any) -> str:
        return " | ".join(e3.confirmatory_problems(replace(context, **over), items))

    # 1. Frozen, with the LOCK entry committed.
    assert "no preregistration" in problems(prereg=None)
    draft = PreregStatus(FROZEN.path, FROZEN.sha256, False, ("x is not frozen in LOCK.json",))
    assert "preregistration: x is not frozen" in problems(prereg=draft)
    uncommitted = replace(FROZEN, frozen=False, problems=("the LOCK entry is not committed",))
    assert "LOCK entry is not committed" in problems(prereg=uncommitted)
    silent = replace(FROZEN, frozen=False, problems=())
    assert f"preregistration: {FROZEN.path} is not frozen" in problems(prereg=silent)
    # 2. The preregistered sample from the analyzed rows; no --limit.
    assert "no machine-readable sample_runs line" in problems(prereg_lines=(None, SEED))
    assert "no machine-readable sample_seed line" in problems(prereg_lines=(8, None))
    assert "cannot be drawn: the sample size K = 6" in problems(prereg_lines=(6, SEED))
    assert "no judged runs" in " | ".join(e3.confirmatory_problems(context, []))
    assert "the SHA-256 of artifacts/e1/runs.jsonl is unknown" in problems(rows_sha256=None)
    other_seed = e3.draw_sample(rows, 8, 7)
    assert "not the preregistered K = 8 and seed 20261108" in problems(sample=other_seed)
    assert "no sample was drawn" in problems(sample=None)
    assert "--limit" in problems(limit=3)
    assert "not the preregistered sample" in " | ".join(
        e3.confirmatory_problems(context, items[1:])
    )
    assert "records no SHA-256" in problems(analyzed_rows_sha256=None)
    assert "is not the file artifacts/e1/results.json analyzes" in problems(
        analyzed_rows_sha256="f" * 64
    )
    few_arms = synthetic_rows(layout_of(arms=e3.E1_ARMS[:3]), synthetic=False)
    assert "not the four E1 arms" in " | ".join(
        e3.confirmatory_problems(good_context(few_arms), items, runs=runs, servers=servers)
    )
    # 3. Both judges, as configured, with the pinned model file in the server provenance.
    assert "not exactly the preregistered" in problems(configs=e3.JUDGES[:1])
    assert "not exactly the preregistered" in problems(configs=(*e3.JUDGES, e3.JUDGES[0]))
    altered = replace(e3.JUDGES[1], params={"temperature": 0.7, "max_tokens": 1024, "seed": 0})
    assert "not configured as preregistered" in problems(configs=(e3.JUDGES[0], altered))
    for server in ({}, {"model": GRANITE_8B.name, "model_sha256": "0" * 64}):
        found = e3.confirmatory_problems(
            context, items, runs=runs, servers={**servers, "granite8b-transcript": server}
        )
        assert any("pinned model file SHA-256" in p for p in found), server
    # 4. Every sampled run judged by both judges.
    short = [runs[0], replace(runs[1], calls=runs[1].calls[1:])]
    found = e3.confirmatory_problems(context, items, runs=short, servers=servers)
    assert any("did not judge 1 sampled run" in p for p in found)
    found = e3.confirmatory_problems(context, items, runs=runs[:1], servers=servers)
    assert "judge granite8b-transcript did not run" in found
    # 5. Nothing synthetic.
    fake = [runs[0], replace(runs[1], synthetic=True)]
    found = e3.confirmatory_problems(context, items, runs=fake, servers=servers)
    assert any("synthetic judge(s): granite8b-transcript" in p for p in found)
    marked = [replace(items[0], synthetic=True), *items[1:]]
    assert any("synthetic" in p for p in e3.confirmatory_problems(context, marked))
    # 6. The held-out evaluation, and frame rows from the evaluated instrument.
    assert "was not read" in problems(valid_types=None)
    moved = {**TREES, rescore.INSTRUMENT_RECORD_PATHS[0]: "0" * 40}
    elsewhere = rescore.valid_types(seeded_eval({"tests_pass": 10}, trees=moved))
    assert "instrument trees other than the evaluated ones" in problems(valid_types=elsewhere)
    blank = rescore.valid_types(seeded_eval({"tests_pass": 10}, trees={}))
    assert "records no instrument trees" in problems(valid_types=blank)
    dirty_rows = synthetic_rows(synthetic=False, instrument={**INSTRUMENT, "dirty": True})
    assert "instrument_dirty" in " | ".join(
        e3.confirmatory_problems(good_context(dirty_rows), items)
    )
    # 7. Committed analysis code (what git says comes in from the tool).
    assert "SYNTHETIC uncommitted" in problems(code_problems=("SYNTHETIC uncommitted",))


def test_excluded_runs_do_not_block_a_confirmatory_artifact(tmp_path: Path) -> None:
    """Section 8 condition 4: every sampled run judged by both, apart from exclusions."""
    rows = synthetic_e1(tmp_path, synthetic=False)
    context = good_context(rows)
    assert context.sample is not None
    gone = context.sample.run_ids[0]
    exclusions = {gone: ({"judge_id": "granite8b-transcript", "attempts": 3},)}
    context = replace(context, exclusions=exclusions)
    items, runs = judged(context, tmp_path)
    assert all(c.status == e3.EXCLUDED for r in runs for c in r.calls if c.run_id == gone)
    assert e3.confirmatory_problems(context, items, runs=runs, servers=pinned_servers()) == []


# The artifact ------------------------------------------------------------------------------


def test_judges_artifact_contract(tmp_path: Path) -> None:
    rows = synthetic_e1(tmp_path)
    context = good_context(rows, prereg=None, valid_types=VALID)
    assert context.sample is not None
    gone = context.sample.run_ids[1]
    exclusions = {
        gone: (
            {
                "judge_id": "granite8b-transcript",
                "cache_key": "k" * 64,
                "attempts": 3,
                "errors": [{"attempt": 3, "time": "t", "error": "BackendError: SYNTHETIC"}],
            },
        )
    }
    context = replace(context, exclusions=exclusions)
    items, runs = judged(context, tmp_path)
    runs = [replace(runs[0], synthetic=True), runs[1]]
    provenance = {"git_sha": "0" * 40, "command": "test", "created": "2026-11-04"}
    replies = {"path": "artifacts/e3/replies.jsonl", "sha256": "r" * 64, "records": 14}
    artifact = e3.judges_artifact(
        context, items, runs, provenance=provenance, servers={}, replies=replies
    )
    assert artifact["schema"] == "receipts.e3.judges/2" and artifact["experiment"] == "E3"
    assert artifact["confirmatory"] is False and artifact["analysis"] == "exploratory"
    assert artifact["synthetic"] is True and artifact["prereg"] is None
    assert "no preregistration is cited" in artifact["confirmatory_problems"]
    sample = artifact["sample"]
    assert sample["sample_runs"] == 8 and sample["seed"] == SEED and sample["per_arm"] == 2
    assert sample["preregistered"] is True and sample["prereg_sample_runs"] == 8
    assert sample["sampled_run_ids"] == list(context.sample.run_ids)
    assert set(sample["arms"]) == set(e3.E1_ARMS)
    assert artifact["runs"] == {
        "rows": len(rows),
        "frame": 16,
        "sampled": 8,
        "judged": 7,
        "excluded": [gone],
        "limit": None,
        "judges": ["qwen7b-transcript", "granite8b-transcript"],
        "complete": True,
    }
    assert artifact["exclusions"] == [{"run_id": gone, "calls": list(exclusions[gone])}]
    (deviation,) = artifact["deviations"]
    assert deviation["kind"] == "excluded_unservable" and deviation["run_id"] == gone
    assert deviation["prereg_section"] == "7"
    assert all(item["run_id"] != gone for item in artifact["items"])
    assert len(artifact["items"]) == 14
    first = artifact["items"][0]
    assert set(first) == {
        "run_id",
        "task_id",
        "config_id",
        "claim_id",
        "claim_type",
        "truth",
        "labels",
    }
    assert first["labels"] == {
        "qwen7b-transcript": "contradicted",
        "granite8b-transcript": "contradicted",
    }
    calls = artifact["calls"]
    assert len(calls) == 16 and sum(1 for c in calls if c["status"] == e3.EXCLUDED) == 2
    assert {c["judge_id"] for c in calls if not c["served"]} == {
        "qwen7b-transcript",
        "granite8b-transcript",
    }
    assert artifact["claim_types"]["tests_pass"] == {
        "claims": 7,
        "contradicted": sum(
            1 for i in items if i.run_id != gone and i.truth["c0"] == "contradicted"
        ),
        "valid_type": True,
    }
    assert artifact["valid_claim_types"]["types"] == ["tests_pass"]
    assert artifact["replies"] == replies
    assert [j["judge_id"] for j in artifact["judges"]] == [c.judge_id for c in e3.JUDGES]
    for judge in artifact["judges"]:
        assert judge["calls"] == 7 and judge["calls_excluded"] == 1
        assert all(
            isinstance(judge["per_type"][t][k], int)
            for t in judge["per_type"]
            for k in ("tp", "fp", "fn", "tn")
        )
    assert artifact["agreement"]["pairs"][0]["n_claims"] == 14
    assert artifact["exploratory"]["label"] == "EXPLORATORY"
    assert artifact["provenance"]["git_sha"] == "0" * 40
    assert artifact["provenance"]["model_servers"] == {}
    json.dumps(artifact, allow_nan=False)
    with pytest.raises(ConfirmatoryRefusedError, match="no preregistration"):
        e3.judges_artifact(context, items, runs, provenance=provenance, confirmatory=True)


def test_completeness_needs_the_whole_sample_and_both_judges(tmp_path: Path) -> None:
    rows = synthetic_e1(tmp_path)
    context = good_context(rows)
    items, runs = judged(context, tmp_path)
    provenance: dict[str, Any] = {}

    def complete(
        context: e3.Context, items: Sequence[e3.JudgeItem], runs: Sequence[e3.JudgeRun]
    ) -> bool:
        artifact = e3.judges_artifact(context, items, runs, provenance=provenance)
        return bool(artifact["runs"]["complete"])

    assert complete(context, items, runs) is True
    assert complete(replace(context, limit=3), items[:3], runs) is False
    assert complete(context, items[1:], runs) is False  # not the whole sample, even unlimited
    assert complete(replace(context, configs=e3.JUDGES[:1]), items, runs[:1]) is False
    short = [runs[0], replace(runs[1], calls=runs[1].calls[:-1])]
    assert complete(context, items, short) is False
    assert complete(replace(context, sample=None), items, runs) is False
    assert complete(context, items, [*runs, runs[0]]) is False  # a judge twice


def test_a_short_arm_is_a_deviation_in_the_artifact(tmp_path: Path) -> None:
    """Section 3: an arm's shortfall is reported as a deviation, not made up elsewhere."""
    layout = layout_of()
    layout["ma-qwen1.5b"] = ["claims", "no_report"]  # one eligible run, K / 4 = 2
    rows = synthetic_e1(tmp_path, layout)
    context = good_context(rows)
    items, runs = judged(context, tmp_path)
    artifact = e3.judges_artifact(context, items, runs, provenance={})
    (deviation,) = artifact["deviations"]
    assert deviation["kind"] == "sample_shortfall" and deviation["prereg_section"] == "3"
    assert (deviation["config_id"], deviation["eligible"], deviation["shortfall"]) == (
        "ma-qwen1.5b",
        1,
        1,
    )
    assert deviation["per_arm"] == 2 and "not made up from other arms" in deviation["detail"]
    assert artifact["sample"]["shortfall"] == 1 and artifact["runs"]["sampled"] == 7
    assert artifact["runs"]["complete"] is True  # the whole (short) sample was judged


def test_items_without_claims_make_no_call() -> None:
    """Library callers may pass a run without claims: no call, no exclusion, no estimate."""
    empty = e3.JudgeItem("r", "t", "ma-qwen7b", "qwen", False, (), (), {})
    assert e3.run_judge(e3.JUDGES[0], [empty], fake_judge(flags_tests)).calls == ()
    key = "a" * 64
    entries = [{"cache_key": key}] * 3
    assert e3.unservable_calls(e3.JUDGES, [empty], entries) == {}
    plan = e3.plan_calls(e3.JUDGES, [empty])
    assert plan["runs"] == 1 and plan["total_calls"] == 0 and plan["runs_excluded"] == 0


def test_the_artifact_is_confirmatory_only_when_every_condition_holds(tmp_path: Path) -> None:
    rows = synthetic_e1(tmp_path, synthetic=False)  # SYNTHETIC rows, flag off: gating only
    context = good_context(rows)
    items, runs = judged(context, tmp_path)
    servers = pinned_servers()
    artifact = e3.judges_artifact(
        context, items, runs, provenance={}, servers=servers, confirmatory=True
    )
    assert artifact["confirmatory"] is True and artifact["analysis"] == "confirmatory"
    assert artifact["prereg"] == FROZEN.path and artifact["prereg_sha256"] == FROZEN.sha256
    assert artifact["confirmatory_problems"] == []
    with pytest.raises(ConfirmatoryRefusedError, match="pinned model file"):
        e3.judges_artifact(context, items, runs, provenance={}, servers={}, confirmatory=True)


def test_reply_records_hold_every_served_reply(tmp_path: Path) -> None:
    """Item 22: judge id, run id, cache key, reply text, parse status, finish reason, tokens."""
    rows = synthetic_e1(tmp_path)
    context = good_context(rows)
    assert context.sample is not None
    gone = context.sample.run_ids[0]
    items = e3.load_items(rows, tmp_path / RUNS, tmp_path, context.sample.run_ids)
    runs = [
        e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests)),
        e3.run_judge(e3.JUDGES[1], items, fake_judge(flags_tests), skip={gone}),
    ]
    records = e3.reply_records(runs, excluded={gone})
    assert len(records) == 2 * len(items) - 1
    first = records[0]
    assert set(first) == {
        "judge_id",
        "run_id",
        "cache_key",
        "cache_hit",
        "text",
        "status",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "wall_s",
        "excluded",
    }
    assert first["judge_id"] == "qwen7b-transcript" and first["run_id"] == items[0].run_id
    assert first["cache_key"] == e3.judge_request(e3.JUDGES[0], items[0]).cache_key()
    assert json.loads(first["text"])["labels"][0] == {"id": "c0", "label": "contradicted"}
    assert (first["status"], first["finish_reason"]) == ("ok", "stop")
    assert (first["input_tokens"], first["output_tokens"]) == (100, 20)
    assert first["excluded"] is True  # the first judge answered for the excluded run
    assert sum(1 for r in records if r["excluded"]) == 1


def test_model_client_cache_means_a_banked_call_is_never_rerun(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = all_items(tmp_path)

    class Counting:
        """SYNTHETIC backend: counts calls and answers like ``flags_tests``."""

        name = "local"
        is_claude = False

        def __init__(self) -> None:
            self.calls = 0
            self.judge = fake_judge(flags_tests)

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            return self.judge(request)

    backend = Counting()
    client = ModelClient(tmp_path, {"local": backend}, tmp_path / "cache", env={}, guard_check=list)
    first = e3.run_judge(e3.JUDGES[0], items, client.complete)
    second = e3.run_judge(e3.JUDGES[0], items, client.complete)
    assert backend.calls == len(items)
    assert not any(c.cache_hit for c in first.calls) and all(c.cache_hit for c in second.calls)
    assert [c.labels for c in first.calls] == [c.labels for c in second.calls]


def test_analyzed_rows_digest_is_read_from_the_e1_results() -> None:
    digest = "a" * 64
    results = {"provenance": {"inputs": {"artifacts/e1/runs.jsonl": digest}}}
    assert e3.analyzed_rows_sha256(results) == digest
    for bad in (
        {},
        {"provenance": []},
        {"provenance": {"inputs": {}}},
        [],
        {"provenance": {"inputs": {ROWS: "x"}}},
    ):
        assert e3.analyzed_rows_sha256(bad) is None


def test_valid_types_type_is_the_rescore_one() -> None:
    assert e3.ValidTypes is ValidTypes
