"""The environment every sandboxed command starts with: an allowlist, never the host's.

:func:`clean_env` builds the whole environment from nothing, so host credentials
(``GH_TOKEN``, ``GITHUB_TOKEN``, ``SSH_AUTH_SOCK``, cloud and API keys, proxy settings)
cannot reach a command, whatever the host environment holds (docs/BUILD_BRIEF.md
section 8). The policy's extra variables are checked as a second line of defence
against a caller passing a secret on by mistake. Refused are names that hold or point
at secrets (a word such as ``TOKEN``, ``SECRET``, ``PASSWORD``, or ``CREDENTIALS``, or
a qualified key such as ``API_KEY`` or ``ACCESS_KEY``), agent and daemon sockets and
credential helpers (``SSH_AUTH_SOCK``, ``DOCKER_HOST``, ``GIT_ASKPASS``), proxy
settings (they can carry credentials; ``NO_PROXY`` is allowed), and model-provider
settings (``ANTHROPIC_*``, ``CLAUDE_*``, ``OPENAI_*``, as the brief's billing guard
lists). Ordinary settings that merely contain such letters, such as
``TOKENIZERS_PARALLELISM``, ``HF_HUB_OFFLINE``, ``AWS_REGION``, or ``SORT_KEY``, are
allowed. The two git safety settings cannot be overridden, and ``HOME`` may only move
inside the workspace. Errors name the offending variables, never their values.
"""

from __future__ import annotations

import posixpath
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

#: Names that point at credentials, credential helpers, or agent and daemon sockets.
CREDENTIAL_NAMES: frozenset[str] = frozenset(
    {
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GPG_AGENT_INFO",
        "GNUPGHOME",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SUDO_ASKPASS",
        "NETRC",
        "KUBECONFIG",
        "BOTO_CONFIG",
        "AWS_CONFIG_FILE",
        "CLOUDSDK_CONFIG",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "DOCKER_CERT_PATH",
        "CLAUDECODE",
    }
)

#: Prefixes of model-provider settings (docs/BUILD_BRIEF.md section 8, billing guard).
PROVIDER_PREFIXES: tuple[str, ...] = ("ANTHROPIC_", "CLAUDE_", "OPENAI_", "GEMINI_", "OPENROUTER_")

#: Words of a name (split at underscores) that mark a secret value.
SECRET_WORDS: frozenset[str] = frozenset(
    {
        "TOKEN",
        "TOKENS",
        "SECRET",
        "SECRETS",
        "PASSWORD",
        "PASSWORDS",
        "PASSWD",
        "PASSPHRASE",
        "CREDENTIAL",
        "CREDENTIALS",
        "APIKEY",
        "PAT",
    }
)

#: Words that, right before ``KEY`` or ``KEYS``, make the key a secret (``API_KEY``).
KEY_QUALIFIERS: frozenset[str] = frozenset(
    {
        "API",
        "ACCESS",
        "SECRET",
        "PRIVATE",
        "SIGNING",
        "ENCRYPTION",
        "MASTER",
        "AUTH",
        "CLIENT",
        "DEPLOY",
        "SSH",
        "GPG",
        "SERVICE",
        "ACCOUNT",
        "LICENSE",
        "SESSION",
    }
)

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def is_credential_name(name: str) -> bool:
    """Return True when ``name`` holds or points at a secret, a socket, or a proxy.

    The test is case-insensitive (``https_proxy`` counts) and works on the words of
    the name: see the module docstring for what is refused and what is not.
    """
    upper = name.upper()
    words = [word for word in upper.split("_") if word]
    if upper in CREDENTIAL_NAMES or upper.startswith(PROVIDER_PREFIXES):
        return True
    if "PROXY" in words and upper != "NO_PROXY":
        return True
    if any(word in SECRET_WORDS for word in words) or (words and words[-1] == "AUTH"):
        return True
    return any(
        word in ("KEY", "KEYS") and index > 0 and words[index - 1] in KEY_QUALIFIERS
        for index, word in enumerate(words)
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


def inside(path: str, directory: str) -> bool:
    """True when absolute ``path`` is ``directory`` or lies under it (lexically)."""
    if not posixpath.isabs(path):
        return False
    top = posixpath.normpath(directory)
    normalized = posixpath.normpath(path)
    return normalized == top or normalized.startswith(top.rstrip("/") + "/")


def clean_env(
    workspace_home: str | Path, policy: SandboxPolicy, path: str = DEFAULT_PATH
) -> dict[str, str]:
    """Return the environment for one sandboxed command, built from the allowlist only.

    The result holds ``PATH`` (``path``), ``HOME`` (``workspace_home``, the
    workspace), the fixed values of :data:`BASE_ENV`, then ``policy.env``, which may
    replace ``PATH`` and the display settings, and ``HOME`` with a path inside the
    workspace, but not :data:`PROTECTED_NAMES`. Nothing is read from the host
    environment.

    Raises:
        ValueError: ``policy.env`` fails :func:`check_extra_env` or sets ``HOME``
            outside ``workspace_home``, or ``path`` or ``workspace_home`` holds a NUL
            byte.
    """
    home = str(workspace_home)
    if "\0" in home or "\0" in path:
        raise ValueError("PATH and HOME may not hold a NUL byte")
    check_extra_env(policy.env)
    if "HOME" in policy.env and not inside(policy.env["HOME"], home):
        raise ValueError("policy.env HOME must be the workspace or a directory inside it")
    env = {"PATH": path, "HOME": home, **BASE_ENV}
    env.update(policy.env)
    return env
