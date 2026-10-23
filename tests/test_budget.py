"""Tests for caps, CAP_SHARE, and the usage ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from receipts import budget

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "cash_usd": 0,
    "claude_agent_runs_per_day": 30,
    "claude_agent_max_turns": 40,
    "claude_single_calls_per_day": 300,
    "claude_review_runs_per_day": 6,
    "local_model_max_params_b": 8,
    "disk_floor_gb": 8,
}


def caps(**overrides: float) -> budget.Caps:
    return budget.Caps.from_mapping({**DEFAULTS, **overrides})


def test_repo_budget_matches_brief_defaults() -> None:
    brief = budget.parse_brief_defaults((ROOT / "docs" / "BUILD_BRIEF.md").read_text())
    assert brief == caps()
    assert budget.check_against_defaults(budget.load_caps(ROOT / "budget.toml"), brief) == []


def test_from_mapping_rejects_bad_input() -> None:
    with pytest.raises(budget.BudgetError, match="missing"):
        budget.Caps.from_mapping({"cash_usd": 0})
    with pytest.raises(budget.BudgetError, match="unexpected"):
        budget.Caps.from_mapping({**DEFAULTS, "extra": 1})
    with pytest.raises(budget.BudgetError, match="number"):
        budget.Caps.from_mapping({**DEFAULTS, "disk_floor_gb": "8"})
    with pytest.raises(budget.BudgetError, match="number"):
        budget.Caps.from_mapping({**DEFAULTS, "disk_floor_gb": True})
    with pytest.raises(budget.BudgetError, match="non-negative"):
        budget.Caps.from_mapping({**DEFAULTS, "claude_agent_max_turns": -1})


def test_cap_share_scales_only_claude_caps() -> None:
    half = caps().effective(0.5)
    assert half.claude_agent_runs_per_day == 15
    assert half.claude_review_runs_per_day == 3
    assert half.claude_agent_max_turns == 20
    assert half.local_model_max_params_b == 8
    assert half.disk_floor_gb == 8


def test_parse_cap_share() -> None:
    assert budget.parse_cap_share({}) == 1.0
    assert budget.parse_cap_share({"CAP_SHARE": " "}) == 1.0
    assert budget.parse_cap_share({"CAP_SHARE": "0.5"}) == 0.5
    with pytest.raises(budget.BudgetError):
        budget.parse_cap_share({"CAP_SHARE": "2"})
    with pytest.raises(budget.BudgetError):
        budget.parse_cap_share({"CAP_SHARE": "half"})
    with pytest.raises(budget.BudgetError):
        budget.validate_cap_share(float("nan"))


def test_check_against_defaults_flags_raised_caps_and_cash() -> None:
    problems = budget.check_against_defaults(
        caps(cash_usd=1, claude_agent_runs_per_day=31, disk_floor_gb=4), caps()
    )
    assert len(problems) == 3
    assert any("cash_usd" in p for p in problems)
    assert any("disk_floor_gb" in p for p in problems)
    assert budget.check_against_defaults(caps(claude_agent_runs_per_day=10), caps()) == []


def test_parse_brief_defaults_requires_block() -> None:
    with pytest.raises(budget.BudgetError):
        budget.parse_brief_defaults("no toml here")


def test_lower_cap_only_lowers(tmp_path: Path) -> None:
    path = tmp_path / "budget.toml"
    path.write_text((ROOT / "budget.toml").read_text())
    assert budget.lower_cap(path, "local_model_max_params_b", 4) is True
    assert budget.load_caps(path).local_model_max_params_b == 4
    assert "# make doctor may lower this" in path.read_text()
    assert budget.lower_cap(path, "local_model_max_params_b", 6) is False
    assert budget.lower_cap(path, "local_model_max_params_b", 2.5) is True
    assert budget.load_caps(path).local_model_max_params_b == 2.5
    for key in ("cash_usd", "disk_floor_gb", "nope"):
        with pytest.raises(budget.BudgetError):
            budget.lower_cap(path, key, 1)


def test_lower_cap_handles_compact_assignment(tmp_path: Path) -> None:
    path = tmp_path / "budget.toml"
    path.write_text("\n".join(f"{k} = {v}" for k, v in DEFAULTS.items()))
    text = path.read_text().replace("claude_agent_max_turns = 40", "claude_agent_max_turns=40")
    path.write_text(text)
    assert budget.lower_cap(path, "claude_agent_max_turns", 10) is True


def write_ledger(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")


def row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "day": "2026-10-23",
        "backend": "claude",
        "kind": "agent_run",
        "cap_share": 1.0,
        "cash_usd": 0,
        "cache_hit": False,
    }
    return {**base, **over}


def test_usage_within_caps(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    write_ledger(path, [row() for _ in range(30)] + [row(backend="local") for _ in range(5)])
    records = budget.read_usage(path)
    assert budget.check_usage(records, caps()) == []
    assert budget.total_cash(records) == 0


def test_usage_over_cap_with_share_and_cache_hits(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    rows = [row(cap_share=0.5) for _ in range(16)] + [row(cache_hit=True) for _ in range(50)]
    write_ledger(path, rows)
    problems = budget.check_usage(budget.read_usage(path), caps())
    assert problems == ["2026-10-23: 16 agent_run calls exceed claude_agent_runs_per_day = 15"]


def test_usage_cash_and_unknown_kind(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    write_ledger(path, [row(cash_usd=0.01), row(kind="mystery")])
    problems = budget.check_usage(budget.read_usage(path), caps())
    assert any("cash_usd" in p for p in problems)
    assert any("mystery" in p for p in problems)


def test_read_usage_missing_and_malformed(tmp_path: Path) -> None:
    assert budget.read_usage(tmp_path / "none.jsonl") == []
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{nope\n")
    with pytest.raises(budget.BudgetError, match="invalid JSON"):
        budget.read_usage(bad)
    bad.write_text("[1]\n")
    with pytest.raises(budget.BudgetError, match="object"):
        budget.read_usage(bad)
    for broken in (
        {"backend": "claude", "kind": "x"},
        row(day="23/10/2026"),
        row(cap_share="1"),
        row(cache_hit="no"),
    ):
        write_ledger(bad, [broken])
        with pytest.raises(budget.BudgetError):
            budget.read_usage(bad)


def test_launch_cap_share(tmp_path: Path) -> None:
    launch = tmp_path / "launch.toml"
    assert budget.load_launch_cap_share(launch) == 1.0
    launch.write_text("cap_share = 0.2\n")
    assert budget.load_launch_cap_share(launch) == 0.2
    assert budget.effective_cap_share({}, launch) == 0.2
    assert budget.effective_cap_share({"CAP_SHARE": "0.1"}, launch) == 0.1
    assert budget.effective_cap_share({"CAP_SHARE": "0.5"}, launch) == 0.2
    launch.write_text("cap_share = true\n")
    with pytest.raises(budget.BudgetError):
        budget.load_launch_cap_share(launch)
    launch.write_text("cap_share = 3\n")
    with pytest.raises(budget.BudgetError):
        budget.load_launch_cap_share(launch)


def test_repo_launch_settings() -> None:
    assert budget.load_launch_cap_share(ROOT / "launch.toml") == 0.2
    effective = budget.load_caps(ROOT / "budget.toml").effective(0.2)
    assert effective.claude_review_runs_per_day == 1
    assert effective.claude_agent_runs_per_day == 6
