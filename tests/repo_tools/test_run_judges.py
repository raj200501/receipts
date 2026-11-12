"""Tests for tools/run_judges.py with SYNTHETIC E1 runs and SYNTHETIC judges.

No model is called and no server starts: ``run_judges.serve`` is replaced by fakes that
answer from the claim text. The E1 runs come from the SYNTHETIC builders of
``tests/evaluation/test_e3.py``. Nothing computed here is a result of any study; the one
artifact marked confirmatory is written in a scratch repository from SYNTHETIC rows with
the synthetic flag off, only to test the gating.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import prereg
import run_judges
from receipts.client.backends import BackendError
from receipts.client.models import LOCAL_MODELS
from receipts.client.wrapper import ClientRefusedError, ModelRequest, ModelResponse
from receipts.evaluation import e3
from receipts.evaluation.judges import JudgeConfig
from receipts.report.derived import comparable
from receipts.study import results_e4
from tests.evaluation.test_e3 import (
    RUNS,
    SEED,
    fake_judge,
    flags_tests,
    read_rows,
    run_of,
    seeded_eval,
    synthetic_e1,
)

ROWS = "artifacts/e1/runs.jsonl"
OUT = "artifacts/e3/judges.json"
REPLIES = "artifacts/e3/replies.jsonl"
FAILURE_LOG = "runs/e3/failures.jsonl"
PREREG = "prereg/0003-e3-judges.md"
Commit = Callable[[Path, str], str]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_prereg(root: Path, k: int | str = 8, seed: int | str = SEED) -> Path:
    """A SYNTHETIC preregistration with the two machine-readable lines of section 3."""
    path = root / PREREG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# SYNTHETIC E3 preregistration for tests\n\nStatus: FROZEN (SYNTHETIC)\n\n"
        f"- sample_runs: {k}\n- sample_seed: {seed}\n",
        encoding="utf-8",
    )
    return path


def setup(root: Path, **kwargs: Any) -> list[dict[str, Any]]:
    """SYNTHETIC E1 rows and transcripts, and a preregistration with K = 8."""
    rows = synthetic_e1(root, **kwargs)
    write_prereg(root)
    return rows


@contextlib.contextmanager
def fake_serve(
    config: JudgeConfig, args: Any, pending: int
) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
    """SYNTHETIC stand-in for ``run_judges.serve``: no server, a fake judge."""
    yield fake_judge(flags_tests), {"model": config.model, "synthetic_judge": True}


def refuse(*_: Any) -> Any:
    raise AssertionError("this run must not start a server or call a model")


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- dry run


def test_dry_run_draws_the_preregistered_sample_and_calls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 19: the dry run reads K and the seed from the preregistration and applies them."""
    rows = setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", refuse)
    assert run_judges.main(["--root", str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "K = 8 with seed 20261108 (the preregistered sample" in out
    assert "8 run(s) sampled from the 16 of the sampling frame" in out
    assert "ma-qwen7b: 4 eligible, 2 sampled" in out
    assert "qwen7b-transcript" in out and "granite8b-transcript" in out
    assert "  qwen7b-transcript (qwen2.5-coder-7b-instruct-q4km): 8 calls" in out
    assert "total: 16 calls, 16 new" in out
    assert not (tmp_path / OUT).exists() and not (tmp_path / "runs" / "e3").exists()
    assert run_judges.main(["--root", str(tmp_path), "--dry-run", "--limit", "3"]) == 0
    assert "total: 6 calls" in capsys.readouterr().out
    # The dry run's sample is the one the tool judges.
    expected = e3.draw_sample(rows, 8, SEED).run_ids
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert run_judges.main(["--root", str(tmp_path)]) == 0
    assert read_json(tmp_path / OUT)["sample"]["sampled_run_ids"] == list(expected)


def test_dry_run_without_a_fixed_k_counts_the_frame_and_a_real_run_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_e1(tmp_path)
    write_prereg(tmp_path, k="TO FIX BEFORE FREEZE")
    monkeypatch.setattr(run_judges, "serve", refuse)
    assert run_judges.main(["--root", str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "K is not fixed" in out and "every one of the 16 runs" in out
    assert "total: 32 calls" in out
    assert run_judges.main(["--root", str(tmp_path)]) == 2
    assert "no sample size" in capsys.readouterr().err
    # An exploratory sample needs --out elsewhere: it is not the preregistered one.
    assert run_judges.main(["--root", str(tmp_path), "--sample-runs", "4"]) == 2
    assert "a sample other than the preregistered one" in capsys.readouterr().err
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    elsewhere = tmp_path / "explore.json"
    args = ["--root", str(tmp_path), "--sample-runs", "4", "--out", str(elsewhere)]
    assert run_judges.main(args) == 0
    data = read_json(elsewhere)
    assert data["sample"]["sample_runs"] == 4 and data["sample"]["seed"] == SEED
    assert data["sample"]["preregistered"] is False and data["runs"]["sampled"] == 4
    assert any("no machine-readable sample_runs" in p for p in data["confirmatory_problems"])
    assert (tmp_path / "explore.replies.jsonl").is_file()
    assert (
        run_judges.main(["--root", str(tmp_path), "--sample-runs", "6", "--out", str(elsewhere)])
        == 2
    )
    assert "multiple of 4" in capsys.readouterr().err


# --------------------------------------------------------------------------- a full run


def test_tool_writes_judges_json_and_the_raw_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 22: every raw reply is banked in artifacts/e3/replies.jsonl, bound by its hash."""
    rows = setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert run_judges.main(["--root", str(tmp_path)]) == 0
    data = read_json(tmp_path / OUT)
    assert [j["judge_id"] for j in data["judges"]] == ["qwen7b-transcript", "granite8b-transcript"]
    assert data["synthetic"] is True and data["confirmatory"] is False
    assert data["runs"]["complete"] is True and data["runs"]["sampled"] == 8
    assert data["sample"]["preregistered"] is True and data["prereg"] == PREREG
    sampled = e3.draw_sample(rows, 8, SEED).run_ids
    prov = data["provenance"]
    assert prov["git_sha"] and prov["command"].startswith("python tools/run_judges.py")
    transcripts = {rel for rel in prov["inputs"] if rel.endswith("transcript.json")}
    assert transcripts == {f"{RUNS}/{run_id}/transcript.json" for run_id in sampled}
    assert {ROWS, PREREG} <= set(prov["inputs"])
    assert all(len(v) == 64 for v in prov["inputs"].values())
    assert not any(
        "ledger" in rel or "verification" in rel or "run.json" in rel for rel in prov["inputs"]
    )
    assert prov["model_servers"]["qwen7b-transcript"]["synthetic_judge"] is True
    assert all(j["synthetic"] is True for j in data["judges"])  # fake judges say so
    assert set(prov["analysis_code"]) == set(run_judges.code_files())
    assert (tmp_path / "runs" / "e3" / "pid").is_file()
    replies = tmp_path / REPLIES
    assert data["replies"] == {"path": REPLIES, "sha256": sha256(replies), "records": 16}
    # The first record banks what the artifact took from the run besides the replies
    # (DECISIONS D65): the judges' model servers and the failure log (none here).
    header, *records = jsonl(replies)
    assert header == {
        "schema": e3.REPLIES_SCHEMA,
        "model_servers": prov["model_servers"],
        "failure_log": None,
    }
    assert len(records) == 16 and {r["judge_id"] for r in records} == {
        "qwen7b-transcript",
        "granite8b-transcript",
    }
    first = records[0]
    assert first["run_id"] == sampled[0] and first["status"] == "ok"
    assert json.loads(first["text"]) == {
        "labels": [{"id": "c0", "label": "contradicted"}, {"id": "c1", "label": "supported"}]
    }
    assert (first["finish_reason"], first["input_tokens"], first["output_tokens"]) == (
        "stop",
        100,
        20,
    )
    calls = {(c["judge_id"], c["run_id"]): c["cache_key"] for c in data["calls"]}
    assert all(calls[(r["judge_id"], r["run_id"])] == r["cache_key"] for r in records)
    out = capsys.readouterr().out
    assert "E3: wrote" in out and "not confirmatory" in out
    assert run_judges.main(["--root", str(tmp_path), "--judges", "nobody"]) == 2
    assert "unknown judge" in capsys.readouterr().err


def test_tool_serves_banked_calls_from_the_cache_without_a_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = setup(tmp_path)
    monkeypatch.delenv("RECEIPTS_OFFLINE", raising=False)
    cache = tmp_path / "runs" / "cache"
    items = e3.load_items(rows, tmp_path / RUNS, tmp_path, e3.draw_sample(rows, 8, SEED).run_ids)
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
    data = read_json(one_judge)
    assert data["judges"][0]["usage"]["cache_hits"] == len(items)
    assert data["provenance"]["model_servers"]["qwen7b-transcript"]["started"] is False
    assert data["provenance"]["model_servers"]["qwen7b-transcript"]["model_sha256"] == (
        LOCAL_MODELS[e3.JUDGES[0].model].sha256
    )
    assert data["provenance"]["cache_dir"] == "runs/cache"
    assert data["runs"]["complete"] is False  # one judge of two
    usage = (tmp_path / "artifacts" / "usage" / "ledger.jsonl").read_text(encoding="utf-8")
    assert len(usage.splitlines()) == len(items)
    # A re-score gets the real server's provenance and the cache hits from the replies,
    # starts no server, and logs no model call.
    again = tmp_path / "again.json"
    banked = ["--rescore", "--replies", "one-judge.replies.jsonl", "--out", str(again)]
    assert run_judges.main([*args, *banked]) == 0
    assert comparable(read_json(again)) == comparable(data)
    after = (tmp_path / "artifacts" / "usage" / "ledger.jsonl").read_text(encoding="utf-8")
    assert after == usage


def test_tool_reads_the_held_out_evaluation_with_the_floor_of_ten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 24: the valid types are rescore.valid_types of the held-out evaluation."""
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    seeded = tmp_path / "artifacts" / "e0" / "seeded_eval.json"
    seeded.parent.mkdir(parents=True)
    seeded.write_text(json.dumps(seeded_eval({"tests_pass": 10, "file_modified": 9})), "utf-8")
    first_two = tmp_path / "first-two.json"  # a partial run never writes the default path
    assert run_judges.main(["--root", str(tmp_path), "--limit", "2", "--out", str(first_two)]) == 0
    data = read_json(first_two)
    assert data["valid_claim_types"]["types"] == ["tests_pass"]
    assert data["valid_claim_types"]["seeded_eval_sha256"] == sha256(seeded)
    assert data["valid_claim_types"]["per_type"]["file_modified"]["status"].startswith(
        "fewer than 10"
    )
    assert data["claim_types"]["tests_pass"]["valid_type"] is True
    assert data["claim_types"]["file_modified"]["valid_type"] is False
    assert data["judges"][0]["pooled"]["valid_types"]["types"] == ["tests_pass"]
    assert data["runs"]["complete"] is False and data["runs"]["judged"] == 2
    assert "artifacts/e0/seeded_eval.json" in data["provenance"]["inputs"]


def test_tool_rejects_a_seeded_evaluation_that_is_not_held_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", refuse)
    seeded = tmp_path / "artifacts" / "e0" / "seeded_eval.json"
    seeded.parent.mkdir(parents=True)
    seeded.write_text(json.dumps({"split": "dev", "items": []}), encoding="utf-8")
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "held-out" in capsys.readouterr().err
    assert not (tmp_path / OUT).exists()


def test_tool_rejects_a_seeded_evaluation_in_another_verifier_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A SYNTHETIC held-out evaluation made without the task requirements (D54).
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", refuse)
    seeded = tmp_path / "artifacts" / "e0" / "seeded_eval.json"
    seeded.parent.mkdir(parents=True)
    other = {**seeded_eval({"tests_pass": 10}), "verifier_mode": "no_requirements"}
    seeded.write_text(json.dumps(other), encoding="utf-8")
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "verifier mode" in capsys.readouterr().err
    assert not (tmp_path / OUT).exists()


def test_tool_refuses_confirmatory_before_any_call_and_missing_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", refuse)
    assert run_judges.main(["--root", str(tmp_path), "--confirmatory"]) == 1
    err = capsys.readouterr().err
    assert "refusing a confirmatory E3 artifact" in err and "not a git checkout" in err
    transcript = tmp_path / RUNS / str(read_rows(tmp_path)[0]["run_id"]) / "transcript.json"
    transcript.unlink()  # a sampled or unsampled run; K = 16 samples every run
    assert run_judges.main(["--root", str(tmp_path), "--sample-runs", "16", "--dry-run"]) == 1
    assert "transcript.json is missing" in capsys.readouterr().err
    (tmp_path / ROWS).unlink()
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "runs.jsonl" in capsys.readouterr().err


def test_tool_records_the_e2_mechanism_classes_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    sampled = e3.draw_sample(rows, 8, SEED).run_ids
    mechanism = tmp_path / "artifacts" / "e2" / "mechanism.json"
    mechanism.parent.mkdir(parents=True)
    claims = [{"run_id": sampled[0], "claim_id": "c0", "class": "never_saw"}]
    mechanism.write_text(json.dumps({"claims": claims}), encoding="utf-8")
    assert run_judges.main(["--root", str(tmp_path)]) == 0
    data = read_json(tmp_path / OUT)
    split = data["exploratory"]["judges"]["qwen7b-transcript"]["recall_by_mechanism"]
    assert split["status"] == "ok" and "artifacts/e2/mechanism.json" in data["provenance"]["inputs"]
    mechanism.write_text(json.dumps({"claims": [{"run_id": "x"}]}), encoding="utf-8")
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "mechanism" in capsys.readouterr().err


# --------------------------------------------------------------------------- failures


def test_a_server_that_cannot_start_or_a_refusal_counts_no_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)

    @contextlib.contextmanager
    def broken(
        config: JudgeConfig, args: Any, pending: int
    ) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
        """SYNTHETIC: the judge's server fails to start."""
        raise RuntimeError("model server exited early")
        yield fake_judge(flags_tests), {}  # pragma: no cover - never reached

    monkeypatch.setattr(run_judges, "serve", broken)
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "a judge call failed (model server exited early); no attempt" in capsys.readouterr().err

    def offline(request: ModelRequest) -> ModelResponse:
        """SYNTHETIC: the client refuses every call."""
        raise ClientRefusedError("RECEIPTS_OFFLINE=1: model calls are disabled")

    @contextlib.contextmanager
    def refusing(
        config: JudgeConfig, args: Any, pending: int
    ) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
        yield offline, {"model": config.model, "synthetic_judge": True}

    monkeypatch.setattr(run_judges, "serve", refusing)
    assert run_judges.main(["--root", str(tmp_path)]) == 1
    assert "RECEIPTS_OFFLINE=1" in capsys.readouterr().err
    assert not (tmp_path / FAILURE_LOG).exists() and not (tmp_path / OUT).exists()


Serve = Callable[..., Any]


def flaky(broken: str, asked: list[tuple[str, str]]) -> Serve:
    """A SYNTHETIC stand-in for ``run_judges.serve`` whose granite judge always fails on
    run ``broken``; every request's ``(judge, run)`` is appended to ``asked``."""

    @contextlib.contextmanager
    def flaky_serve(
        config: JudgeConfig, args: Any, pending: int
    ) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
        judge = fake_judge(flags_tests)

        def complete(request: ModelRequest) -> ModelResponse:
            asked.append((config.judge_id, run_of(request)))
            if config.judge_id == "granite8b-transcript" and run_of(request) == broken:
                raise BackendError("local backend call failed: HTTP Error 400: Bad Request")
            return judge(request)

        yield complete, {"model": config.model, "synthetic_judge": True}

    return flaky_serve


def test_a_failed_call_is_retried_and_its_run_excluded_after_three_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 23: three logged failures exclude the run for both judges; nothing aborts it all."""
    rows = setup(tmp_path)
    sampled = e3.draw_sample(rows, 8, SEED).run_ids
    broken = sampled[2]
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(run_judges, "serve", flaky(broken, asked))
    root = ["--root", str(tmp_path)]
    for attempt in (1, 2, 3):
        assert run_judges.main(root) == 1
        err = capsys.readouterr().err
        assert f"attempt {attempt} of 3" in err and broken in err
        assert ("excludes run" in err) == (attempt == 3)
        assert len(jsonl(tmp_path / FAILURE_LOG)) == attempt
        assert not (tmp_path / OUT).exists()  # a failed call writes no artifact
    entries = jsonl(tmp_path / FAILURE_LOG)
    assert [e["attempt"] for e in entries] == [1, 2, 3]
    assert {e["judge_id"] for e in entries} == {"granite8b-transcript"}
    assert all(e["error"].startswith("BackendError: local backend call failed") for e in entries)
    asked.clear()
    assert run_judges.main(root) == 0
    assert all(run_id != broken for _, run_id in asked)  # never asked again, by either judge
    data = read_json(tmp_path / OUT)
    assert data["runs"]["excluded"] == [broken] and data["runs"]["judged"] == 7
    assert data["runs"]["complete"] is True  # judged or excluded under section 7
    (excluded,) = data["exclusions"]
    assert excluded["run_id"] == broken
    assert [e["attempt"] for e in excluded["calls"][0]["errors"]] == [1, 2, 3]
    assert any(d["kind"] == "excluded_unservable" for d in data["deviations"])
    statuses = {c["status"] for c in data["calls"] if c["run_id"] == broken}
    assert statuses == {e3.EXCLUDED}
    assert all(item["run_id"] != broken for item in data["items"])
    header, *records = jsonl(tmp_path / REPLIES)
    assert all(r["run_id"] != broken for r in records)
    # The replies bank the failure log the exclusion came from, byte for byte.
    log = (tmp_path / FAILURE_LOG).read_text(encoding="utf-8")
    assert header["failure_log"] == {"path": FAILURE_LOG, "text": log}
    assert data["provenance"]["inputs"][FAILURE_LOG] == sha256(tmp_path / FAILURE_LOG)
    assert run_judges.main([*root, "--dry-run"]) == 0
    assert "1 run(s) excluded under section 7" in capsys.readouterr().out
    # Excluded for both judges: a run of the qwen judge alone skips it too.
    asked.clear()
    alone = tmp_path / "qwen-only.json"
    assert run_judges.main([*root, "--judges", "qwen7b-transcript", "--out", str(alone)]) == 0
    assert asked and all(run_id != broken for _, run_id in asked)
    assert read_json(alone)["runs"]["excluded"] == [broken]


# --------------------------------------------------------------------------- re-score (D65)


def rescore(root: Path, out: Path, *extra: str) -> int:
    """``--rescore`` of the artifact under ``root`` into ``out``."""
    return run_judges.main(["--root", str(root), "--rescore", "--out", str(out), *extra])


def test_a_rescore_reproduces_the_artifact_from_the_banked_replies_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every field but when, where, and how it was made comes back without a model call,
    the run's state under runs/ (git ignores it, so a fresh clone has none) included."""
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert run_judges.main(["--root", str(tmp_path)]) == 0
    committed = read_json(tmp_path / OUT)
    banked = (tmp_path / REPLIES).read_bytes()
    shutil.rmtree(tmp_path / "runs")  # the pid file and the response cache
    monkeypatch.setattr(run_judges, "serve", refuse)  # no server, no model
    again = tmp_path / "rescored.json"
    assert rescore(tmp_path, again) == 0
    fresh = read_json(again)
    assert comparable(fresh) == comparable(committed)
    assert fresh["provenance"]["command"].endswith(f"--rescore --out {again}")
    # The usage, the parse statuses, and the cache hits come from the banked replies.
    assert [j["usage"] for j in fresh["judges"]] == [j["usage"] for j in committed["judges"]]
    assert fresh["replies"] == committed["replies"]
    # A re-score writes only its output: no replies file, pid file, cache, or failure log.
    assert (tmp_path / REPLIES).read_bytes() == banked
    assert not (tmp_path / "runs").exists() and not (tmp_path / "artifacts" / "usage").exists()
    assert "E3: re-scored artifacts/e3/replies.jsonl with no model call" in capsys.readouterr().out
    # The banked replies, named or not, may re-score the default artifact itself.
    assert rescore(tmp_path, tmp_path / OUT, "--replies", REPLIES) == 0
    assert comparable(read_json(tmp_path / OUT)) == comparable(committed)


def test_a_rescore_takes_the_exclusions_from_the_banked_failure_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = setup(tmp_path)
    broken = e3.draw_sample(rows, 8, SEED).run_ids[2]
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(run_judges, "serve", flaky(broken, asked))
    root = ["--root", str(tmp_path)]
    for _ in range(e3.MAX_ATTEMPTS):
        assert run_judges.main(root) == 1
    assert run_judges.main(root) == 0
    committed = read_json(tmp_path / OUT)
    assert committed["runs"]["excluded"] == [broken]
    shutil.rmtree(tmp_path / "runs")  # the live failure log is gone, as in a fresh clone
    monkeypatch.setattr(run_judges, "serve", refuse)
    again = tmp_path / "rescored.json"
    assert rescore(tmp_path, again) == 0
    fresh = read_json(again)
    assert comparable(fresh) == comparable(committed)
    assert fresh["exclusions"] == committed["exclusions"]
    assert [e["attempt"] for e in fresh["exclusions"][0]["calls"][0]["errors"]] == [1, 2, 3]


def test_a_rescore_of_a_partial_run_reads_its_own_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    part = ["--judges", "qwen7b-transcript", "--limit", "3"]
    out = ["--out", str(tmp_path / "part.json")]
    assert run_judges.main(["--root", str(tmp_path), *part, *out]) == 0
    committed = read_json(tmp_path / "part.json")
    assert committed["replies"]["path"] == "part.replies.jsonl"
    monkeypatch.setattr(run_judges, "serve", refuse)
    again = tmp_path / "again.json"
    assert rescore(tmp_path, again, *part, "--replies", "part.replies.jsonl") == 0
    assert comparable(read_json(again)) == comparable(committed)
    # The full replies answer other calls than this run's: refused, nothing written.
    again.unlink()
    assert rescore(tmp_path, again, *part, "--replies", "missing.jsonl") == 1
    assert "missing.jsonl is missing: a re-score serves every judge call" in capsys.readouterr().err
    assert rescore(tmp_path, again, "--limit", "3", "--replies", "part.replies.jsonl") == 1
    err = capsys.readouterr().err
    assert "records the model servers of qwen7b-transcript, but this re-score runs" in err
    assert not again.exists()


def test_a_rescore_refuses_replies_that_do_not_serve_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert run_judges.main(["--root", str(tmp_path)]) == 0
    replies = tmp_path / REPLIES
    lines = replies.read_text(encoding="utf-8").splitlines(keepends=True)
    monkeypatch.setattr(run_judges, "serve", refuse)
    again = tmp_path / "rescored.json"
    for text, said in (
        # A reply removed: its request has none, and no model is asked instead.
        (
            "".join(lines[:1] + lines[2:]),
            "has no banked reply of judge qwen7b-transcript to request",
        ),
        # A reply that no call of this run asks for.
        ("".join([*lines, lines[1]]), "1 banked reply record(s) that answer no call"),
        # The replies without their first record (the servers and the failure log).
        ("".join(lines[1:]), "does not begin with its receipts.e3.replies/2 record"),
    ):
        replies.write_text(text, encoding="utf-8")
        assert rescore(tmp_path, again) == 1
        err = capsys.readouterr().err
        assert said in err, err
        assert not again.exists()
    replies.unlink()
    assert rescore(tmp_path, again) == 1
    assert "artifacts/e3/replies.jsonl is missing" in capsys.readouterr().err


def test_rescore_usage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    monkeypatch.setattr(run_judges, "serve", refuse)
    root = ["--root", str(tmp_path)]
    assert run_judges.main([*root, "--rescore", "--dry-run"]) == 2
    assert "pass one" in capsys.readouterr().err
    assert run_judges.main([*root, "--replies", "x.jsonl", "--out", str(tmp_path / "x.json")]) == 2
    assert "add --rescore" in capsys.readouterr().err
    other = tmp_path / "other.jsonl"
    assert rescore(tmp_path, other, "--replies", "other.jsonl") == 2
    assert "is the replies file the re-score reads" in capsys.readouterr().err
    # The output rules of a run hold for a re-score too.
    assert rescore(tmp_path, tmp_path / REPLIES) == 2
    assert "is the replies file of" in capsys.readouterr().err
    assert run_judges.main([*root, "--rescore", "--limit", "2"]) == 2
    assert "a partial run" in capsys.readouterr().err
    # A re-score of other replies never writes the default artifact, which is scored from
    # the banked replies (review BV2 of the B5 fix); it is refused before anything is read.
    (tmp_path / "other.replies.jsonl").write_text("SYNTHETIC: never read\n", encoding="utf-8")
    for out in (tmp_path / OUT, Path(OUT)):  # absolute, and relative to the working directory
        monkeypatch.chdir(tmp_path)
        assert rescore(tmp_path, out, "--replies", "other.replies.jsonl") == 2
        err = capsys.readouterr().err
        assert f"a re-score of other.replies.jsonl never writes {OUT}" in err, err
        assert f"scored from the banked replies {REPLIES}" in err
    assert not (tmp_path / OUT).exists()


# --------------------------------------------------------------------------- output rules


def test_tool_never_writes_a_partial_artifact_to_the_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--limit, not every judge, or another sample needs --out elsewhere; nothing runs first."""
    setup(tmp_path)
    default = tmp_path / OUT
    default.parent.mkdir(parents=True)
    # A SYNTHETIC placeholder standing for a complete judges.json banked earlier.
    placeholder = '{"SYNTHETIC": "placeholder for a complete artifact"}\n'
    default.write_text(placeholder, encoding="utf-8")
    monkeypatch.setattr(run_judges, "serve", refuse)
    root = ["--root", str(tmp_path)]
    for extra in (
        ["--limit", "2"],
        ["--judges", "qwen7b-transcript"],
        ["--judges", "granite8b-transcript", "--limit", "9"],
        ["--limit", "2", "--out", str(default)],
        ["--sample-runs", "12"],
        ["--sample-seed", "20261107"],
    ):
        assert run_judges.main([*root, *extra]) == 2, extra
        err = capsys.readouterr().err
        assert "a partial run" in err and "--out" in err and OUT in err
    twice = ["--judges", "qwen7b-transcript,qwen7b-transcript", "--out", str(tmp_path / "x.json")]
    assert run_judges.main([*root, *twice]) == 2
    assert "named more than once: qwen7b-transcript" in capsys.readouterr().err
    assert run_judges.main([*root, "--out", str(tmp_path / REPLIES)]) == 2
    assert "is the replies file" in capsys.readouterr().err
    assert default.read_text(encoding="utf-8") == placeholder
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    elsewhere = tmp_path / "partial" / "judges.json"
    partial = ["--judges", "qwen7b-transcript", "--limit", "2", "--out", str(elsewhere)]
    assert run_judges.main([*root, *partial]) == 0
    data = read_json(elsewhere)
    assert [j["judge_id"] for j in data["judges"]] == ["qwen7b-transcript"]
    assert data["runs"]["complete"] is False and data["runs"]["limit"] == 2
    assert data["replies"] == {
        "path": "partial/judges.replies.jsonl",
        "sha256": sha256(tmp_path / "partial" / "judges.replies.jsonl"),
        "records": 2,
    }
    assert len(jsonl(tmp_path / "partial" / "judges.replies.jsonl")) == 1 + 2  # first record
    assert default.read_text(encoding="utf-8") == placeholder
    assert not (tmp_path / REPLIES).exists()
    # Every judge, in any order and without --limit, is a full run: it may write the default.
    assert run_judges.main([*root, "--judges", "granite8b-transcript,qwen7b-transcript"]) == 0
    full = read_json(default)
    assert full["runs"]["complete"] is True and len(full["judges"]) == 2
    assert [j["judge_id"] for j in full["judges"]] == [c.judge_id for c in e3.JUDGES]


def test_tool_never_replaces_a_confirmatory_artifact_with_an_exploratory_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same guard as analyze_e4: a confirmatory judges.json is kept."""
    setup(tmp_path)
    default = tmp_path / OUT
    default.parent.mkdir(parents=True)
    # A SYNTHETIC placeholder standing for a banked confirmatory artifact.
    placeholder = '{"confirmatory": true, "SYNTHETIC": "placeholder"}\n'
    default.write_text(placeholder, encoding="utf-8")
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
    assert check(tmp_path, default, judges=every, limit=None, preregistered_sample=False)


# --------------------------------------------------------------------------- git and code


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def copy_analysis_code(root: Path) -> None:
    """Copy every analysis code file that runs to the same path under ``root``."""
    for rel, path in run_judges.code_files().items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def test_analysis_code_names_every_module_that_runs() -> None:
    for required in (
        "tools/run_judges.py",
        "src/receipts/evaluation/e3.py",
        "src/receipts/evaluation/judges.py",
        "src/receipts/study/results_e4.py",
        "src/receipts/study/rescore.py",
        "src/receipts/analysis",
    ):
        assert required in run_judges.ANALYSIS_CODE
    for rel in run_judges.code_files():
        assert any(rel == p or rel.startswith(p + "/") for p in run_judges.ANALYSIS_CODE), rel


def test_analysis_code_state_and_the_lock_commit(
    git_repo: Path, commit: Commit, tmp_path: Path
) -> None:
    """Item 20: uncommitted code blocks; a change after the freeze is a deviation."""
    copy_analysis_code(git_repo)
    freeze = commit(git_repo, "SYNTHETIC analysis code")
    problems, deviations, hashes, dirty = run_judges.analysis_code_state(git_repo, freeze)
    assert (problems, deviations, dirty) == ([], [], [])
    assert hashes == {rel: sha256(p) for rel, p in run_judges.code_files().items()}
    e3_file = git_repo / "src" / "receipts" / "evaluation" / "e3.py"
    kept = e3_file.read_text(encoding="utf-8")
    e3_file.write_text(kept + "# SYNTHETIC edit\n", encoding="utf-8")
    problems, _, _, dirty = run_judges.analysis_code_state(git_repo, freeze)
    assert dirty == ["src/receipts/evaluation/e3.py"]
    assert any("uncommitted changes" in p for p in problems)
    assert any("differs from the files under --root" in p for p in problems)
    commit(git_repo, "SYNTHETIC change after the freeze")
    e3_file.write_text(kept, encoding="utf-8")
    problems, deviations, _, _ = run_judges.analysis_code_state(git_repo, freeze)
    assert any("uncommitted" in p for p in problems)  # the revert is not committed yet
    commit(git_repo, "SYNTHETIC revert")
    assert run_judges.analysis_code_state(git_repo, freeze)[:2] == ([], [])
    _git(git_repo, "mv", "src/receipts/analysis/rates.py", "src/receipts/analysis/moved.py")
    moved = run_judges.analysis_code_state(git_repo, freeze)[3]
    assert {"src/receipts/analysis/rates.py", "src/receipts/analysis/moved.py"} <= set(moved)
    _git(git_repo, "mv", "src/receipts/analysis/moved.py", "src/receipts/analysis/rates.py")
    judges_file = git_repo / "src" / "receipts" / "evaluation" / "judges.py"
    judges_file.write_text(judges_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    commit(git_repo, "SYNTHETIC judges change after the freeze")
    _, deviations, _, _ = run_judges.analysis_code_state(git_repo, freeze)
    assert deviations[0]["kind"] == "analysis_code_changed"
    assert deviations[0]["files"] == ["src/receipts/evaluation/judges.py"]
    assert any("not a git checkout" in p for p in run_judges.analysis_code_state(tmp_path, None)[0])
    bad = run_judges.analysis_code_state(git_repo, "0" * 40)[0]
    assert any("cannot be compared with the freeze commit" in p for p in bad)
    # The LOCK commit: none until the freeze is committed; an unreadable lock is skipped.
    write_prereg(git_repo)
    (git_repo / "prereg" / "LOCK.json").write_text("{ not json", encoding="utf-8")
    commit(git_repo, "SYNTHETIC prereg draft and an unreadable lock")
    assert run_judges.lock_commit(git_repo, PREREG) is None
    (git_repo / "prereg" / "LOCK.json").unlink()
    commit(git_repo, "SYNTHETIC lock removed")
    prereg.freeze(git_repo, PREREG, "2026-11-04")
    assert run_judges.lock_commit(git_repo, PREREG) is None  # frozen, not committed
    frozen_at = commit(git_repo, "SYNTHETIC freeze")
    found = run_judges.lock_commit(git_repo, PREREG)
    assert found == results_e4.LockCommit(frozen_at, sha256(git_repo / PREREG))
    assert run_judges.lock_commit(tmp_path, PREREG) is None


def test_analyzed_digest_is_read_from_the_e1_results(tmp_path: Path) -> None:
    """Item 20: the runs.jsonl digest artifacts/e1/results.json records, or None."""
    assert run_judges.analyzed_digest(tmp_path) is None
    path = tmp_path / "artifacts" / "e1" / "results.json"
    path.parent.mkdir(parents=True)
    for broken in ("{ not json", "[1]", json.dumps({"provenance": {"inputs": {}}})):
        path.write_text(broken, encoding="utf-8")
        assert run_judges.analyzed_digest(tmp_path) is None
    path.write_text(json.dumps({"provenance": {"inputs": {ROWS: "a" * 64}}}), encoding="utf-8")
    assert run_judges.analyzed_digest(tmp_path) == "a" * 64


def confirmatory_checkout(root: Path, commit: Commit) -> list[dict[str, Any]]:
    """A scratch repository where every condition of section 8 holds (SYNTHETIC inputs).

    The analysis code is copied in, the rows carry the synthetic flag off and the
    instrument trees the SYNTHETIC held-out evaluation records, ``results.json`` records
    the rows' digest, and the preregistration's LOCK entry is committed.
    """
    copy_analysis_code(root)
    rows = synthetic_e1(root, synthetic=False)
    seeded = root / "artifacts" / "e0" / "seeded_eval.json"
    seeded.parent.mkdir(parents=True)
    seeded.write_text(json.dumps(seeded_eval({"tests_pass": 10})), encoding="utf-8")
    results = {"provenance": {"inputs": {ROWS: sha256(root / ROWS)}}}
    (root / "artifacts" / "e1" / "results.json").write_text(json.dumps(results), "utf-8")
    write_prereg(root)
    commit(root, "SYNTHETIC code, rows, evaluation, prereg")
    prereg.freeze(root, PREREG, "2026-11-04")
    commit(root, "SYNTHETIC freeze")
    return rows


@contextlib.contextmanager
def pinned_serve(
    config: JudgeConfig, args: Any, pending: int
) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
    """A stand-in server recording the pinned model file (SYNTHETIC judge, gating test)."""
    pin = LOCAL_MODELS[config.model]
    yield fake_judge(flags_tests), {"model": pin.name, "model_sha256": pin.sha256}


def test_a_confirmatory_artifact_needs_every_condition_of_section_8(
    git_repo: Path,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Item 20 end to end: every condition holds, then each git-side one alone refuses."""
    confirmatory_checkout(git_repo, commit)
    monkeypatch.setattr(run_judges, "serve", pinned_serve)
    root = ["--root", str(git_repo)]
    assert run_judges.main([*root, "--confirmatory"]) == 0
    data = read_json(git_repo / OUT)
    assert data["confirmatory"] is True and data["confirmatory_problems"] == []
    assert data["prereg"] == PREREG and data["prereg_sha256"] == sha256(git_repo / PREREG)
    assert data["prereg_frozen"] is True and data["synthetic"] is False
    assert data["provenance"]["uncommitted_analysis_code"] == []
    # An exploratory run may not replace it.
    assert run_judges.main(root) == 2
    assert "holds a confirmatory artifact" in capsys.readouterr().err
    (git_repo / OUT).unlink()
    (git_repo / REPLIES).unlink()
    # The rows are not the ones artifacts/e1/results.json analyzes.
    results = git_repo / "artifacts" / "e1" / "results.json"
    kept = results.read_text(encoding="utf-8")
    results.write_text(json.dumps({"provenance": {"inputs": {ROWS: "f" * 64}}}), "utf-8")
    assert run_judges.main([*root, "--confirmatory"]) == 1
    assert "is not the file artifacts/e1/results.json analyzes" in capsys.readouterr().err
    results.write_text(kept, encoding="utf-8")
    # Uncommitted analysis code, or an uncommitted held-out evaluation.
    e3_file = git_repo / "src" / "receipts" / "evaluation" / "e3.py"
    e3_file.write_text(e3_file.read_text(encoding="utf-8") + "# SYNTHETIC\n", "utf-8")
    assert run_judges.main([*root, "--confirmatory"]) == 1
    assert "uncommitted changes" in capsys.readouterr().err
    _git(git_repo, "checkout", "--", "src/receipts/evaluation/e3.py")
    seeded = git_repo / "artifacts" / "e0" / "seeded_eval.json"
    seeded.write_text(seeded.read_text(encoding="utf-8") + "\n", "utf-8")
    assert run_judges.main([*root, "--confirmatory"]) == 1
    assert "seeded_eval.json has uncommitted changes" in capsys.readouterr().err
    _git(git_repo, "checkout", "--", "artifacts/e0/seeded_eval.json")
    # A judge whose server provenance lacks the pinned model file.
    monkeypatch.setattr(run_judges, "serve", fake_serve)
    assert run_judges.main([*root, "--confirmatory"]) == 1
    err = capsys.readouterr().err
    assert "pinned model file SHA-256" in err and "synthetic judge" in err
    assert not (git_repo / OUT).exists()


def test_a_confirmatory_artifact_is_reproduced_by_a_rescore(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The pinned model files and every condition of section 8 come back from the banked
    replies, so a confirmatory artifact re-scores to itself in its committed checkout."""
    confirmatory_checkout(git_repo, commit)
    monkeypatch.setattr(run_judges, "serve", pinned_serve)
    root = ["--root", str(git_repo)]
    assert run_judges.main([*root, "--confirmatory"]) == 0
    committed = read_json(git_repo / OUT)
    assert committed["confirmatory"] is True
    commit(git_repo, "SYNTHETIC E3 artifact and replies")
    monkeypatch.setattr(run_judges, "serve", refuse)
    again = tmp_path / "rescored.json"
    assert rescore(git_repo, again, "--confirmatory") == 0
    assert comparable(read_json(again)) == comparable(committed)


def test_an_uncommitted_lock_entry_is_not_a_freeze(
    git_repo: Path,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    copy_analysis_code(git_repo)
    synthetic_e1(git_repo, synthetic=False)
    write_prereg(git_repo)
    commit(git_repo, "SYNTHETIC code, rows, prereg")
    prereg.freeze(git_repo, PREREG, "2026-11-04")  # in the working tree only
    monkeypatch.setattr(run_judges, "serve", refuse)
    assert run_judges.main(["--root", str(git_repo), "--confirmatory"]) == 1
    err = capsys.readouterr().err
    assert "is not committed" in err and "was not read" in err
