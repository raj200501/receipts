"""Tests for receipts.evaluation.e3 and tools/run_judges.py with SYNTHETIC runs and judges.

The E1 runs are generated here (labeled synthetic) and the judges are fake completion
functions that answer from the claim text (labeled synthetic too); no model is called.
Nothing computed here is a result of any study.
"""

from __future__ import annotations

import contextlib
import json
import math
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

import run_judges
from receipts.analysis import rate_with_ci
from receipts.client.models import GRANITE_8B, LOCAL_MODELS, QWEN_CODER_7B
from receipts.client.wrapper import ModelClient, ModelRequest, ModelResponse
from receipts.evaluation import e3
from receipts.evaluation.judges import JudgeConfig
from receipts.study.aggregate import e1_rows, write_jsonl
from receipts.study.results_e4 import ConfirmatoryRefusedError, PreregStatus, ValidTypes

SENTINEL = "LEDGER-SENTINEL-never-shown-to-a-judge"
ROWS = "artifacts/e1/runs.jsonl"
RUNS = "artifacts/studies/e1/runs"
OUT = "artifacts/e3/judges.json"


def claim(cid: str, ctype: str, text: str, verdict: str) -> dict[str, Any]:
    """One SYNTHETIC banked claim (``Claim.to_dict`` plus the ledger verdict)."""
    return {
        "claim_id": cid,
        "type": ctype,
        "text": text,
        "span": [0, len(text)],
        "params": {},
        "negated": False,
        "extractor": "pattern",
        "verdict": verdict,
    }


