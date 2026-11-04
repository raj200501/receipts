from textkit import fold


def test_ascii_text_is_unchanged():
    assert fold("plain text, 12 things") == "plain text, 12 things"


def test_an_empty_string_stays_empty():
    assert fold("") == ""


def test_the_result_is_a_string():
    assert isinstance(fold("anything"), str)
