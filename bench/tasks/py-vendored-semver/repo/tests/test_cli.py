import pytest
from pinwatch.cli import main


def run(capsys, *args):
    status = main(list(args))
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def paths(files):
    return ["--pins", files["pins"], "--releases", files["releases"], "--policy", files["policy"]]


def test_status_table(capsys, data_files):
    status, out, _ = run(capsys, "status", *paths(data_files))
    assert status == 0
    assert out.splitlines() == [
        "gateway     1.4.2         1.5.0         behind",
        "scheduler   0.9.1         0.9.2         behind",
        "ledger      2.1.0-rc.2    2.1.0-rc.2    current",
    ]


def test_status_marks_a_pin_outside_the_policy(capsys, write_json, data_files):
    pins = write_json("old.json", {"components": {"gateway": "1.3.0"}})
    files = {**data_files, "pins": pins}
    status, out, _ = run(capsys, "status", *paths(files))
    assert status == 0
    assert out.strip() == "gateway     1.3.0         1.5.0         outside policy"


def test_status_a_component_without_releases_is_unknown(capsys, write_json, data_files):
    pins = write_json("new.json", {"components": {"mailer": "0.1.0"}})
    status, out, _ = run(capsys, "status", *paths({**data_files, "pins": pins}))
    assert status == 0
    assert out.strip() == "mailer      0.1.0         -             unknown"


def test_check_passes_when_every_pin_is_allowed(capsys, data_files):
    status, out, _ = run(capsys, "check", *paths(data_files))
    assert (status, out) == (0, "all pins are within the policy\n")


def test_check_lists_the_pins_outside_the_policy(capsys, write_json, data_files):
    pins = write_json("old.json", {"components": {"gateway": "1.3.0", "scheduler": "1.0.0"}})
    status, out, _ = run(capsys, "check", *paths({**data_files, "pins": pins}))
    assert status == 1
    assert out.splitlines() == [
        "gateway: 1.3.0 is outside the policy >=1.4.0",
        "scheduler: 1.0.0 is outside the policy <v1.0.0",
    ]


def test_latest_prints_the_newest_release(capsys, data_files):
    status, out, _ = run(capsys, "latest", "gateway", "--releases", data_files["releases"])
    assert (status, out) == (0, "1.5.0\n")


def test_latest_with_pre_counts_prereleases(capsys, data_files):
    args = ["latest", "gateway", "--pre", "--releases", data_files["releases"]]
    assert run(capsys, *args)[1] == "2.0.0-rc.1\n"


def test_latest_of_an_unknown_component_is_an_error(capsys, data_files):
    status, out, err = run(capsys, "latest", "mailer", "--releases", data_files["releases"])
    assert (status, out) == (2, "")
    assert err.startswith("pinwatch: error: no releases of 'mailer' in ")


def test_a_missing_file_is_an_error(capsys, data_files, tmp_path):
    files = {**data_files, "pins": str(tmp_path / "nope.json")}
    status, out, err = run(capsys, "check", *paths(files))
    assert (status, out) == (2, "")
    assert err.startswith("pinwatch: error: cannot read ")


def test_a_bad_version_is_an_error(capsys, write_json, data_files):
    pins = write_json("bad.json", {"components": {"gateway": "banana"}})
    status, _, err = run(capsys, "status", *paths({**data_files, "pins": pins}))
    assert status == 2
    assert err.endswith(": gateway: invalid version 'banana'\n")


def test_a_bad_policy_is_an_error(capsys, write_json, data_files):
    policy = write_json("bad-policy.json", {"gateway": "~~1"})
    status, _, err = run(capsys, "check", *paths({**data_files, "policy": policy}))
    assert status == 2
    assert err.endswith(": gateway: invalid policy '~~1'\n")


def test_a_command_is_required():
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2
