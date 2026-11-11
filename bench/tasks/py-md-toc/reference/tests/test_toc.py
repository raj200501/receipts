from pathlib import Path

import pytest
from mdkit.cli import main
from mdkit.toc import TocError, toc_lines, update_toc

PAGE = """# Deploy guide

<!-- toc -->
- [Old entry](#old-entry)
<!-- /toc -->

## Prepare

### Access

#### Tokens

## Roll out
"""


def test_toc_lists_headings_from_level_2_as_nested_links() -> None:
    assert toc_lines(PAGE) == [
        "- [Prepare](#prepare)",
        "  - [Access](#access)",
        "    - [Tokens](#tokens)",
        "- [Roll out](#roll-out)",
    ]


def test_depth_limits_the_levels() -> None:
    assert toc_lines(PAGE, depth=3) == [
        "- [Prepare](#prepare)",
        "  - [Access](#access)",
        "- [Roll out](#roll-out)",
    ]


def test_update_replaces_only_the_marked_lines() -> None:
    updated = update_toc(PAGE)
    assert updated == PAGE.replace(
        "- [Old entry](#old-entry)\n",
        "- [Prepare](#prepare)\n  - [Access](#access)\n    - [Tokens](#tokens)\n"
        "- [Roll out](#roll-out)\n",
    )
    assert update_toc(updated) == updated


def test_markers_in_fenced_code_do_not_count() -> None:
    with pytest.raises(TocError):
        update_toc("# Page\n```\n<!-- toc -->\n<!-- /toc -->\n```\n## Section\n")


def test_toc_command_prints_the_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "deploy.md"
    path.write_text(PAGE, encoding="utf-8")
    assert main(["toc", str(path), "--depth", "2"]) == 0
    assert capsys.readouterr().out == "- [Prepare](#prepare)\n- [Roll out](#roll-out)\n"


def test_toc_write_updates_the_page(tmp_path: Path) -> None:
    path = tmp_path / "deploy.md"
    path.write_text(PAGE, encoding="utf-8")
    assert main(["toc", "--write", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == update_toc(PAGE)


def test_toc_write_without_markers_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plain.md"
    path.write_text("# Plain\n\n## Section\n", encoding="utf-8")
    assert main(["toc", "--write", str(path)]) == 2
    assert "no <!-- toc --> line" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == "# Plain\n\n## Section\n"
