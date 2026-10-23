"""Tests for the numbers registry, SVG figures, and report build (synthetic artifacts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from receipts.report import build as report_build
from receipts.report import registry, svg
from receipts.report.build import ReportSpec


def make_spec() -> ReportSpec:
    spec = ReportSpec()

    @spec.numbers.add("e1.rate", "artifacts/e1/results.json")
    def rate(data: Any) -> str:
        return registry.fmt_rate(data["rate"])

    @spec.numbers.add("e1.ci", "artifacts/e1/results.json")
    def ci(data: Any) -> str:
        return registry.fmt_ci(data["lo"], data["hi"])

    @spec.numbers.add("e1.rows", "artifacts/e1/runs.jsonl")
    def rows(data: Any) -> str:
        return str(len(data))

    @spec.numbers.add("absent", "artifacts/none.json")
    def absent(data: Any) -> str:
        return "never"

    @spec.figure("docs/figures/headline.svg")
    def headline(root: Path) -> str | None:
        data = json.loads((root / "artifacts/e1/results.json").read_text())
        return svg.bar_chart(
            [
                svg.Bar("a", data["rate"], data["lo"], data["hi"]),
                svg.Bar("b", 0.5, 0.4, 0.6, series=1),
            ],
            title="Synthetic",
            y_label="rate",
        )

    @spec.figure("docs/figures/skipped.svg")
    def skipped(root: Path) -> str | None:
        return None

    return spec


def seed(root: Path, rate: float = 0.25) -> None:
    (root / "artifacts/e1").mkdir(parents=True, exist_ok=True)
    (root / "artifacts/e1/results.json").write_text(
        json.dumps({"rate": rate, "lo": 0.2, "hi": 0.3})
    )
    (root / "artifacts/e1/runs.jsonl").write_text('{"a": 1}\n\n{"a": 2}\n')


def test_build_registry_and_manifest(tmp_path: Path) -> None:
    seed(tmp_path)
    manifest = report_build.build(tmp_path, make_spec())
    numbers = json.loads((tmp_path / report_build.NUMBERS).read_text())["numbers"]
    assert numbers["e1.rate"]["value"] == "0.25" and numbers["e1.ci"]["value"] == "[0.20, 0.30]"
    assert numbers["e1.rows"]["value"] == "2" and "absent" not in numbers
    assert numbers["e1.rate"]["derivation"].endswith("make_spec.<locals>.rate")
    assert manifest["figures"] == ["docs/figures/headline.svg"]
    assert (tmp_path / "docs/figures/headline.svg").read_text().startswith("<svg")
    assert report_build.reproduce(tmp_path, make_spec()) == []
    seed(tmp_path, rate=0.5)
    assert any("differs" in p for p in report_build.reproduce(tmp_path, make_spec()))
    (tmp_path / "docs/figures/headline.svg").unlink()
    assert any("not committed" in p for p in report_build.reproduce(tmp_path, make_spec()))


def test_numbers_only(tmp_path: Path) -> None:
    seed(tmp_path)
    out = tmp_path / "x" / "n.json"
    numbers = report_build.numbers_only(tmp_path, make_spec(), out)
    assert set(numbers) == {"e1.rate", "e1.ci", "e1.rows"} and out.is_file()


def test_registry_rules() -> None:
    reg = registry.Registry()
    reg.add("k", "a.json")(lambda d: "1")
    with pytest.raises(ValueError, match="twice"):
        reg.add("k", "b.json")(lambda d: "2")
    assert len(reg) == 1
    spec = ReportSpec()
    with pytest.raises(ValueError, match="SVG"):
        spec.figure("docs/figures/x.png")(lambda root: None)
    assert registry.fmt_pct(0.234) == "23%" and registry.fmt_rate(0.2345, 3) == "0.234"


def test_bar_chart_requires_bars_and_escapes() -> None:
    with pytest.raises(ValueError):
        svg.bar_chart([], title="t", y_label="y")
    out = svg.bar_chart([svg.Bar("<a>", 1.2, -0.1, 0.9)], title="A & B", y_label="y")
    assert "&lt;a&gt;" in out and "A &amp; B" in out and "prefers-color-scheme: dark" in out


def test_project_spec_builds_on_an_empty_tree(tmp_path: Path) -> None:
    from receipts.report.spec import SPEC

    manifest = report_build.build(tmp_path, SPEC)
    assert manifest["numbers"] == len(
        json.loads((tmp_path / report_build.NUMBERS).read_text())["numbers"]
    )
