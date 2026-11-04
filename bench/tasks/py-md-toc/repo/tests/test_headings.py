import pytest
from mdkit.headings import Heading, find_headings, outline, parse_heading


def test_headings_have_levels_text_and_lines() -> None:
    text = "# Title\n\nIntro.\n\n## Section\n\n###### Deep\n"
    assert find_headings(text) == [
        Heading(1, "Title", 1),
        Heading(2, "Section", 5),
        Heading(6, "Deep", 7),
    ]


def test_closing_hashes_are_not_part_of_the_text() -> None:
    assert parse_heading("## Setup ##", 1) == Heading(2, "Setup", 1)
    assert parse_heading("### Notes #####   ", 1) == Heading(3, "Notes", 1)


def test_hash_inside_the_text_stays() -> None:
    assert parse_heading("## C# and F#", 1) == Heading(2, "C# and F#", 1)


@pytest.mark.parametrize("line", ["#hashtag", "####### seven", "    # four spaces", "text # no"])
def test_lines_that_are_not_headings(line: str) -> None:
    assert parse_heading(line, 1) is None


@pytest.mark.parametrize("line", [" # one", "  # two", "   # three"])
def test_up_to_three_spaces_of_indentation(line: str) -> None:
    heading = parse_heading(line, 1)
    assert heading is not None
    assert heading.level == 1


def test_empty_heading() -> None:
    assert parse_heading("##", 4) == Heading(2, "", 4)


def test_headings_in_fenced_code_are_skipped() -> None:
    text = "# Title\n```sh\n# a shell comment\n```\n## After\n"
    assert [heading.text for heading in find_headings(text)] == ["Title", "After"]


def test_title_is_shown_without_formatting() -> None:
    heading = parse_heading("## The `pager` **tool**", 1)
    assert heading is not None
    assert heading.text == "The `pager` **tool**"
    assert heading.title == "The pager tool"


def test_outline_indents_two_spaces_per_level() -> None:
    headings = find_headings("# Guide\n## Install\n### On Linux\n## Use\n")
    assert outline(headings) == ["Guide", "  Install", "    On Linux", "  Use"]
