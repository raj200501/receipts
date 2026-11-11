import pytest
from releasenotes import next_version, parse_subject, suggest_bump


def _bump(*subjects):
    return suggest_bump([parse_subject(s) for s in subjects])


def test_a_breaking_commit_is_major():
    assert _bump("fix: a", "feat!: b") == "major"


def test_a_feature_is_minor():
    assert _bump("fix: a", "feat: b") == "minor"


def test_a_fix_is_patch():
    assert _bump("fix: a", "docs: b") == "patch"


def test_a_performance_change_is_patch():
    assert _bump("perf: faster") == "patch"


def test_housekeeping_needs_no_release():
    assert _bump("docs: a", "chore: b", "refactor: c") == "none"


def test_no_commits_need_no_release():
    assert suggest_bump([]) == "none"


@pytest.mark.parametrize(
    ("current", "bump", "expected"),
    [
        ("1.3.2", "major", "2.0.0"),
        ("1.3.2", "minor", "1.4.0"),
        ("1.3.2", "patch", "1.3.3"),
        ("1.3.2", "none", "1.3.2"),
        ("0.0.9", "patch", "0.0.10"),
        ("9.9.9", "major", "10.0.0"),
    ],
)
def test_next_version_applies_the_bump(current, bump, expected):
    assert next_version(current, bump) == expected


@pytest.mark.parametrize("current", ["1.3", "v1.3.2", "1.3.2-rc1", "", "one.two.three"])
def test_a_version_must_be_major_minor_patch(current):
    with pytest.raises(ValueError, match=r"not a MAJOR\.MINOR\.PATCH version"):
        next_version(current, "patch")


def test_an_unknown_bump_is_rejected():
    with pytest.raises(ValueError, match="unknown bump"):
        next_version("1.0.0", "huge")