def synthetic_e1(root: Path, n_runs: int = 6) -> list[dict[str, Any]]:
    """SYNTHETIC E1 runs under ``root``: run.json, transcript.json, ledger, rows.

    Run i says "all tests pass" (ledger: contradicted for even i) and "updated calc.py"
    (ledger: supported, except unverifiable for i divisible by 3). Run 4 has no report.
    The ledger and verification files hold a sentinel the judges must never see.
    """
    records = []
    for i in range(n_runs):
        run_id = f"e1-{i:03d}-ma-qwen7b"
        reported = i != 4
        claims = (
            [
                claim(
                    "c0",
                    "tests_pass",
                    "SYNTHETIC: all tests pass.",
                    ("supported", "contradicted")[i % 2 == 0],
                ),
                claim(
                    "c1",
                    "file_modified",
                    "SYNTHETIC: updated calc.py.",
                    ("supported", "unverifiable")[i % 3 == 0],
                ),
            ]
            if reported
            else []
        )
        record = {
            "run_id": run_id,
            "task_id": f"syn-task{i % 3}",
            "config_id": "ma-qwen7b",
            "model": QWEN_CODER_7B.name,
            "family": "qwen",
            "conditions": {"M1": "attainable"},
            "seed": i,
            "report": "SYNTHETIC: all tests pass. SYNTHETIC: updated calc.py." if reported else "",
            "stop_reason": "finished" if reported else "max_turns",
            "success_reported": reported,
            "ground_truth_success": i % 2 == 1,
            "false_success": reported and i % 2 == 0,
            "claims": claims,
            "omissions": 0,
            "synthetic": True,
        }
        records.append(record)
        run_dir = root / RUNS / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        transcript = {
            "messages": [
                {"role": "system", "content": "SYNTHETIC system prompt"},
                {"role": "user", "content": f"SYNTHETIC task for {run_id}"},
                {"role": "assistant", "content": "SYNTHETIC action: run_tests"},
                {"role": "user", "content": "Result of run_tests:\n1 failed, 3 passed"},
            ],
            "drafts": [],
            "protocol_errors": 0,
        }
        (run_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
        (run_dir / "ledger.jsonl").write_text(json.dumps({"data": SENTINEL}) + "\n", "utf-8")
        (run_dir / "verification.json").write_text(json.dumps({"x": SENTINEL}), "utf-8")
    write_jsonl(root / ROWS, e1_rows(records))
    return records


def rows(root: Path) -> list[dict[str, Any]]:
    text = (root / ROWS).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def listing(request: ModelRequest) -> list[tuple[str, str]]:
    """The ``(claim_id, text)`` pairs of a judge request's claim list."""
    body = request.messages[-1]["content"].split("Claims from the final report:\n", 1)[1]
    pairs: list[tuple[str, str]] = []
    for line in body.splitlines():
        cid, text = line.split(": ", 1)
        pairs.append((cid, text))
    return pairs


def fake_judge(
    label_for: Callable[[str, str], str | None], seen: list[ModelRequest] | None = None
) -> e3.Completion:
    """A SYNTHETIC judge: labels each listed claim with ``label_for(claim_id, text)``."""

    def complete(request: ModelRequest) -> ModelResponse:
        if seen is not None:
            seen.append(request)
        labels = [
            {"id": cid, "label": label}
            for cid, text in listing(request)
            if (label := label_for(cid, text)) is not None
        ]
        return ModelResponse(json.dumps({"labels": labels}), 100, 20, 0.5, "stop")

    return complete


def flags_tests(cid: str, text: str) -> str:
    """SYNTHETIC rule: every "all tests pass" claim is contradicted, the rest supported."""
    return "contradicted" if "tests pass" in text else "supported"


def items_for(root: Path) -> list[e3.JudgeItem]:
    return e3.load_items(rows(root), root / RUNS, root)


# --------------------------------------------------------------------------- configs


def test_default_judges_are_the_larger_model_of_each_family() -> None:
    assert [j.judge_id for j in e3.JUDGES] == ["qwen7b-transcript", "granite8b-transcript"]
    assert [j.model for j in e3.JUDGES] == [QWEN_CODER_7B.name, GRANITE_8B.name]
    assert {LOCAL_MODELS[j.model].family for j in e3.JUDGES} == {"qwen", "granite"}
    assert all(j.backend == "local" and j.params["temperature"] == 0 for j in e3.JUDGES)
    described = e3.describe_config(e3.JUDGES[0])
    assert described["model_pin"]["sha256"] == QWEN_CODER_7B.sha256
    assert len(described["system_prompt_sha256"]) == 64
    assert "never the ledger" in described["reads"]
    other = e3.describe_config(JudgeConfig("x", "claude", "sonnet"))
    assert other["model_pin"] is None


# --------------------------------------------------------------------------- items


def test_items_carry_the_transcript_and_claims_but_never_the_ledger(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = items_for(tmp_path)
    assert [i.run_id for i in items] == [f"e1-{i:03d}-ma-qwen7b" for i in (0, 1, 2, 3, 5)]
    first = items[0]
    assert [c.claim_id for c in first.claims] == ["c0", "c1"]
    assert first.truth == {"c0": "contradicted", "c1": "unverifiable"}
    assert first.claim_types == {"c0": "tests_pass", "c1": "file_modified"}
    assert first.synthetic is True and first.transcript[1]["content"].startswith("SYNTHETIC task")
    assert set(first.sources) == {
        f"{RUNS}/{first.run_id}/run.json",
        f"{RUNS}/{first.run_id}/transcript.json",
    }
    seen: list[ModelRequest] = []
    for config in e3.JUDGES:
        e3.run_judge(config, items, fake_judge(flags_tests, seen))
    assert len(seen) == 2 * len(items)
    for request in seen:
        text = json.dumps([dict(m) for m in request.messages])
        assert SENTINEL not in text and "unverifiable" not in text.split("Claims from")[1]
        assert request.kind == "local_call" and request.purpose.startswith("e3:judge ")


def test_items_reject_inconsistent_banking(tmp_path: Path) -> None:
    records = synthetic_e1(tmp_path)
    run_dir = tmp_path / RUNS / str(records[0]["run_id"])
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    record["claims"] = record["claims"][:1]
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match=r"differ from its runs\.jsonl row"):
        items_for(tmp_path)
    record["claims"] = [dict(c, verdict="supported") for c in records[0]["claims"]]
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match=r"differ from its runs\.jsonl row"):
        items_for(tmp_path)
    (run_dir / "run.json").write_text(json.dumps(records[0]), encoding="utf-8")
    (run_dir / "transcript.json").unlink()
    with pytest.raises(ValueError, match=r"transcript\.json"):
        items_for(tmp_path)


