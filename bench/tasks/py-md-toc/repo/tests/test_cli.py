from pathlib import Path

import pytest
from mdkit.cli import main

PAGE = """# Guide

## Install **it**

```sh
# not a heading
```

### On Linux

## Use

See [setup](setup.md) and [the site](https://example.invalid).
"""


def _page(tmp_path: Path, text: str = PAGE, name: str = "guide.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_outline_prints_the_heading_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["outline", str(_page(tmp_path))]) == 0
    assert capsys.readouterr().out == "Guide\n  Install it\n    On Linux\n  Use\n"


def test_links_reports_broken_links_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _page(tmp_path)
    assert main(["links", str(path)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"{path}:13: broken link to setup.md",
        "checked 1 local links in 1 page, 1 broken",
    ]


def test_links_exits_0_when_every_file_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _page(tmp_path)
    _page(tmp_path, "# Setup\n", name="setup.md")
    other = _page(tmp_path, "no links\n", name="other.md")
    assert main(["links", str(path), str(other)]) == 0
    assert capsys.readouterr().out == "checked 1 local links in 2 pages, 0 broken\n"


def test_stats_prints_the_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stats", str(_page(tmp_path))]) == 0
    assert capsys.readouterr().out == (
        "words: 11\nheadings: 4\nlinks: 2\nimages: 0\ncode blocks: 1\n"
    )


@pytest.mark.parametrize("command", ["outline", "links", "stats"])
def test_missing_page_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    missing = tmp_path / "missing.md"
    assert main([command, str(missing)]) == 2
    assert capsys.readouterr().err == f"mdkit: cannot read {missing}: no such file\n"


def test_page_that_is_not_utf8_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "latin1.md"
    path.write_bytes("# Caf\xe9\n".encode("latin-1"))
    assert main(["outline", str(path)]) == 2
    assert "not UTF-8 text" in capsys.readouterr().err


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
