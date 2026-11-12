"""tools/amend_plan.py: one new smoke run in place of an excluded one (DECISIONS D71).

The tool appends the excluded run's planned spec under a new id with a server-window
requirement, records the amendment and its reason in the plan, and leaves every other
byte of the plan, the failure log, and every banked run as it was. Every plan, run,
failure, model, and checkout here is a SYNTHETIC test fixture under tmp_path; no model
is called and nothing touches the real artifacts or runs/.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import amend_plan
import run_study
from receipts.client.server import LocalModel
from receipts.study.plan import Plan, load_plan, local_arm, plan_text, smoke_plan, write_plan

MODEL = "synthetic-model"
PINNED_N_CTX = 16384
TASKS = ("py-alpha", "py-beta", "ts-gamma")
EXCLUDED = "smoke-py-beta-ma-syn"
ADDED = f"{EXCLUDED}-ctx32k"
REASON = "SYNTHETIC: the final-report request outgrew the 16384-token window per slot"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A SYNTHETIC checkout: a smoke plan, one banked run, and a failure log that shows
    the excluded run's three failed attempts."""
    root = tmp_path / "checkout"
    plan = smoke_plan("smoke", TASKS, local_arm("ma-syn", MODEL, "fam"))
    write_plan(root / "artifacts" / "studies" / "smoke" / "plan.json", plan)
    banked = root / "artifacts" / "studies" / "smoke" / "runs" / "smoke-py-alpha-ma-syn"
    banked.mkdir(parents=True)
    (banked / "run.json").write_text('{"SYNTHETIC": "banked run"}\n', encoding="utf-8")
    state = root / "runs"
    monkeypatch.setattr(run_study, "RUNS", state)
    failures(root, EXCLUDED, 3)
    model = LocalModel(MODEL, "fam", Path("/nonexistent.gguf"), "0" * 64, "SYNTHETIC")
    monkeypatch.setattr(amend_plan, "LOCAL_MODELS", {MODEL: model})
    return root


def plan_path(root: Path) -> Path:
    """The SYNTHETIC smoke plan of the checkout."""
    return root / "artifacts" / "studies" / "smoke" / "plan.json"


