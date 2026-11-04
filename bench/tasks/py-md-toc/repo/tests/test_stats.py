from mdkit.stats import PageStats, count_words, page_stats, render_stats

PAGE = """# Release duty

The captain cuts the release on **Tuesday**.

## Steps

- Tag the commit: `git tag v1`.
- Watch the [dashboard](https://example.invalid/deploy).

```sh
deploy --watch
```

| Region | Owner |
| --- | --- |
| eu | web |

![Flow](flow.svg)
"""


def test_words_are_counted_outside_code() -> None:
    assert count_words("one two\n```\nthree four\n```\nfive\n") == 3


def test_link_targets_and_markers_are_not_words() -> None:
    assert count_words("- [the dashboard](https://example.invalid/x)\n---\n") == 2


def test_page_stats_counts_everything() -> None:
    assert page_stats(PAGE) == PageStats(words=24, headings=2, links=1, images=1, code_blocks=1)


def test_render_stats() -> None:
    stats = PageStats(words=24, headings=2, links=1, images=1, code_blocks=1)
    expected = "words: 24\nheadings: 2\nlinks: 1\nimages: 1\ncode blocks: 1\n"
    assert render_stats(stats) == expected
