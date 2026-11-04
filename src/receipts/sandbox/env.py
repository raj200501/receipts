"""The environment every sandboxed command starts with: an allowlist, never the host's.

:func:`clean_env` builds the whole environment from nothing, so host credentials
(``GH_TOKEN``, ``GITHUB_TOKEN``, ``SSH_AUTH_SOCK``, cloud and API keys, proxy settings)
cannot reach a command, whatever the host environment holds (docs/BUILD_BRIEF.md
section 8). The policy's extra variables are checked as well: a name that looks like a
credential, an agent socket, or a proxy setting is refused, and the two git safety
settings cannot be overridden. Errors name the offending variables, never their values.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from receipts.sandbox.api import SandboxPolicy

#: ``PATH`` for sandboxed commands unless the policy sets its own.
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

#: Fixed values every command gets, besides ``PATH`` and ``HOME``.
BASE_ENV: Mapping[str, str] = MappingProxyType(
    {
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
    }
)

#: Variables the policy may not override: git must never read host configuration.
PROTECTED_NAMES: frozenset[str] = frozenset({"GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"})

_CREDENTIAL_EXACT = frozenset(
    {
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GPG_AGENT_INFO",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SUDO_ASKPASS",
        "NETRC",
        "KUBECONFIG",
        "BOTO_CONFIG",
        "CLAUDECODE",
    }
)
_CREDENTIAL_PREFIXES = (
    "AWS_",
    "ANTHROPIC_",
    "CLAUDE_",
    "OPENAI_",
    "AZURE_",
    "GOOGLE_",
    "GCLOUD_",
    "CLOUDSDK_",
    "GEMINI_",
    "OPENROUTER_",
    "HF_",
    "HUGGING_FACE_",
    "GITHUB_",
    "GH_",
    "GITLAB_",
    "DOCKER_",
    "VAULT_",
)
_CREDENTIAL_PARTS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "API_KEY",
    "APIKEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "_PROXY",
)
_CREDENTIAL_SUFFIXES = ("_KEY", "_PAT", "PROXY")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def is_credential_name(name: str) -> bool:
    """Return True when ``name`` looks like a credential, agent-socket, or proxy variable.

    The test is case-insensitive (``https_proxy`` counts) and deliberately broad: a
    sandboxed command never needs any of these.
    """
    upper = name.upper()
    return (
        upper in _CREDENTIAL_EXACT
        or upper.startswith(_CREDENTIAL_PREFIXES)
        or upper.endswith(_CREDENTIAL_SUFFIXES)
        or any(part in upper for part in _CREDENTIAL_PARTS)
    )


def check_extra_env(extra: Mapping[str, str]) -> None:
    """Raise ValueError unless every extra variable may enter a sandbox.

    Refused: names that are not shell identifiers, values holding a NUL byte, the
    :data:`PROTECTED_NAMES`, and names for which :func:`is_credential_name` is True.
    The message lists names only, never values.
    """
    invalid = sorted(name for name in extra if not _NAME.fullmatch(name))
    if invalid:
        raise ValueError(f"policy.env has invalid variable names: {', '.join(invalid)}")
    protected = sorted(name for name in extra if name in PROTECTED_NAMES)
    if protected:
        raise ValueError(f"policy.env may not override {', '.join(protected)}")
    credentials = sorted(name for name in extra if is_credential_name(name))
    if credentials:
        raise ValueError(
            "policy.env may not carry credential, agent-socket, or proxy variables: "
            + ", ".join(credentials)
        )
    with_nul = sorted(name for name, value in extra.items() if "\0" in value)
    if with_nul:
        raise ValueError(f"policy.env values hold a NUL byte: {', '.join(with_nul)}")


def clean_env(
    workspace_home: str | Path, policy: SandboxPolicy, path: str = DEFAULT_PATH
) -> dict[str, str]:
    """Return the environment for one sandboxed command, built from the allowlist only.

    The result holds ``PATH`` (``path``), ``HOME`` (``workspace_home``), the fixed
    values of :data:`BASE_ENV`, then ``policy.env``, which may replace ``PATH``,
    ``HOME``, and the display settings but not :data:`PROTECTED_NAMES`. Nothing is read
    from the host environment.

    Raises:
        ValueError: ``policy.env`` fails :func:`check_extra_env`, or ``path`` or
            ``workspace_home`` holds a NUL byte.
    """
    home = str(workspace_home)
    if "\0" in home or "\0" in path:
        raise ValueError("PATH and HOME may not hold a NUL byte")
    check_extra_env(policy.env)
    env = {"PATH": path, "HOME": home, **BASE_ENV}
    env.update(policy.env)
    return env
