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
    local = row(backend="local", kind="local_call", model="qwen2.5-coder-7b-instruct-q4km")
    write_ledger(path, [row() for _ in range(30)] + [local for _ in range(5)])
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


# ---------------------------------------------------------------- turns and model size (H42)
# The ledgers below are small synthetic files under tmp_path, not real usage.


def test_turn_cap_is_checked_per_claude_run(tmp_path: Path) -> None:
    """A Claude run above its effective max-turns cap is a violation (H42)."""
    path = tmp_path / "ledger.jsonl"
    rows = [row(cap_share=0.2, num_turns=100) for _ in range(2)]
    rows += [row(cap_share=0.2, num_turns=8), row(kind="review_run", num_turns=41)]
    rows += [row(kind="agent_run"), row(kind="single_call"), row(cache_hit=True, num_turns=99)]
    write_ledger(path, rows)
    records = budget.read_usage(path)
    assert budget.check_usage(records, caps()) == [
        "2026-10-23: 2 agent_run run(s) took more than claude_agent_max_turns = 8 turns (max 100)",
        "2026-10-23: 1 review_run run(s) took more than claude_agent_max_turns = 40 turns (max 41)",
    ]
    assert budget.runs_without_turns(records) == 1


def test_local_model_size_is_checked(tmp_path: Path) -> None:
    """Local calls must name a model whose size is within local_model_max_params_b."""
    path = tmp_path / "ledger.jsonl"
    local = {"backend": "local", "kind": "local_call"}
    rows = [row(**local, model="qwen2.5-coder-7b-instruct-q4km") for _ in range(3)]
    rows += [row(**local, model="qwen2.5-coder-1.5b-instruct-q4km")]
    rows += [row(**local, model="llama-3.1-70b-instruct-q4km") for _ in range(2)]
    rows += [row(**local, model="mystery-model"), row(**local, model="x-9b", cache_hit=True)]
    write_ledger(path, rows)
    problems = budget.check_usage(budget.read_usage(path), caps())
    assert problems == [
        "local model 'llama-3.1-70b-instruct-q4km' (70B) is above local_model_max_params_b = 8 "
        "in 2 call(s)",
        "local model 'mystery-model' has no total parameter count in its name (1 call(s))",
    ]
    assert budget.model_params_b("granite-3.3-8b-instruct-q4km") == 8
    assert budget.model_params_b("qwen2.5-coder-1.5b-instruct-q4km") == 1.5
    # 8x7b reads as 56 (an upper bound on the total); the largest reading wins.
    assert budget.model_params_b("mixtral-8x7b-moe-47b") == 56


def test_mixture_of_experts_names_are_read_by_their_total(tmp_path: Path) -> None:
    """Review of H42: a mixture-of-experts name is judged by its total, never an expert size.

    NxMb is N experts of M billion, so it reads as N times M. An active or effective
    size (-a3b, e4b) is not a total, so a name with only that fails closed. The
    ledger is a small synthetic file under tmp_path, not real usage. Before the
    fix, 'mixtral-8x7b-v0.1' read as 7 and passed the 8B cap.
    """
    path = tmp_path / "ledger.jsonl"
    local = {"backend": "local", "kind": "local_call"}
    models = ("mixtral-8x7b-v0.1", "qwen1.5-moe-a2.7b-chat-q4km", "m:2x4b", "qwen3-30b-a3b")
    write_ledger(path, [row(**local, model=m) for m in models])
    assert budget.check_usage(budget.read_usage(path), caps()) == [
        "local model 'mixtral-8x7b-v0.1' (56B) is above local_model_max_params_b = 8 in 1 call(s)",
        "local model 'qwen1.5-moe-a2.7b-chat-q4km' has no total parameter count in its name "
        "(1 call(s))",
        "local model 'qwen3-30b-a3b' (30B) is above local_model_max_params_b = 8 in 1 call(s)",
    ]
    readings = {
        "mixtral:8x7b": 56.0,
        "mixtral-8x22b-instruct": 176.0,
        "Mixtral-8X7B-v0.1-Q4_K_M.gguf": 56.0,
        "moe-4\N{MULTIPLICATION SIGN}0.5b": 2.0,
        "SmallThinker-21BA3B-Instruct": 21.0,
        "Kimi-VL-A3B-Instruct": None,
        "gemma-3n-e4b-it": None,
        "big-1t-a3b": None,
        # An expert count of its own (16E) makes the size beside it the active size.
        "Llama-4-Scout-17B-16E-Instruct": None,
        "moe-30b-a3b-128e": 30.0,
        "tuned-7b-lr2e-5": 7.0,
        # Not active sizes: a letter glued before the digits, training tokens (4e1t, 3T).
        "openllama3b": 3.0,
        "stablelm-3b-4e1t": 3.0,
        "TinyLlama-1.1B-intermediate-step-1431k-3T": 1.1,
        # Bits (4bit), context lengths (128k, 1m), and millions are not sizes.
        "llama-3-8b-4bit": 8.0,
        "glm-4-9b-chat-1m": 9.0,
        "phi-3-mini-128k-instruct": None,
        "smollm2-135m-instruct": None,
    }
    assert {name: budget.model_params_b(name) for name in readings} == readings


def test_usage_record_rejects_bad_turns_and_model(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    for broken in (row(num_turns="3"), row(num_turns=True), row(num_turns=-1), row(model=3)):
        write_ledger(bad, [broken])
        with pytest.raises(budget.BudgetError):
            budget.read_usage(bad)


def test_repo_ledger_respects_caps() -> None:
    """The real usage ledger in this checkout passes every ledger check."""
    records = budget.read_usage(ROOT / "artifacts" / "usage" / "ledger.jsonl")
    assert budget.check_usage(records, budget.load_caps(ROOT / "budget.toml")) == []


def test_recorded_digest() -> None:
    digest = "68dc9a82046277d5cf1d4d2aeff00577f85ff1e4c107077b51bae745e45ce531"
    assert budget.recorded_digest(f"{digest}  BUILD_BRIEF.md\n") == digest
    for text in ("", "not-a-digest  BUILD_BRIEF.md\n", digest.upper()):
        with pytest.raises(budget.BudgetError):
            budget.recorded_digest(text)
