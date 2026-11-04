import io

from textkit.cli import main


def run(capsys, *args):
    status = main(list(args))
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_slug_prints_one_line_per_title(capsys):
    status, out, _ = run(capsys, "slug", "Hello World", "Second Page")
    assert (status, out) == (0, "hello-world\nsecond-page\n")


def test_slug_reads_titles_from_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("First Page\nSecond Page\n"))
    status, out, _ = run(capsys, "slug", "-")
    assert (status, out) == (0, "first-page\nsecond-page\n")


def test_slug_takes_the_default_separator_explicitly(capsys):
    assert run(capsys, "slug", "--separator", "-", "Two Words")[1] == "two-words\n"


def test_an_unknown_separator_is_an_error(capsys):
    status, out, err = run(capsys, "slug", "--separator", "+", "Two Words")
    assert (status, out) == (2, "")
    assert err == "textkit: error: separator must be '-' or '_', not '+'\n"


def test_unique_prints_slugs_for_distinct_titles(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("Overview\nInstall Guide\n"))
    status, out, _ = run(capsys, "unique")
    assert (status, out) == (0, "overview\ninstall-guide\n")
