import pytest
from pinwatch import PinwatchError, allows, load_policy
from pinwatch.pins import parse_version


def version(text):
    return parse_version(text, "test")


@pytest.mark.parametrize(
    ("pinned", "requirement", "expected"),
    [
        ("1.4.2", ">=1.4.0", True),
        ("1.3.9", ">=1.4.0", False),
        ("1.4.0", ">1.4.0", False),
        ("0.9.1", "<1.0.0", True),
        ("1.0.0", "<1.0.0", False),
        ("0.3.5", "!=0.3.5", False),
        ("0.3.4", "!=0.3.5", True),
        ("1.12.0", ">= 1.11.0", True),
        ("2.0.0", "==2.0.0", True),
        ("2.0.0-rc.1", ">=2.0.0", False),
        ("0.9.1", "<v1.0.0", True),
    ],
)
def test_allows(pinned, requirement, expected):
    assert allows(version(pinned), requirement) is expected


def test_load_policy_reads_requirements(data_files):
    assert load_policy(data_files["policy"]) == {"gateway": ">=1.4.0", "scheduler": "<v1.0.0"}


def test_load_policy_rejects_a_requirement_that_is_not_one(write_json):
    path = write_json("policy.json", {"gateway": "newer than 1.4"})
    with pytest.raises(PinwatchError, match=r"gateway: invalid policy 'newer than 1\.4'"):
        load_policy(path)


def test_load_policy_rejects_a_non_string(write_json):
    with pytest.raises(PinwatchError, match="invalid policy 3"):
        load_policy(write_json("policy.json", {"gateway": 3}))
