import io

from releasenotes.cli import main

LOG = "feat(api): add paging\nfix: handle empty input\nMerge branch 'main'\nchore: bump\n"


def test_notes_prints_markdown_for_the_subjects(capsys):
    status = main(["notes", "--version", "1.4.0", "--date", "2026-11-03"], stdin=io.StringIO(LOG))
    assert status == 0
    out = capsys.readouterr().out
    assert out.startswith("## 1.4.0 (2026-11-03)\n")
    assert "- **api:** add paging" in out
    assert "bump" not in out


def test_lines_outside_the_style_are_skipped(capsys):
    assert main(["bump", "1.0.0"], stdin=io.StringIO("Merge branch 'main'\nfix: a\n")) == 0
    assert capsys.readouterr().out == "1.0.1\n"


def test_bump_prints_the_next_version(capsys):
    assert main(["bump", "1.3.2"], stdin=io.StringIO(LOG)) == 0
    assert capsys.readouterr().out == "1.4.0\n"


def test_bump_prints_the_same_version_when_nothing_needs_a_release(capsys):
    assert main(["bump", "1.3.2"], stdin=io.StringIO("chore: bump\n")) == 0
    assert capsys.readouterr().out == "1.3.2\n"


def test_a_bad_version_is_an_error(capsys):
    assert main(["bump", "one"], stdin=io.StringIO(LOG)) == 2
    assert "releasenotes: error: not a MAJOR.MINOR.PATCH version" in capsys.readouterr().err


def test_a_missing_command_is_a_usage_error(capsys):
    assert main([], stdin=io.StringIO("")) == 2
    assert capsys.readouterr().err


def test_notes_needs_a_version_and_a_date(capsys):
    assert main(["notes", "--version", "1.0.0"], stdin=io.StringIO("")) == 2
    assert "--date" in capsys.readouterr().err
