from pathlib import Path

import pytest
from mdkit.links import Link, broken_links, find_links, is_local, target_path


def test_finds_links_and_images_with_their_lines() -> None:
    text = "See [setup](setup.md).\n\n![diagram](img/flow.svg) and [site](https://a.invalid)\n"
    assert find_links(text) == [
        Link(1, "setup.md"),
        Link(3, "img/flow.svg", image=True),
        Link(3, "https://a.invalid"),
    ]


def test_links_in_code_are_not_links() -> None:
    text = "```\n[a](a.md)\n```\nUse `[b](b.md)` literally, then [c](c.md).\n"
    assert [link.target for link in find_links(text)] == ["c.md"]


def test_title_is_not_part_of_the_target() -> None:
    assert find_links('[guide](guide.md "The guide")\n') == [Link(1, "guide.md")]


@pytest.mark.parametrize(
    ("target", "local"),
    [
        ("setup.md", True),
        ("../ops/runbook.md", True),
        ("setup.md#install", True),
        ("#install", False),
        ("/handbook/setup.md", False),
        ("https://example.invalid/x", False),
        ("mailto:ops@example.invalid", False),
        ("", False),
    ],
)
def test_which_targets_are_local(target: str, local: bool) -> None:
    assert is_local(target) is local


def test_target_path_is_relative_to_the_page_and_drops_the_anchor() -> None:
    assert target_path(Path("handbook/oncall.md"), "releases.md#afterwards") == Path(
        "handbook/releases.md"
    )


def test_broken_links_are_local_links_to_missing_files(tmp_path: Path) -> None:
    (tmp_path / "present.md").write_text("# Present\n", encoding="utf-8")
    page = tmp_path / "page.md"
    text = (
        "[ok](present.md) [ok too](present.md#present)\n"
        "[missing](missing.md)\n"
        "![missing image](img/none.svg)\n"
        "[web](https://example.invalid) [here](#top)\n"
    )
    assert broken_links(page, text) == [Link(2, "missing.md"), Link(3, "img/none.svg", True)]
