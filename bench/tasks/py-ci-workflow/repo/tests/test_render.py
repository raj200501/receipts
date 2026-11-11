from releasenotes import group_commits, parse_subject, render_markdown


def _notes(*subjects):
    commits = [parse_subject(s) for s in subjects]
    return render_markdown("1.4.0", "2026-11-03", group_commits(commits))


def test_the_heading_has_version_and_date():
    assert _notes("fix: a").startswith("## 1.4.0 (2026-11-03)\n")


def test_each_section_has_a_heading_and_a_list():
    text = _notes("feat: add paging", "fix: handle empty input")
    assert "### Features\n\n- add paging\n" in text
    assert "### Bug fixes\n\n- handle empty input\n" in text


def test_a_scope_is_shown_in_bold():
    assert "- **api:** add paging" in _notes("feat(api): add paging")


def test_a_release_without_user_facing_changes_says_so():
    text = _notes("chore: bump", "ci: add job")
    assert text == "## 1.4.0 (2026-11-03)\n\nNo user-facing changes.\n"


def test_the_notes_end_with_a_newline():
    assert _notes("fix: a").endswith("\n")


def test_breaking_changes_come_before_features():
    text = _notes("feat: a", "feat!: b")
    assert text.index("### Breaking changes") < text.index("### Features")