def failures(root: Path, run_id: str, attempts: int) -> Path:
    """Log ``attempts`` SYNTHETIC failed attempts of ``run_id`` (replacing the log)."""
    path = root / "runs" / "smoke" / "failures.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"run_id": run_id, "attempt": n, "time": "t", "error": "SYNTHETIC HTTPError 400"}
        for n in range(1, attempts + 1)
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def amend(root: Path, *extra: str, replace: str = EXCLUDED, n_ctx: str = "32768") -> int:
    """Run the tool on the checkout's plan."""
    return amend_plan.main(
        [
            "--plan",
            str(plan_path(root)),
            "--replace",
            replace,
            "--n-ctx",
            n_ctx,
            "--decision",
            "D71",
            "--reason",
            REASON,
            "--date",
            "2026-11-12",
            *extra,
        ]
    )


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under the checkout with its bytes."""
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def sha256(data: bytes) -> str:
    """Hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def test_the_tool_adds_one_run_and_changes_nothing_else(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = snapshot(checkout)
    old = plan_path(checkout).read_bytes()
    assert amend(checkout) == 0
    new = plan_path(checkout).read_bytes()
    # Only the plan file changed: not the failure log, not the banked run.
    after = snapshot(checkout)
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    assert changed == {"artifacts/studies/smoke/plan.json"}
    data: dict[str, Any] = json.loads(new)
    (record,) = data.pop("amendments")
    added = data["runs"].pop()
    # Byte for byte, the rest is the plan as it was.
    assert (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8") == old
    excluded = next(r for r in json.loads(old)["runs"] if r["run_id"] == EXCLUDED)
    assert added == {**excluded, "run_id": ADDED}
    assert record == {
        "run_id": ADDED,
        "replaces": EXCLUDED,
        "server": {
            "min_n_ctx_per_slot": 32768,
            "max_parallel_slots": 1,
            "pinned_n_ctx_per_slot": PINNED_N_CTX,
        },
        "decision": "D71",
        "reason": REASON,
        "date": "2026-11-12",
        "plan_sha256_before": sha256(old),
    }
    out = capsys.readouterr().out
    assert f"plan_sha256 before: {sha256(old)}" in out
    assert f"plan_sha256 after: {sha256(new)}" in out
    assert f"added {ADDED} in place of {EXCLUDED}" in out and "3 failed attempts" in out
    # The amended plan is what the library writes and reads back.
    loaded = load_plan(plan_path(checkout))
    assert plan_text(loaded).encode("utf-8") == new
    assert loaded.replaced() == {EXCLUDED} and loaded.amendment(ADDED) is not None


def test_a_second_amendment_of_the_same_task_is_refused(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert amend(checkout) == 0
    once = plan_path(checkout).read_bytes()
    capsys.readouterr()
    assert amend(checkout) == 2
    assert "already has an amendment" in capsys.readouterr().err
    # Nor may the added run be replaced in turn, even after three failed attempts.
    failures(checkout, ADDED, 3)
    assert amend(checkout, replace=ADDED, n_ctx="65536") == 2
    assert "already has an amendment" in capsys.readouterr().err
    assert plan_path(checkout).read_bytes() == once


def bank_excluded(root: Path) -> None:
    """A directory of the excluded run under the banked runs (banked or in progress)."""
    run = root / "artifacts" / "studies" / "smoke" / "runs" / EXCLUDED
    run.mkdir(parents=True)
    (run / "ledger.jsonl").write_text("{}\n", encoding="utf-8")


def two_failures(root: Path) -> None:
    """Only two logged failed attempts: the runner has not excluded the run."""
    failures(root, EXCLUDED, 2)


def no_log(root: Path) -> None:
    """No failure log at all."""
    (root / "runs" / "smoke" / "failures.jsonl").unlink()


def broken_log(root: Path) -> None:
    """A failure log the runner cannot count."""
    (root / "runs" / "smoke" / "failures.jsonl").write_text('{"run_id": \n', encoding="utf-8")


def reformatted(root: Path) -> None:
    """The same plan written with another layout than write_plan's."""
    path = plan_path(root)
    path.write_text(json.dumps(json.loads(path.read_text()), indent=4) + "\n", encoding="utf-8")


def pilot_study(root: Path) -> None:
    """A plan of another study than smoke."""
    plan = smoke_plan("smoke", TASKS, local_arm("ma-syn", MODEL, "fam"))
    pilot = Plan("pilot", plan.arms, plan.runs, plan.text, plan.notes)
    write_plan(plan_path(root), pilot)


@pytest.mark.parametrize(
    ("setup", "extra", "options", "message"),
    [
        pytest.param(bank_excluded, (), {}, "is banked or in progress", id="banked"),
        pytest.param(two_failures, (), {}, "2 failed attempt", id="not-excluded"),
        pytest.param(no_log, (), {}, "0 failed attempt", id="no-failure-log"),
        pytest.param(broken_log, (), {}, "not JSON", id="broken-failure-log"),
        pytest.param(reformatted, (), {}, "not the text write_plan writes", id="reformatted"),
        pytest.param(None, (), {"n_ctx": "16384"}, "does not raise", id="pinned-window"),
        pytest.param(None, (), {"n_ctx": "8192"}, "does not raise", id="smaller-window"),
        pytest.param(None, (), {"replace": "smoke-py-delta-ma-syn"}, "not a planned", id="unknown"),
        pytest.param(pilot_study, (), {}, "not amended", id="other-study"),
        pytest.param(None, ("--date", "November"), {}, "ISO 8601", id="bad-date"),
        pytest.param(None, ("--decision", "D70"), {}, "D71 only", id="other-decision"),
        pytest.param(None, ("--reason", " "), {}, "needs a reason", id="no-reason"),
    ],
)
def test_the_tool_refuses_and_writes_nothing(
    checkout: Path,
    capsys: pytest.CaptureFixture[str],
    setup: Any,
    extra: tuple[str, ...],
    options: dict[str, str],
    message: str,
) -> None:
    if setup is not None:
        setup(checkout)
    before = snapshot(checkout)
    assert amend(checkout, *extra, **options) == 2
    err = capsys.readouterr().err
    assert "amend_plan: refused:" in err and message in err
    assert snapshot(checkout) == before


def test_a_model_that_is_not_pinned_is_refused(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(amend_plan, "LOCAL_MODELS", {})
    before = snapshot(checkout)
    assert amend(checkout) == 2
    assert "not a pinned local model" in capsys.readouterr().err
    assert snapshot(checkout) == before


def test_the_window_must_be_a_positive_number(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        amend(checkout, n_ctx="0")
    assert "--n-ctx must be a positive number of tokens" in capsys.readouterr().err


def test_the_amendment_records_the_pinned_window_of_the_runs_model(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = LocalModel(MODEL, "fam", Path("/nonexistent.gguf"), "0" * 64, "SYNTHETIC", 8192)
    monkeypatch.setattr(amend_plan, "LOCAL_MODELS", {MODEL: small})
    assert amend(checkout, n_ctx="16384") == 0
    (record,) = json.loads(plan_path(checkout).read_text())["amendments"]
    assert record["run_id"] == f"{EXCLUDED}-ctx16k"
    assert record["server"] == {
        "min_n_ctx_per_slot": 16384,
        "max_parallel_slots": 1,
        "pinned_n_ctx_per_slot": 8192,
    }
