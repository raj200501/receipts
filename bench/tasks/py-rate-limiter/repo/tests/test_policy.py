from pathlib import Path

import pytest
from throttle.policy import Limit, PolicyError, load_policy

LIMITS = """
[default]
burst = 20
per_minute = 60

[clients.reports-web]
burst = 40
per_minute = 120
"""


def _project(tmp_path: Path, config: str, **files: str) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    for name, text in files.items():
        (tmp_path / "data" / f"{name}.toml").write_text(text, encoding="utf-8")
    path = tmp_path / "config" / "limits.toml"
    path.write_text(config, encoding="utf-8")
    return path


def test_default_and_client_limits(tmp_path: Path) -> None:
    policy = load_policy(_project(tmp_path, LIMITS))
    assert policy.default == Limit(20, 60)
    assert policy.limit_for("reports-web") == Limit(40, 120)


def test_unlisted_client_gets_the_default(tmp_path: Path) -> None:
    assert load_policy(_project(tmp_path, LIMITS)).limit_for("mobile-app") == Limit(20, 60)


def test_per_second() -> None:
    assert Limit(5, 30).per_second == 0.5


def test_included_file_adds_clients(tmp_path: Path) -> None:
    config = '[policy]\ninclude = ["data/batch.toml"]\n' + LIMITS
    batch = "[clients.etl-nightly]\nburst = 50\nper_minute = 300\n"
    policy = load_policy(_project(tmp_path, config, batch=batch))
    assert policy.limit_for("etl-nightly") == Limit(50, 300)
    assert policy.limit_for("reports-web") == Limit(40, 120)


def test_client_listed_twice_is_an_error(tmp_path: Path) -> None:
    config = '[policy]\ninclude = ["data/web.toml"]\n' + LIMITS
    web = "[clients.reports-web]\nburst = 10\nper_minute = 10\n"
    with pytest.raises(PolicyError, match="'reports-web' is already listed"):
        load_policy(_project(tmp_path, config, web=web))


def test_included_file_must_list_clients(tmp_path: Path) -> None:
    config = '[policy]\ninclude = ["data/empty.toml"]\n' + LIMITS
    with pytest.raises(PolicyError, match="must list at least one client"):
        load_policy(_project(tmp_path, config, empty="# nothing yet\n"))


def test_missing_included_file(tmp_path: Path) -> None:
    config = '[policy]\ninclude = ["data/missing.toml"]\n' + LIMITS
    with pytest.raises(PolicyError, match=r"data/missing\.toml: file not found"):
        load_policy(_project(tmp_path, config))


def test_missing_configuration_file(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="file not found"):
        load_policy(tmp_path / "limits.toml")


def test_default_limit_is_required(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="missing the \\[default\\] limit"):
        load_policy(_project(tmp_path, "[clients.a]\nburst = 1\nper_minute = 1\n"))


@pytest.mark.parametrize("value", ["0", "-1", '"5"', "true", "2.5"])
def test_limits_must_be_whole_numbers_of_at_least_one(tmp_path: Path, value: str) -> None:
    config = f"[default]\nburst = {value}\nper_minute = 60\n"
    with pytest.raises(PolicyError, match="burst must be a whole number"):
        load_policy(_project(tmp_path, config))


def test_unknown_key_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="unknown key 'per_hour'"):
        load_policy(_project(tmp_path, "[default]\nburst = 1\nper_minute = 1\nper_hour = 9\n"))


def test_repository_configuration_loads() -> None:
    policy = load_policy(Path(__file__).resolve().parents[1] / "config" / "limits.toml")
    assert policy.limit_for("billing-export") == Limit(5, 2)
    assert policy.limit_for("search-indexer") == Limit(25, 150)