# --------------------------------------------------------------------------- scoring


def test_scores_per_type_with_wilson_intervals(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = items_for(tmp_path)
    run = e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests), synthetic=True)
    scored = e3.score_judge(run, items)
    tests = scored["per_type"]["tests_pass"]
    # Runs 0, 2 have contradicted test claims; 1, 3, 5 supported ones; the judge flags all.
    assert (tests["tp"], tests["fp"], tests["fn"], tests["tn"]) == (2, 3, 0, 0)
    expected = rate_with_ci(2, 5)
    assert tests["precision"]["estimate"] == pytest.approx(expected.estimate)
    assert tests["precision"]["ci_low"] == pytest.approx(expected.ci_low)
    assert tests["recall"]["estimate"] == 1.0
    files = scored["per_type"]["file_modified"]
    assert (files["tp"], files["fp"], files["fn"]) == (0, 0, 0)
    assert files["precision"]["estimate"] is None
    assert files["precision"]["status"] == "undefined: the judge flagged no claim of this type"
    assert files["recall"]["status"] == "undefined: the ledger contradicts no claim of this type"
    assert scored["overall"]["tp"] == 2 and scored["overall"]["fp"] == 3
    assert scored["calls"] == len(items) and scored["parse_failures"] == 0
    assert scored["claims"] == 10 and scored["claims_unlabeled"] == 0
    assert scored["label_counts"] == {"contradicted": 5, "supported": 5}
    assert scored["synthetic"] is True and scored["usage"]["input_tokens"] == 100 * len(items)
    assert "overall_g5_valid" not in scored
    valid = ValidTypes(("tests_pass",), {})
    with_valid = e3.score_judge(run, items, valid)
    assert with_valid["overall_g5_valid"]["tp"] == 2
    assert with_valid["per_type"]["tests_pass"]["g5_valid"] is True
    assert with_valid["per_type"]["file_modified"]["g5_valid"] is False
    assert json.loads(json.dumps(scored, allow_nan=False)) == scored


def test_parse_failures_and_omitted_labels_count_against_recall(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = items_for(tmp_path)

    def sloppy(request: ModelRequest) -> ModelResponse:
        """SYNTHETIC judge with three kinds of unparseable reply and one partial reply."""
        run_id = request.purpose.rsplit(" ", 1)[1]
        if run_id.endswith("000-ma-qwen7b"):
            return ModelResponse("I think they are fine.", 50, 5, 0.1, "stop")
        if run_id.endswith("001-ma-qwen7b"):
            return ModelResponse('{"labels": [oops]}', 50, 5, 0.1, "stop")
        if run_id.endswith("002-ma-qwen7b"):
            return ModelResponse('{"verdicts": []}', 50, 5, 0.1, "stop")
        only_c1 = [{"id": "c1", "label": "Supported"}, {"id": "c9", "label": "contradicted"}]
        return ModelResponse(json.dumps({"labels": only_c1}), 50, 5, 0.1, "stop")

    scored = e3.score_judge(e3.run_judge(e3.JUDGES[1], items, sloppy), items)
    assert scored["parse_failures"] == 3
    assert scored["parse_failure_kinds"] == {
        "invalid_json": 1,
        "no_json_object": 1,
        "no_labels_list": 1,
    }
    assert scored["claims_unlabeled"] == 3 * 2 + 2  # failed calls, then c0 of runs 3 and 5
    tests = scored["per_type"]["tests_pass"]
    assert (tests["tp"], tests["fn"]) == (0, 2)  # runs 0 and 2 were contradicted, never flagged
    assert scored["label_counts"]["unlabeled"] == 8


def test_reply_status() -> None:
    assert e3.reply_status('Sure: {"labels": []}') == "ok"
    assert e3.reply_status("no json") == "no_json_object"
    assert e3.reply_status("{bad}") == "invalid_json"
    assert e3.reply_status('{"labels": {}}') == "no_labels_list"
    assert e3.reply_status("[1, 2]") == "no_json_object"


# --------------------------------------------------------------------------- agreement


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
    items = items_for(tmp_path)
    first = e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests))

    def contrarian(cid: str, text: str) -> str | None:
        """SYNTHETIC: flags nothing and omits every file claim."""
        return "supported" if "tests" in text else None

    second = e3.run_judge(e3.JUDGES[1], items, fake_judge(contrarian))
    agreement = e3.agreement([first, second], items)
    assert "never instead" in agreement["note"]
    (pair,) = agreement["pairs"]
    assert pair["judges"] == ["qwen7b-transcript", "granite8b-transcript"]
    assert pair["n_claims"] == 10 and pair["three_way"]["n"] == 5
    assert pair["three_way"]["observed_agreement"] == 0.0
    flag = pair["contradicted_flag"]
    assert flag["n"] == 10 and flag["observed_agreement"] == 0.5
    assert pair["both_flagged"] == {
        "claims": 0,
        "tp": 0,
        "fp": 0,
        "precision": pair["both_flagged"]["precision"],
    }
    assert e3.agreement([first], items)["pairs"] == []


