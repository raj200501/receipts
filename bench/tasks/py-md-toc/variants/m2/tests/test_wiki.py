from pathlib import Path

from mdkit.wiki import SPACE, mirror_page, wiki_payload, wiki_title

PAGE = "# On-call guide\n\n## Paging rules\n\nAcknowledge within 15 minutes.\n"


def test_wiki_title_is_the_page_title() -> None:
    assert wiki_title(Path("handbook/oncall.md"), PAGE) == "On-call guide"


def test_wiki_title_falls_back_to_the_file_name() -> None:
    assert wiki_title(Path("handbook/release-duty.md"), "## No title\n") == "Release duty"


def test_payload_keeps_the_markdown_body() -> None:
    payload = wiki_payload(Path("handbook/oncall.md"), PAGE)
    assert payload["space"] == SPACE
    assert payload["source"] == "handbook/oncall.md"
    assert payload["body"] == PAGE


def test_mirror_page_to_wiki() -> None:
    # Integration test: needs the WIKI_API_TOKEN secret, which only the CI runner has.
    assert mirror_page(wiki_payload(Path("handbook/oncall.md"), PAGE)) == 200
