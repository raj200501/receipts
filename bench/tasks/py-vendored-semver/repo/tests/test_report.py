from pinwatch.pins import parse_version
from pinwatch.report import Row, format_status, format_violation, show


def version(text):
    return parse_version(text, "test")


def test_show_prints_the_version_without_a_v():
    assert show(version("v0.9.1")) == "0.9.1"


def test_show_keeps_the_prerelease():
    assert show(version("2.1.0-rc.2")) == "2.1.0-rc.2"


def test_show_a_missing_version_is_a_dash():
    assert show(None) == "-"


def test_format_status_lines_are_aligned():
    rows = [
        Row("gateway", version("1.4.2"), version("1.5.0"), "behind"),
        Row("mailer", version("0.1.0"), None, "unknown"),
    ]
    assert format_status(rows) == [
        "gateway     1.4.2         1.5.0         behind",
        "mailer      0.1.0         -             unknown",
    ]


def test_format_violation_names_the_policy():
    line = format_violation("gateway", version("1.3.0"), ">=1.4.0")
    assert line == "gateway: 1.3.0 is outside the policy >=1.4.0"
