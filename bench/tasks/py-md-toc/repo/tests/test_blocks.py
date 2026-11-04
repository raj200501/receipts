from mdkit.blocks import CLOSE, CODE, OPEN, TEXT, count_code_blocks, scan


def kinds(text: str) -> list[str]:
    return [line.kind for line in scan(text)]


def test_backtick_fence_marks_its_lines_as_code() -> None:
    text = "intro\n```python\nx = 1\n```\noutro\n"
    assert kinds(text) == [TEXT, OPEN, CODE, CLOSE, TEXT]


def test_tilde_fence_marks_its_lines_as_code() -> None:
    assert kinds("~~~\n# not a heading\n~~~\n") == [OPEN, CODE, CLOSE]


def test_fence_closes_only_with_the_same_character() -> None:
    assert kinds("```\n~~~\n```\n") == [OPEN, CODE, CLOSE]


def test_shorter_fence_does_not_close_the_block() -> None:
    assert kinds("````\n```\n````\nafter\n") == [OPEN, CODE, CLOSE, TEXT]


def test_unclosed_fence_runs_to_the_end_of_the_page() -> None:
    assert kinds("text\n```\ncode\nmore code\n") == [TEXT, OPEN, CODE, CODE]


def test_fence_may_be_indented_by_up_to_three_spaces() -> None:
    assert kinds("   ```\ncode\n   ```\n") == [OPEN, CODE, CLOSE]
    assert kinds("    ```\ntext\n") == [TEXT, TEXT]


def test_backticks_in_the_info_string_do_not_open_a_fence() -> None:
    assert kinds("``` not `a` fence\ntext\n") == [TEXT, TEXT]


def test_lines_keep_their_numbers_and_text() -> None:
    lines = scan("a\n\n```\nb\n```\n")
    assert [(line.number, line.text, line.code) for line in lines] == [
        (1, "a", False),
        (2, "", False),
        (3, "```", True),
        (4, "b", True),
        (5, "```", True),
    ]


def test_code_blocks_are_counted() -> None:
    text = "```\na\n```\n\n~~~ sh\nb\n~~~\n```\nunclosed\n"
    assert count_code_blocks(text) == 3
    assert count_code_blocks("no code here\n") == 0