# --------------------------------------------------------------------------- dry run


def test_plan_calls_counts_without_calling_a_model(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = items_for(tmp_path)
    cached_runs = {items[0].run_id}

    def is_cached(request: ModelRequest) -> bool:
        return request.purpose.rsplit(" ", 1)[1] in cached_runs

    plan = e3.plan_calls(e3.JUDGES, items, is_cached=is_cached)
    assert plan["runs"] == len(items) and plan["runs_without_claims"] == 0
    first = plan["judges"][0]
    requests = [e3.judge_request(e3.JUDGES[0], i) for i in items]
    chars = [sum(len(m["content"]) for m in r.messages) for r in requests]
    assert first["calls"] == len(items) and first["cached"] == 1 and first["new"] == len(items) - 1
    assert first["estimated_input_tokens"] == sum(math.ceil(c / e3.CHARS_PER_TOKEN) for c in chars)
    assert first["max_output_tokens"] == 1024 * len(items)
    assert first["over_context_estimate"] == 0
    assert plan["total_calls"] == 2 * len(items) and plan["total_new"] == 2 * (len(items) - 1)
    empty = e3.JudgeItem("r", "t", "c", False, (), (), {}, {}, {})
    assert e3.plan_calls(e3.JUDGES, [empty])["runs_without_claims"] == 1
    tiny = e3.plan_calls(e3.JUDGES, items, context_tokens=10)
    assert tiny["judges"][0]["over_context_estimate"] == len(items)


# --------------------------------------------------------------------------- artifact


def test_judges_artifact_contract(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = items_for(tmp_path)
    runs = [
        e3.run_judge(e3.JUDGES[0], items, fake_judge(flags_tests), synthetic=True),
        e3.run_judge(e3.JUDGES[1], items, fake_judge(lambda c, t: "supported"), synthetic=True),
    ]
    provenance = {"git_sha": "0" * 40, "command": "test", "created": "2026-11-04"}
    artifact = e3.judges_artifact(
        runs, items, included_runs=len(items), limit=None, valid_types=None, provenance=provenance
    )
    assert artifact["schema"] == "receipts.e3.judges/1"
    assert artifact["confirmatory"] is False and artifact["synthetic"] is True
    assert artifact["analysis"] == "exploratory" and artifact["prereg"] is None
    assert len(artifact["judges"]) == 2
    for judge in artifact["judges"]:
        assert judge["judge_id"] and judge["model"] and judge["config"]["judge_id"]
        for counts in judge["per_type"].values():
            assert all(isinstance(counts[k], int) for k in ("tp", "fp", "fn"))
    assert artifact["runs"] == {
        "included": len(items),
        "judged": len(items),
        "without_claims": 0,
        "limit": None,
        "complete": True,
    }
    assert artifact["claim_types"]["tests_pass"] == {
        "claims": 5,
        "contradicted": 2,
        "g5_valid": None,
    }
    assert len(artifact["items"]) == 10
    labels = artifact["items"][0]["labels"]
    assert labels == {"qwen7b-transcript": "contradicted", "granite8b-transcript": "supported"}
    assert artifact["agreement"]["pairs"][0]["judges"] == [
        "qwen7b-transcript",
        "granite8b-transcript",
    ]
    assert artifact["calls"][0]["status"] == "ok"
    assert artifact["provenance"]["git_sha"] == "0" * 40
    json.dumps(artifact, allow_nan=False)
    partial = e3.judges_artifact(
        runs, items[:2], included_runs=len(items), limit=2, valid_types=None, provenance=provenance
    )
    assert partial["runs"]["complete"] is False and partial["runs"]["limit"] == 2
    frozen = PreregStatus("prereg/0003-e3.md", "a" * 64, True, (), "2026-11-04")
    with pytest.raises(ConfirmatoryRefusedError, match="synthetic"):
        e3.judges_artifact(
            runs,
            items,
            included_runs=len(items),
            limit=None,
            valid_types=None,
            provenance=provenance,
            prereg=frozen,
            confirmatory=True,
        )
    assert e3.confirmatory_problems(None, []) == [
        "no preregistration is cited (E3 has none yet)",
        "no judged runs",
    ]
    draft = PreregStatus("prereg/0003-e3.md", "a" * 64, False, ("not frozen",))
    assert e3.confirmatory_problems(draft, items, limit=2)[:2] == [
        "preregistration: not frozen",
        "a --limit run judges only part of E1",
    ]


def test_model_client_cache_means_a_banked_call_is_never_rerun(tmp_path: Path) -> None:
    synthetic_e1(tmp_path)
    items = items_for(tmp_path)

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


# --------------------------------------------------------------------------- the tool


@contextlib.contextmanager
def fake_serve(
    config: JudgeConfig, args: Any, pending: int
) -> Iterator[tuple[e3.Completion, Mapping[str, Any]]]:
    """SYNTHETIC stand-in for ``run_judges.serve``: no server, a fake judge."""
    yield fake_judge(flags_tests), {"model": config.model, "synthetic_judge": True}


def test_tool_dry_run_calls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)

    def refuse(*_: Any) -> Any:
        raise AssertionError("a dry run must not start a server or call a model")

    monkeypatch.setattr(run_judges, "serve", refuse)
    assert run_judges.main(["--root", str(tmp_path), "--dry-run", "--limit", "3"]) == 0
    out = capsys.readouterr().out
    assert "dry run: 3 of 5 included E1 runs" in out
    assert "qwen7b-transcript" in out and "granite8b-transcript" in out
    assert not (tmp_path / "artifacts" / "e3" / "judges.json").exists()


def test_tool_writes_judges_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert (
        run_judges.main(
            ["--root", str(tmp_path), "--judges", "qwen7b-transcript,granite8b-transcript"]
        )
        == 0
    )
    data = json.loads((tmp_path / "artifacts" / "e3" / "judges.json").read_text(encoding="utf-8"))
    assert [j["judge_id"] for j in data["judges"]] == ["qwen7b-transcript", "granite8b-transcript"]
    assert data["synthetic"] is True and data["runs"]["complete"] is True
    prov = data["provenance"]
    assert prov["git_sha"] and prov["command"].startswith("python tools/run_judges.py")
    assert f"{ROWS}" in prov["inputs"] and all(len(v) == 64 for v in prov["inputs"].values())
    assert not any("ledger" in rel or "verification" in rel for rel in prov["inputs"])
    assert prov["model_servers"]["qwen7b-transcript"]["synthetic_judge"] is True
    assert (tmp_path / "runs" / "e3" / "pid").is_file()
    assert "E3: wrote" in capsys.readouterr().out
    assert run_judges.main(["--root", str(tmp_path), "--judges", "nobody"]) == 2
    assert "unknown judge" in capsys.readouterr().err


def test_tool_serves_banked_calls_from_the_cache_without_a_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)
    monkeypatch.delenv("RECEIPTS_OFFLINE", raising=False)
    cache = tmp_path / "runs" / "cache"
    items = items_for(tmp_path)
    judge = fake_judge(flags_tests)
    for item in items:  # bank SYNTHETIC responses exactly where ModelClient looks
        request = e3.judge_request(e3.JUDGES[0], item)
        path = run_judges.cache_path(cache, request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(judge(request).to_dict()), encoding="utf-8")
    args = ["--root", str(tmp_path), "--judges", "qwen7b-transcript"]
    assert run_judges.main([*args, "--dry-run"]) == 0
    assert f"{len(items)} cached, 0 new" in capsys.readouterr().out
    one_judge = tmp_path / "one-judge.json"  # a partial run never writes the default path
    assert run_judges.main([*args, "--out", str(one_judge)]) == 0
    data = json.loads(one_judge.read_text(encoding="utf-8"))
    assert data["judges"][0]["usage"]["cache_hits"] == len(items)
    assert data["provenance"]["model_servers"]["qwen7b-transcript"]["started"] is False
    assert data["provenance"]["cache_dir"] == "runs/cache"
    usage = (tmp_path / "artifacts" / "usage" / "ledger.jsonl").read_text(encoding="utf-8")
    assert len(usage.splitlines()) == len(items)


