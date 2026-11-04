import pytest
from pinwatch import PinwatchError, allows, load_policy
from pinwatch.cli import main
from pinwatch.pins import parse_version


def version(text):
    return parse_version(text, "test")


@pytest.mark.parametrize(
    ("pinned", "requirement", "expected"),
    [
        ("1.9.3", "^1.4", True),
        ("2.0.0", "^1.4", False),
        ("1.3.9", "^1.4", False),
        ("0.3.9", "^0.3.1", True),
        ("0.4.0", "^0.3.1", False),
        ("1.4.9", "~1.4.2", True),
        ("1.5.0", "~1.4.2", False),
        ("3.1.1", ">=3.0.0,<3.1.2", True),
        ("3.1.2", ">=3.0.0,<3.1.2", False),
        ("1.4.0", ">=1.0,!=1.4.0", False),
        ("0.9.1", "<v1.0.0,>=v0.9.0", True),
        ("2.0.0-rc.10", ">2.0.0-rc.2", True),
    ],
)
def test_allows_ranges(pinned, requirement, expected):
    assert allows(version(pinned), requirement) is expected


def test_a_policy_file_may_hold_ranges(write_json):
    path = write_json("policy.json", {"gateway": "^1.4", "exporter": ">=0.3.0,!=0.3.5"})
    assert load_policy(path) == {"gateway": "^1.4", "exporter": ">=0.3.0,!=0.3.5"}


def test_a_range_that_is_not_one_is_an_error(write_json):
    with pytest.raises(PinwatchError, match=r"invalid policy '>=1\.0,,<2'"):
        load_policy(write_json("policy.json", {"gateway": ">=1.0,,<2"}))


def test_check_uses_ranges(capsys, write_json):
    files = [
        "--pins",
        write_json("pins.json", {"components": {"gateway": "2.0.1", "exporter": "0.3.4"}}),
        "--policy",
        write_json("policy.json", {"gateway": "^1.4", "exporter": "~0.3.1"}),
    ]
    assert main(["check", *files]) == 1
    assert capsys.readouterr().out == "gateway: 2.0.1 is outside the policy ^1.4\n"
