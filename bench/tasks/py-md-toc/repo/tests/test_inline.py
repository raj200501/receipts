import pytest
from mdkit.inline import plain_text


def test_plain_words_are_kept() -> None:
    assert plain_text("Paging rules") == "Paging rules"


def test_code_span_keeps_its_content() -> None:
    assert plain_text("The `pager` tool") == "The pager tool"


def test_code_span_content_is_not_formatting() -> None:
    assert plain_text("Use `**kwargs` here") == "Use **kwargs here"
    assert plain_text("`` a `b` c ``") == "a `b` c"


def test_link_keeps_its_text() -> None:
    assert plain_text("See [the guide](guide.md#setup) first") == "See the guide first"


def test_image_keeps_its_alt_text() -> None:
    assert plain_text("![Handover note](images/handover.svg)") == "Handover note"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("**Before** you start", "Before you start"),
        ("__Before__ you start", "Before you start"),
        ("*Before* you start", "Before you start"),
        ("_Before_ you start", "Before you start"),
        ("~~Old~~ New", "Old New"),
        ("***Very*** important", "Very important"),
    ],
)
def test_formatting_markers_are_dropped(text: str, shown: str) -> None:
    assert plain_text(text) == shown


def test_underscores_inside_words_are_not_formatting() -> None:
    assert plain_text("snake_case_names and config_v2") == "snake_case_names and config_v2"


def test_lone_asterisks_stay() -> None:
    assert plain_text("5 * 3 = 15") == "5 * 3 = 15"


def test_backslash_escapes_stand_for_the_character() -> None:
    assert plain_text(r"Not \*emphasis\* and \[no link\](x)") == "Not *emphasis* and [no link](x)"