def test_tool_refuses_confirmatory_and_missing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert run_judges.main(["--root", str(tmp_path), "--confirmatory"]) == 1
    assert "refusing a confirmatory E3 artifact" in capsys.readouterr().err
    (tmp_path / ROWS).unlink()
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "runs.jsonl" in capsys.readouterr().err


def test_tool_reads_the_seeded_evaluation_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synthetic_e1(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    seeded = tmp_path / "artifacts" / "e0" / "seeded_eval.json"
    seeded.parent.mkdir(parents=True)
    items = [
        {
            "report_id": f"r{i}",
            "claim_type": "tests_pass",
            "gold_verdict": "supported",
            "pred_verdict": "supported",
        }
        for i in range(5)
    ]
    seeded.write_text(json.dumps({"split": "heldout", "items": items}), encoding="utf-8")
    first_two = tmp_path / "first-two.json"  # a partial run never writes the default path
    assert run_judges.main(["--root", str(tmp_path), "--limit", "2", "--out", str(first_two)]) == 0
    data = json.loads(first_two.read_text(encoding="utf-8"))
    assert data["valid_claim_types"]["types"] == ["tests_pass"]
    assert data["claim_types"]["tests_pass"]["g5_valid"] is True
    assert data["runs"]["complete"] is False and data["runs"]["judged"] == 2
    assert "artifacts/e0/seeded_eval.json" in data["provenance"]["inputs"]


def test_tool_reports_failed_calls_and_cites_a_prereg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)

    @contextlib.contextmanager
    def broken(
        config: JudgeConfig, args: Any, pending: int
    ) -> Iterator[tuple[e3.Completion, Mapping[str, Any]]]:
        """SYNTHETIC: the judge's server fails to start."""
        raise RuntimeError("model server exited early")
        yield fake_judge(flags_tests), {}  # pragma: no cover - never reached

    monkeypatch.setattr(run_judges, "serve", broken)
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "a judge call failed (model server exited early)" in capsys.readouterr().err
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    (tmp_path / "prereg").mkdir()
    (tmp_path / "prereg" / "0003-e3-judges.md").write_text("# SYNTHETIC draft\n", "utf-8")
    assert run_judges.main(["--root", str(tmp_path), "--prereg", "prereg/0003-e3-judges.md"]) == 0
    data = json.loads((tmp_path / "artifacts" / "e3" / "judges.json").read_text(encoding="utf-8"))
    assert data["prereg"] == "prereg/0003-e3-judges.md" and data["confirmatory"] is False
    assert "prereg/0003-e3-judges.md" in data["provenance"]["inputs"]


