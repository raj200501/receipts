"""The project's report: which numbers and figures ``make report`` derives.

Derivations are added here as their artifacts are banked. Each one reads exactly one
artifact; a number that is not derived here cannot appear in README.md or
docs/REPORT.md (``make claimcheck``).

Banked so far: the exploratory outcomes of the G6 smoke runs
(``artifacts/exploratory/smoke_outcomes.json``, written by ``tools/smoke_outcomes.py``).
They are labeled exploratory wherever they appear: one unmanipulated run per task by
one local model, with run-time claim verdicts before the instrument's validation. Also
the Stop hook's wall time on the recorded smoke sessions (``artifacts/hook/latency.json``,
written by ``tools/hook_latency.py``), a measurement of the packaged hook, not a study
outcome.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from receipts.report.build import ReportSpec
from receipts.report.registry import fmt_ci, fmt_pct, fmt_rate, load_artifact
from receipts.report.svg import Bar, bar_chart, text_panel

SPEC = ReportSpec()

SMOKE = "artifacts/exploratory/smoke_outcomes.json"
HOOK_LATENCY = "artifacts/hook/latency.json"


def _summary(data: Any) -> dict[str, Any]:
    summary = data["summary"]
    assert isinstance(summary, dict)
    return summary


def _count(field: str) -> Any:
    def derive(data: Any) -> str:
        return str(_summary(data)[field])

    return derive


def _rate_part(name: str, part: str) -> Any:
    def derive(data: Any) -> str:
        entry = _summary(data)[name]
        if part == "rate":
            return fmt_rate(float(entry["rate"]))
        if part == "pct":
            return fmt_pct(float(entry["rate"]))
        if part == "ci":
            return fmt_ci(float(entry["ci_low"]), float(entry["ci_high"]))
        return str(entry[part])

    return derive


def _verdict(verdict: str) -> Any:
    def derive(data: Any) -> str:
        return str(_summary(data)["claims_by_verdict"].get(verdict, 0))

    return derive


def _language(language: str) -> Any:
    def derive(data: Any) -> str:
        return str(_summary(data)["by_language"].get(language, 0))

    return derive


for _field in ("runs", "runs_with_report", "claims", "turn_cap_reached", "turn_cap_without_report"):
    SPEC.numbers.add(f"smoke.{_field}", SMOKE)(_count(_field))
for _name in (
    "task_success",
    "success_claimed",
    "false_success",
    "success_claims_false",
    "false_success_without_contradicted_claim",
):
    for _part in ("k", "n", "rate", "pct", "ci"):
        SPEC.numbers.add(f"smoke.{_name}.{_part}", SMOKE)(_rate_part(_name, _part))
for _verdict_name in ("supported", "contradicted", "unverifiable"):
    SPEC.numbers.add(f"smoke.claims.{_verdict_name}", SMOKE)(_verdict(_verdict_name))
for _lang in ("python", "typescript"):
    SPEC.numbers.add(f"smoke.language.{_lang}", SMOKE)(_language(_lang))


def _latency_samples(data: Any) -> list[float]:
    return [float(s) for s in data["samples_s"]]


@SPEC.numbers.add("hook.latency.samples", HOOK_LATENCY)
def _latency_count(data: Any) -> str:
    return str(len(_latency_samples(data)))


@SPEC.numbers.add("hook.latency.median_s", HOOK_LATENCY)
def _latency_median(data: Any) -> str:
    return f"{statistics.median(_latency_samples(data)):.2f}"


@SPEC.numbers.add("hook.latency.max_s", HOOK_LATENCY)
def _latency_max(data: Any) -> str:
    return f"{max(_latency_samples(data)):.2f}"


@SPEC.figure("docs/figures/smoke_outcomes.svg")
def smoke_outcomes_figure(root: Path) -> str | None:
    """Headline figure: task success versus claimed success in the smoke runs."""
    path = root / SMOKE
    if not path.is_file():
        return None
    summary = _summary(load_artifact(path))
    bars = []
    # Each bar names its own denominator: task success is over the runs with a hidden-check
    # result, claimed success over the runs that ended with a final report. False success is
    # not drawn: with no task done it equals claimed success, so its bar would repeat one.
    for label, name, series in (
        ("Task done (hidden checks pass)", "task_success", 0),
        ("Report claims success", "success_claimed", 1),
    ):
        entry = summary[name]
        bars.append(
            Bar(
                f"{label}, {entry['k']} of {entry['n']}",
                float(entry["rate"]),
                float(entry["ci_low"]),
                float(entry["ci_high"]),
                series,
            )
        )
    title = (
        f"Exploratory smoke runs ({summary['runs']} runs, Qwen2.5-Coder-7B): "
        "shares with Wilson 95% intervals"
    )
    return bar_chart(bars, title=title, y_label="share", width=720)


DEMO_GOLDEN = "tests/golden/demo_output.txt"
DEMO_RUN = "=== ts-parser-tests"
OMISSION = "  [NOT MENTIONED]"
OMISSIONS_SHOWN = 3


@SPEC.figure("docs/figures/demo_report_card.svg")
def demo_report_card(root: Path) -> str | None:
    """One recorded run's report card, cut from the committed ``make demo`` golden output."""
    path = root / DEMO_GOLDEN
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(DEMO_RUN)]
    if not starts:
        return None
    end = next(
        (i for i in range(starts[0], len(lines)) if lines[i].startswith("Summary:")), len(lines) - 1
    )
    section = [line for line in lines[starts[0] : end + 1] if not line.startswith("    recorded")]
    title = "make demo: one recorded run, checked claim by claim"
    return text_panel(cap_omissions(section), title=title)


def cap_omissions(section: list[str], shown: int = OMISSIONS_SHOWN) -> list[str]:
    """Keep the first ``shown`` omission lines and count the rest in one line."""
    omissions = [i for i, line in enumerate(section) if line.startswith(OMISSION)]
    if len(omissions) <= shown:
        return section
    cut = omissions[shown]
    rest = [i for i in range(cut, len(section)) if not section[i].startswith(OMISSION)]
    more = len(omissions) - shown
    summary = f"{OMISSION} {more} more failed hidden checks that the report does not admit"
    return section[:cut] + [summary] + [section[i] for i in rest]
