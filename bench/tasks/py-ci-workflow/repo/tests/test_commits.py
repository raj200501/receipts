import pytest
from releasenotes import Commit, parse_subject


def test_a_plain_subject_is_parsed():
    assert parse_subject("fix: handle empty input") == Commit("fix", None, "handle empty input")


def test_a_scope_is_kept():
    commit = parse_subject("feat(api): add paging")
    assert commit == Commit("feat", "api", "add paging")


def test_a_bang_marks_a_breaking_change():
    commit = parse_subject("refactor!: rename the config keys")
    assert commit is not None
    assert commit.breaking is True


def test_a_bang_after_the_scope_marks_a_breaking_change():
    commit = parse_subject("feat(api)!: drop the v1 routes")
    assert commit == Commit("feat", "api", "drop the v1 routes", True)


def test_a_breaking_change_prefix_in_the_text_is_recognized():
    commit = parse_subject("fix: BREAKING CHANGE: ids are strings now")
    assert commit == Commit("fix", None, "ids are strings now", True)


def test_surrounding_whitespace_is_ignored():
    assert parse_subject("  docs: fix a typo \n") == Commit("docs", None, "fix a typo")


@pytest.mark.parametrize(
    "subject",
    [
        "",
        "just a message",
        "Merge branch 'main'",
        "fix:missing space",
        "fix: ",
        "feat(): empty scope",
    ],
)
def test_subjects_outside_the_style_give_none(subject):
    assert parse_subject(subject) is None


def test_an_unknown_type_gives_none():
    assert parse_subject("wip: half done") is None


@pytest.mark.parametrize(
    "kind", ["feat", "fix", "perf", "docs", "refactor", "test", "build", "ci", "chore"]
)
def test_every_known_type_is_accepted(kind):
    commit = parse_subject(f"{kind}: something")
    assert commit is not None
    assert commit.type == kind


def test_a_commit_is_immutable():
    commit = parse_subject("fix: a")
    with pytest.raises(AttributeError):
        commit.type = "feat"  # type: ignore[misc]