def test_tool_never_writes_a_partial_artifact_to_the_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review fix: --limit, or not every judge, needs --out elsewhere; nothing runs first."""
    synthetic_e1(tmp_path)
    default = tmp_path / OUT
    default.parent.mkdir(parents=True)
    # A SYNTHETIC placeholder standing for a complete judges.json banked earlier.
    placeholder = '{"SYNTHETIC": "placeholder for a complete artifact"}\n'
    default.write_text(placeholder, encoding="utf-8")

    def refuse(*_: Any) -> Any:
        raise AssertionError("a refused run must not start a server or call a model")

    monkeypatch.setattr(run_judges, "serve", refuse)
    root = ["--root", str(tmp_path)]
    for extra in (
        ["--limit", "2"],
        ["--judges", "qwen7b-transcript"],
        ["--judges", "granite8b-transcript", "--limit", "9"],
        ["--limit", "2", "--out", str(default)],
    ):
        assert run_judges.main([*root, *extra]) == 2, extra
        err = capsys.readouterr().err
        assert "a partial run" in err and "--out" in err and OUT in err
    twice = ["--judges", "qwen7b-transcript,qwen7b-transcript", "--out", str(tmp_path / "x.json")]
    assert run_judges.main([*root, *twice]) == 2
    assert "named more than once: qwen7b-transcript" in capsys.readouterr().err
    assert default.read_text(encoding="utf-8") == placeholder
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    elsewhere = tmp_path / "partial" / "judges.json"
    partial = ["--judges", "qwen7b-transcript", "--limit", "2", "--out", str(elsewhere)]
    assert run_judges.main([*root, *partial]) == 0
    data = json.loads(elsewhere.read_text(encoding="utf-8"))
    assert [j["judge_id"] for j in data["judges"]] == ["qwen7b-transcript"]
    assert data["runs"]["complete"] is False
    assert default.read_text(encoding="utf-8") == placeholder
    # Every judge, in any order and without --limit, is a full run: it may write the default.
    assert run_judges.main([*root, "--judges", "granite8b-transcript,qwen7b-transcript"]) == 0
    full = json.loads(default.read_text(encoding="utf-8"))
    assert full["runs"]["complete"] is True and len(full["judges"]) == 2


def test_tool_never_replaces_a_confirmatory_artifact_with_an_exploratory_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review fix (the same guard as analyze_e4): a confirmatory judges.json is kept."""
    synthetic_e1(tmp_path)
    default = tmp_path / OUT
    default.parent.mkdir(parents=True)
    # A SYNTHETIC placeholder standing for a banked confirmatory artifact.
    placeholder = '{"confirmatory": true, "SYNTHETIC": "placeholder"}\n'
    default.write_text(placeholder, encoding="utf-8")

    def refuse(*_: Any) -> Any:
        raise AssertionError("a refused run must not start a server or call a model")

    monkeypatch.setattr(run_judges, "serve", refuse)
    assert run_judges.main(["--root", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "holds a confirmatory artifact" in err and "--confirmatory" in err
    assert default.read_text(encoding="utf-8") == placeholder
    every = [j.judge_id for j in e3.JUDGES]
    check = run_judges.output_problem
    assert check(tmp_path, default, judges=every, limit=None, confirmatory=True) is None
    assert check(tmp_path, tmp_path / "new.json", judges=every[:1], limit=3) is None
    default.write_text('{"confirmatory": false}\n', encoding="utf-8")
    assert check(tmp_path, default, judges=every, limit=None) is None


def test_tool_rejects_a_seeded_evaluation_that_is_not_held_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    seeded = tmp_path / "artifacts" / "e0" / "seeded_eval.json"
    seeded.parent.mkdir(parents=True)
    seeded.write_text(json.dumps({"split": "dev", "items": []}), encoding="utf-8")
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "held-out" in capsys.readouterr().err
    assert not (tmp_path / "artifacts" / "e3" / "judges.json").exists()
