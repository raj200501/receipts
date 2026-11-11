"""Repository-wide style rules from docs/BUILD_BRIEF.md section 9 (rule 12)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    paths = [ROOT / p for p in out.split("\0") if p]
    return [p for p in paths if p.is_file() and b"\0" not in p.read_bytes()[:8192]]


def test_no_em_dashes_in_tracked_files() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in tracked_text_files()
        if "\N{EM DASH}" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert offenders == []
