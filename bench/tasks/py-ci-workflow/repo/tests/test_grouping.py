from releasenotes import group_commits, parse_subject


def _commits(*subjects):
    return [parse_subject(s) for s in subjects]


def test_commits_are_grouped_by_type_in_notes_order():
    groups = group_commits(_commits("fix: b", "feat: a", "docs: c", "perf: d"))
    assert list(groups) == ["Features", "Bug fixes", "Performance", "Documentation"]


def test_commits_keep_their_order_inside_a_section():
    groups = group_commits(_commits("feat: one", "fix: x", "feat: two"))
    assert [c.description for c in groups["Features"]] == ["one", "two"]


def test_empty_sections_are_left_out():
    assert list(group_commits(_commits("fix: only a fix"))) == ["Bug fixes"]


def test_housekeeping_types_stay_out_of_the_notes():
    assert group_commits(_commits("chore: bump", "ci: add job", "test: more", "build: x")) == {}


def test_refactors_stay_out_of_the_notes():
    assert group_commits(_commits("refactor: tidy", "feat: new")).keys() == {"Features"}


def test_a_breaking_commit_goes_first_in_its_own_section():
    groups = group_commits(_commits("feat: a", "fix!: b"))
    assert list(groups) == ["Breaking changes", "Features"]
    assert [c.description for c in groups["Breaking changes"]] == ["b"]


def test_a_breaking_housekeeping_commit_is_still_listed():
    groups = group_commits(_commits("chore!: drop python 3.10"))
    assert list(groups) == ["Breaking changes"]


def test_no_commits_give_no_sections():
    assert group_commits([]) == {}


def test_any_iterable_of_commits_is_accepted():
    groups = group_commits(iter(_commits("feat: a")))
    assert list(groups) == ["Features"]
