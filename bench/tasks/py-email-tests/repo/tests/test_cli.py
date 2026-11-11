import io

from addrcheck.cli import main


def test_a_valid_address_prints_ok_and_exits_zero(capsys):
    assert main(["ada@example.org"]) == 0
    assert capsys.readouterr().out == "ok ada@example.org\n"


def test_an_invalid_address_prints_the_reason_and_exits_one(capsys):
    assert main(["ada.example.org"]) == 1
    assert capsys.readouterr().out == "invalid 'ada.example.org': missing_at\n"


def test_one_bad_address_among_good_ones_fails_the_run(capsys):
    assert main(["a@example.org", "oops", "b@example.org"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["ok a@example.org", "invalid 'oops': missing_at", "ok b@example.org"]


def test_no_address_is_a_usage_error(capsys):
    assert main([]) == 2
    assert "no address given" in capsys.readouterr().err


def test_an_unknown_option_is_a_usage_error(capsys):
    assert main(["--frobnicate", "a@example.org"]) == 2
    assert capsys.readouterr().err


def test_dash_reads_addresses_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a@example.org\nb@example.org\n"))
    assert main(["-"]) == 0
    assert capsys.readouterr().out.splitlines() == ["ok a@example.org", "ok b@example.org"]


def test_block_rejects_the_listed_domain(capsys):
    assert main(["--block", "spam.example", "ada@spam.example"]) == 1
    assert "blocked_domain" in capsys.readouterr().out


def test_list_reasons_prints_every_code(capsys):
    assert main(["--list-reasons"]) == 0
    out = capsys.readouterr().out
    assert "missing_at: the address has no @" in out
    assert "blocked_domain:" in out
