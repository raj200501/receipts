"""Tests for the allowlisted command environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from receipts.sandbox.api import SandboxPolicy
from receipts.sandbox.env import (
    BASE_ENV,
    DEFAULT_PATH,
    PROTECTED_NAMES,
    check_extra_env,
    clean_env,
    inside,
    is_credential_name,
)


def test_clean_env_is_exactly_the_allowlist() -> None:
    env = clean_env("/work/ws", SandboxPolicy())
    assert env == {
        "PATH": DEFAULT_PATH,
        "HOME": "/work/ws",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
    }


def test_host_credentials_never_reach_the_environment(planted_secrets: dict[str, str]) -> None:
    env = clean_env(Path("/work/ws"), SandboxPolicy(env={"PYTEST_ADDOPTS": "-q"}))
    for name, value in planted_secrets.items():
        assert name not in env
        assert value not in env.values()
    assert not [k for k in env if k.startswith(("AWS_", "ANTHROPIC_"))]
    assert "HTTPS_PROXY" not in env and "https_proxy" not in env


def test_policy_env_is_added_and_may_replace_path_and_home() -> None:
    policy = SandboxPolicy(env={"PATH": "/tools/bin:/usr/bin", "HOME": "/work/ws/.home", "X": "1"})
    env = clean_env("/work/ws", policy)
    assert env["PATH"] == "/tools/bin:/usr/bin"
    assert env["HOME"] == "/work/ws/.home"
    assert env["X"] == "1"
    assert {k: env[k] for k in BASE_ENV} == dict(BASE_ENV)
    assert clean_env("/work/ws", SandboxPolicy(env={"HOME": "/work/ws/"}))["HOME"] == "/work/ws/"


@pytest.mark.parametrize(
    "home", ["/elsewhere", "/work/wsx", "/work/ws/../other", "relative/home", "/work"]
)
def test_home_outside_the_workspace_is_refused(home: str) -> None:
    with pytest.raises(ValueError, match="HOME must be the workspace"):
        clean_env("/work/ws", SandboxPolicy(env={"HOME": home}))


def test_inside() -> None:
    assert inside("/a/b", "/a/b") and inside("/a/b/c/../d", "/a/b") and inside("/x", "/")
    assert not inside("/a/bc", "/a/b") and not inside("a/b", "a") and not inside("/a", "/a/b")


def test_path_argument_sets_path() -> None:
    assert clean_env("/w", SandboxPolicy(), "/only/bin")["PATH"] == "/only/bin"


@pytest.mark.parametrize(
    "name",
    [
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GH_PAT",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GIT_ASKPASS",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SHARED_CREDENTIALS_FILE",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDECODE",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "GIT_PROXY_COMMAND",
        "OPENAI_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_API_KEY",
        "HF_TOKEN",
        "MY_SERVICE_TOKEN",
        "DB_PASSWORD",
        "TWINE_PASSWORD",
        "SECRET_KEY",
        "DJANGO_SECRET_KEY",
        "STRIPE_SECRET_KEY",
        "SIGNING_KEY",
        "NPM_CONFIG__AUTH",
        "BASIC_AUTH",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "KUBECONFIG",
        "NETRC",
    ],
)
def test_credential_like_policy_variables_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        clean_env("/w", SandboxPolicy(env={name: "synthetic-value"}))


def test_refusal_names_variables_but_never_values() -> None:
    with pytest.raises(ValueError) as caught:
        clean_env("/w", SandboxPolicy(env={"GH_TOKEN": "synthetic-do-not-print"}))
    assert "GH_TOKEN" in str(caught.value)
    assert "synthetic-do-not-print" not in str(caught.value)


@pytest.mark.parametrize(
    "name",
    [
        "PYTHONHASHSEED",
        "GIT_AUTHOR_NAME",
        "PYTEST_ADDOPTS",
        "CI",
        "TZ",
        "NODE_OPTIONS",
        "TOKENIZERS_PARALLELISM",
        "HF_HUB_OFFLINE",
        "HF_DATASETS_OFFLINE",
        "GH_PAGER",
        "DOCKER_BUILDKIT",
        "SORT_KEY",
        "PRIMARY_KEY",
        "PATH_KEYS",
        "GOOGLE_CLOUD_PROJECT",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AZURE_TENANT_ID",
        "NO_PROXY",
        "no_proxy",
        "GITHUB_ACTIONS",
        "OAUTH_CLIENT_ID",
        "SESSION_COOKIE_SECURE",
    ],
)
def test_ordinary_variables_are_allowed(name: str) -> None:
    assert not is_credential_name(name)
    assert clean_env("/w", SandboxPolicy(env={name: "v"}))[name] == "v"


@pytest.mark.parametrize("name", sorted(PROTECTED_NAMES))
def test_git_safety_settings_cannot_be_overridden(name: str) -> None:
    with pytest.raises(ValueError, match="may not override"):
        clean_env("/w", SandboxPolicy(env={name: "/home/user/.gitconfig"}))


@pytest.mark.parametrize("name", ["1BAD", "A-B", "", "A B", "X=Y"])
def test_invalid_variable_names_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="invalid variable names"):
        check_extra_env({name: "v"})


def test_nul_bytes_are_refused() -> None:
    with pytest.raises(ValueError, match="NUL"):
        check_extra_env({"X": "a\0b"})
    with pytest.raises(ValueError, match="NUL"):
        clean_env("/w\0x", SandboxPolicy())
    with pytest.raises(ValueError, match="NUL"):
        clean_env("/w", SandboxPolicy(), "/bin\0")


def test_credential_names_are_matched_case_insensitively() -> None:
    assert is_credential_name("gh_token")
    assert is_credential_name("Http_Proxy")
    assert not is_credential_name("LANG")
