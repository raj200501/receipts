"""``make secrets-scan``: fail if any tracked file contains a secret (rule 6).

Two checks over every tracked file:

1. Pattern rules for common credential formats (Anthropic, OpenAI-style, GitHub,
   AWS, Google, Slack, Hugging Face, private keys, bearer headers).
2. Exact values of secret-looking environment variables in the current shell
   (names containing KEY, TOKEN, SECRET, PASSWORD, or CREDENTIAL). This catches
   a real key pasted into a log or artifact even when it has no known prefix.

Findings are reported as ``path:line: rule`` and never include the matched text.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from gitutil import repo_root, tracked_files

MAX_BYTES = 5_000_000
MIN_ENV_SECRET_LEN = 20
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-style-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("openrouter-key", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{32,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("bearer-header", re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._~+/-]{20,}")),
)


@dataclass(frozen=True)
class Finding:
    """One secret found in a file. Holds the rule name, never the secret."""

    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def env_secret_values(env: Mapping[str, str]) -> dict[str, str]:
    """Return ``{name: value}`` for environment variables that look like secrets."""
    return {
        name: value
        for name, value in env.items()
        if SECRET_NAME.search(name) and len(value) >= MIN_ENV_SECRET_LEN and " " not in value
    }


def scan_text(path: str, text: str, env_secrets: Mapping[str, str]) -> list[Finding]:
    """Return every finding in ``text``; line numbers are 1-based."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in RULES:
            if pattern.search(line):
                findings.append(Finding(path, number, rule))
        for name, value in env_secrets.items():
            if value in line:
                findings.append(Finding(path, number, f"value of ${name}"))
    return findings


def scan_files(
    root: Path, paths: Iterable[str], env_secrets: Mapping[str, str]
) -> tuple[list[Finding], int]:
    """Scan ``paths`` under ``root``; returns findings and the number of files read."""
    findings: list[Finding] = []
    scanned = 0
    for rel in paths:
        path = root / rel
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        scanned += 1
        findings.extend(scan_text(rel, data.decode("utf-8", errors="replace"), env_secrets))
    return findings, scanned


def main(argv: Sequence[str] | None = None) -> int:
    """Scan tracked files and exit 1 on any finding."""
    parser = argparse.ArgumentParser(description="Scan tracked files for secrets.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    findings, scanned = scan_files(root, tracked_files(root), env_secret_values(os.environ))
    for finding in findings:
        print(finding)
    if findings:
        print(f"SECRETS-SCAN: FAIL {len(findings)} finding(s) in {scanned} tracked files")
        return 1
    print(f"SECRETS-SCAN: CLEAN ({scanned} tracked text files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
