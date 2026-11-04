import pytest
from pinwatch import PinwatchError, latest_release, load_releases


def test_releases_are_sorted_oldest_first(write_json):
    path = write_json("releases.json", {"gateway": ["1.5.0", "1.4.0", "1.10.0", "1.9.2"]})
    versions = load_releases(path)["gateway"]
    assert [str(v) for v in versions] == ["1.4.0", "1.5.0", "1.9.2", "1.10.0"]


def test_a_release_sorts_after_its_prereleases(write_json):
    path = write_json("releases.json", {"gateway": ["2.0.0", "2.0.0-rc.1", "1.9.0"]})
    assert str(load_releases(path)["gateway"][-1]) == "2.0.0"


def test_latest_release_skips_prereleases_by_default(data_files):
    releases = load_releases(data_files["releases"])
    assert str(latest_release(releases, "gateway")) == "1.5.0"


def test_latest_release_can_count_prereleases(data_files):
    releases = load_releases(data_files["releases"])
    assert str(latest_release(releases, "gateway", prereleases=True)) == "2.0.0-rc.1"


def test_latest_release_of_an_unknown_component_is_none(data_files):
    assert latest_release(load_releases(data_files["releases"]), "mailer") is None


def test_latest_release_is_none_when_only_prereleases_exist(write_json):
    path = write_json("releases.json", {"mailer": ["0.1.0-rc.1"]})
    assert latest_release(load_releases(path), "mailer") is None


def test_tags_with_a_v_are_read(data_files):
    releases = load_releases(data_files["releases"])
    assert str(latest_release(releases, "scheduler")) == "0.9.2"


def test_load_releases_rejects_a_bad_version(write_json):
    path = write_json("releases.json", {"gateway": ["1.4.0", "next"]})
    with pytest.raises(PinwatchError, match="invalid version 'next'"):
        load_releases(path)


def test_load_releases_needs_lists(write_json):
    with pytest.raises(PinwatchError, match="expected a list of versions"):
        load_releases(write_json("releases.json", {"gateway": "1.4.0"}))


def test_prerelease_numbers_compare_as_numbers(write_json):
    path = write_json("releases.json", {"gateway": ["2.0.0-rc.10", "2.0.0-rc.2", "2.0.0-rc.1"]})
    releases = load_releases(path)
    assert [str(v) for v in releases["gateway"]] == ["2.0.0-rc.1", "2.0.0-rc.2", "2.0.0-rc.10"]
    assert str(latest_release(releases, "gateway", prereleases=True)) == "2.0.0-rc.10"
