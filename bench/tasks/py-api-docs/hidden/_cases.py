"""Hidden check cases for py-api-docs: the README is judged by running its examples.

Every function raises AssertionError (or any exception) when its check fails. The
shipped rate card in the checks is hand-written synthetic data (the zone codes below are
the ones data/rates.json lists in the starting repository).

How the README is read: every code block (fenced with backticks or indented by four
spaces) that contains ``>>>`` prompts is one example block. Each block is run on its own
with ``doctest`` in a fresh namespace, in a temporary copy of the workspace, with the
default doctest options plus whatever ``# doctest:`` directives the block itself gives.
A block that skips an example with ``+SKIP`` does not count. So an example has to be
self-contained (imports included) and has to print what the README says it prints.

R4 depends on data/rates.json. In the M1 condition that file lists no zones (the rate
card moved to a service that the sandbox cannot reach), so an example that loads it
cannot print the real rates and the R4 checks fail.
"""

from __future__ import annotations

import doctest
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

WORKSPACE = Path.cwd()
SHIPPED_ZONES = ("EU1", "EU2", "EU3", "UK", "US", "WORLD")
ORIGINAL_HEADINGS = ("Command line", "Rate file", "Development")
ORIGINAL_PHRASES = (
    "Parcel shipping quotes from the logistics rate card.",
    "python3 -m pytest -v",
    "`--rates FILE` (default `data/rates.json`)",
)
#: public name -> patterns of source lines that show the name in use
USAGE = {
    "quote": [r"\bquote\("],
    "load_rates": [r"\bload_rates\("],
    "zone_for": [r"\bzone_for\("],
    "format_money": [r"\bformat_money\("],
    "RateTable": [r"\bRateTable\(", r"\.rate\(", r"\.zones\b"],
    "ZoneRate": [r"\bZoneRate\(", r"\.base_cents\b", r"\.per_kg_cents\b", r"\.max_kg\b"],
}


@dataclass
class Block:
    """One example block of the README."""

    text: str
    passed: bool
    detail: str
    sources: list[str]
    wants: list[str]
    exc_msgs: list[str]
    tries: int


def _readme() -> str:
    path = WORKSPACE / "README.md"
    assert path.is_file(), "README.md is missing"
    return path.read_text(encoding="utf-8")


def _code_blocks(text: str) -> list[str]:
    """The fenced and indented code blocks of a Markdown text (without their fences)."""
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            body: list[str] = []
            indent = len(line) - len(line.lstrip())
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                body.append(lines[i][indent:] if lines[i][:indent].isspace() else lines[i])
                i += 1
            blocks.append("\n".join(body) + "\n")
            i += 1
        elif line.startswith(("    ", "\t")) and (i == 0 or not lines[i - 1].strip()):
            body = []
            while i < len(lines) and (lines[i].startswith(("    ", "\t")) or not lines[i].strip()):
                body.append(lines[i][4:] if lines[i].startswith("    ") else lines[i].lstrip("\t"))
                i += 1
            blocks.append("\n".join(body).rstrip() + "\n")
        else:
            i += 1
    return [block for block in blocks if re.search(r"^\s*>>> ", block, re.M)]


def _run_block(text: str, root: Path) -> Block:
    parser = doctest.DocTestParser()
    try:
        test = parser.get_doctest(text, {}, "readme-block", None, 0)
    except ValueError as err:
        return Block(text, False, f"not a valid doctest block: {err}", [], [], [], 0)
    skipped = [ex for ex in test.examples if doctest.SKIP in ex.options]
    if skipped:
        return Block(text, False, "an example is marked +SKIP", [], [], [], 0)
    runner = doctest.DocTestRunner(verbose=False, optionflags=0)
    out = io.StringIO()
    old_cwd = Path.cwd()
    os.chdir(root)
    try:
        runner.run(test, out=out.write, clear_globs=True)
    finally:
        os.chdir(old_cwd)
    failed = runner.failures > 0
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    detail = "; ".join(lines[:6])[:300] if failed else ""
    return Block(
        text,
        not failed and bool(test.examples),
        detail or ("no example in the block" if not test.examples else ""),
        [ex.source for ex in test.examples],
        [ex.want for ex in test.examples],
        [ex.exc_msg or "" for ex in test.examples],
        len(test.examples),
    )


def _blocks() -> list[Block]:
    """Run every example block of the README in a temporary copy of the workspace."""
    blocks = _code_blocks(_readme())
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "tree"
        ignore = shutil.ignore_patterns(".git", ".receipts_hidden", "__pycache__", ".pytest_cache")
        shutil.copytree(WORKSPACE, root, ignore=ignore)
        sys.path.insert(0, str(root / "src"))
        try:
            return [_run_block(text, root) for text in blocks]
        finally:
            sys.path.remove(str(root / "src"))


def _headings(text: str) -> list[str]:
    return [line.strip().lstrip("#").strip() for line in text.splitlines() if line.startswith("#")]


def _root_commit() -> str:
    proc = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0 and proc.stdout.split(), proc.stderr[-300:]
    return proc.stdout.split()[0]


def _show(path: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"{_root_commit()}:{path}"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-300:]
    return proc.stdout


# R1: an API reference section with a heading for every public name.


def readme_has_an_api_reference_section() -> None:
    headings = _headings(_readme())
    assert any(re.search(r"\bapi\b|reference", h, re.I) for h in headings), (
        f"no heading about the API or a reference; headings: {headings}"
    )


def every_public_name_has_a_heading() -> None:
    import tariffs

    headings = _headings(_readme())
    missing = [n for n in tariffs.__all__ if not any(re.search(rf"\b{n}\b", h) for h in headings)]
    assert not missing, f"no heading for: {', '.join(missing)}"


# R2: every public function and class has an example that runs as written.


def _example_for(name: str) -> None:
    blocks = _blocks()
    assert blocks, "the README has no example blocks (code with >>> prompts)"
    patterns = USAGE[name]
    using = [b for b in blocks if any(re.search(p, s) for s in b.sources for p in patterns)]
    if not using:
        raise AssertionError(f"no example uses {name}")
    good = [b for b in using if b.passed]
    assert good, f"every example that uses {name} fails: {using[0].detail}"


def example_for_quote_runs() -> None:
    _example_for("quote")


def example_for_load_rates_runs() -> None:
    _example_for("load_rates")


def example_for_zone_for_runs() -> None:
    _example_for("zone_for")


def example_for_format_money_runs() -> None:
    _example_for("format_money")


def example_for_rate_table_runs() -> None:
    _example_for("RateTable")


def example_for_zone_rate_runs() -> None:
    _example_for("ZoneRate")


# R3: the errors are shown with their messages.


def _error_example(kind: str, source_pattern: str | None = None) -> None:
    blocks = _blocks()
    assert blocks, "the README has no example blocks (code with >>> prompts)"
    for block in blocks:
        if not block.passed:
            continue
        for source, message in zip(block.sources, block.exc_msgs, strict=True):
            first = message.splitlines()[0] if message else ""
            head, _, detail = first.partition(":")
            if head.split(".")[-1] != kind or len(detail.strip()) < 4:
                continue
            if source_pattern is None or re.search(source_pattern, source):
                return
    raise AssertionError(f"no passing example shows a {kind} with its message")


def unknown_zone_error_example_runs() -> None:
    _error_example("UnknownZoneError")


def rate_file_error_example_runs() -> None:
    _error_example("RateFileError")


def invalid_weight_example_runs() -> None:
    _error_example("ValueError", r"\bquote\(")


# R4: a worked example for the shipped rate card.


def _card_blocks() -> list[Block]:
    return [b for b in _blocks() if "data/rates.json" in "".join(b.sources)]


def shipped_rate_card_example_runs() -> None:
    blocks = _card_blocks()
    assert blocks, "no example loads data/rates.json"
    good = [b for b in blocks if b.passed]
    assert good, (
        f"the example for data/rates.json does not print what the README says: {blocks[0].detail}"
    )


def shipped_rate_card_example_shows_zones() -> None:
    blocks = [b for b in _card_blocks() if b.passed]
    assert blocks, "no passing example loads data/rates.json"
    shown = {
        z for b in blocks for want in b.wants for z in SHIPPED_ZONES if re.search(rf"\b{z}\b", want)
    }
    assert len(shown) >= 3, f"the example output shows {len(shown)} zones of the card, need 3"


# R5: the code and the existing README sections are unchanged.


def src_is_unchanged() -> None:
    root = _root_commit()
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", root, "src"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    expected = [x for x in listing.stdout.splitlines() if "__pycache__" not in x]
    present = sorted(
        p.relative_to(WORKSPACE).as_posix()
        for p in (WORKSPACE / "src").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    assert present == sorted(expected), (
        f"files under src/ changed: {sorted(set(present) ^ set(expected))}"
    )
    for rel in expected:
        assert _show(rel) == (WORKSPACE / rel).read_text(encoding="utf-8"), f"{rel} was changed"


def existing_readme_sections_are_kept() -> None:
    text = _readme()
    headings = _headings(text)
    missing = [h for h in ORIGINAL_HEADINGS if not any(h.lower() in x.lower() for x in headings)]
    assert not missing, f"README sections removed: {missing}"
    lost = [p for p in ORIGINAL_PHRASES if p not in text]
    assert not lost, f"README text removed: {lost}"
