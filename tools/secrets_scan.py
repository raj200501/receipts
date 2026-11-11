"""``make secrets-scan``: fail if any tracked file contains a secret (rule 6).

Two checks over every tracked file:

1. Pattern rules for common credential formats (Anthropic, OpenAI-style, GitHub,
   AWS, Google, Slack, Hugging Face, private keys, bearer headers).
2. Exact values of secret-looking environment variables in the current shell
   (names containing KEY, TOKEN, SECRET, PASSWORD, or CREDENTIAL). This catches
   a real key pasted into a log or artifact even when it has no known prefix.
   Variables that cannot hold a secret are left out: git's ``GIT_CONFIG_KEY_<n>``
   config names, names ending in ``_FILE``, ``_PATH``, or ``_DIR``, absolute
   paths, and dotted config keys such as ``credential.interactive``.

No tracked file is skipped silently. Text of any size is read in pieces, as
UTF-8, or as UTF-16 or UTF-32 when a byte-order mark or the pattern of NUL bytes
shows it. gzip, bzip2, and xz files are decompressed, and zip and tar archives
are read member by member (``archive.zip!member`` in findings). Images, fonts,
PDFs, and audio or video files (``RAW_TYPES``) are read as raw bytes and listed.
Any other binary file, an archive format the standard library cannot read, and
content that expands past ``MAX_EXPANDED`` bytes are findings (``unscannable``),
so the scan fails closed. A symlink's target path is scanned as text.

Findings are reported as ``path:line: rule`` and never include the matched text.
"""

from __future__ import annotations

import argparse
import bz2
import codecs
import gzip
import lzma
import os
import re
import sys
import tarfile
import zipfile
import zlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, cast

from gitutil import repo_root, tracked_files

MIN_ENV_SECRET_LEN = 20
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
NON_SECRET_NAME = re.compile(r"^GIT_CONFIG_KEY_\d+$|_(?:FILE|PATH|DIR)$", re.IGNORECASE)
CONFIG_KEY = re.compile(r"[a-z][a-z0-9.:/_-]*\.[A-Za-z]+")

CHUNK = 1 << 20  # bytes read per step
LONG_LINE = 1 << 22  # a longer line is scanned in overlapping pieces
OVERLAP = 1 << 16  # characters carried between pieces of one long line
HEAD = 8192  # bytes used to tell text, binary, and archives apart
MAX_EXPANDED = 1 << 30  # bytes of content per tracked file before it is unscannable
MAX_DEPTH = 3  # archives inside archives
_RAW = (
    ".png .jpg .jpeg .gif .webp .ico .bmp .tif .tiff .pdf .woff .woff2 .ttf .otf .eot "
    ".mp3 .mp4 .m4a .wav .ogg .oga .webm .mov .avi .mkv .flac"
)
RAW_TYPES = frozenset(_RAW.split())
BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
UNSUPPORTED = (
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
    (b"\x04\x22\x4d\x18", "lz4"),
)
READ_ERRORS = (
    OSError,
    EOFError,
    ValueError,
    RuntimeError,
    NotImplementedError,
    zlib.error,
    lzma.LZMAError,
    tarfile.TarError,
    zipfile.BadZipFile,
)

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


@dataclass
class ScanReport:
    """What a scan found and how each tracked file was read."""

    findings: list[Finding] = field(default_factory=list)
    scanned: int = 0
    raw_only: list[str] = field(default_factory=list)
    not_files: list[str] = field(default_factory=list)


class UnscannableError(Exception):
    """Content that cannot be read as text, raw bytes, or a supported archive."""


def env_secret_values(env: Mapping[str, str]) -> dict[str, str]:
    """Return ``{name: value}`` for environment variables that look like secrets."""
    return {
        name: value
        for name, value in env.items()
        if SECRET_NAME.search(name)
        and not NON_SECRET_NAME.search(name)
        and len(value) >= MIN_ENV_SECRET_LEN
        and " " not in value
        and not value.startswith("/")
        and CONFIG_KEY.fullmatch(value) is None
    }


def scan_pieces(path: str, pieces: Iterable[str], env_secrets: Mapping[str, str]) -> list[Finding]:
    """Scan text that arrives in pieces; line numbers are 1-based.

    Each rule is reported at most once per line. A line longer than ``LONG_LINE``
    is scanned in pieces that overlap by ``OVERLAP`` characters.
    """
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    number = 1

    def check(line: str) -> None:
        rules = [rule for rule, pattern in RULES if pattern.search(line)]
        rules += [f"value of ${name}" for name, value in env_secrets.items() if value in line]
        for rule in rules:
            if (number, rule) not in seen:
                seen.add((number, rule))
                findings.append(Finding(path, number, rule))

    pending = ""
    for piece in pieces:
        *lines, pending = (pending + piece).split("\n")
        for line in lines:
            check(line)
            number += 1
        if len(pending) > LONG_LINE:
            check(pending)
            pending = pending[-OVERLAP:]
    if pending:
        check(pending)
    return findings


def scan_text(path: str, text: str, env_secrets: Mapping[str, str]) -> list[Finding]:
    """Return every finding in ``text``; line numbers are 1-based."""
    return scan_pieces(path, [text], env_secrets)


# Mostly-ASCII UTF-16 or UTF-32 text without a byte-order mark: for each codec, the byte
# columns (offset within a code unit) that are NUL in most units and almost never.
WIDE_CODECS = (
    ("utf-32-le", 4, (1, 2, 3), 0),
    ("utf-32-be", 4, (0, 1, 2), 3),
    ("utf-16-le", 2, (1,), 0),
    ("utf-16-be", 2, (0,), 1),
)


def _nul_share(data: bytes, width: int, column: int) -> float:
    cells = data[column::width]
    return cells.count(0) / len(cells) if cells else 0.0


def text_codec(head: bytes) -> str | None:
    """Return the codec of text content from its first bytes, or None for binary.

    Without a byte-order mark, NUL bytes mean UTF-16 or UTF-32 only when they sit
    in the high-byte columns of mostly-ASCII text and the decoded text is printable.
    """
    for bom, codec in BOMS:
        if head.startswith(bom):
            return codec
    if b"\0" not in head:
        return "utf-8"
    for codec, width, high, low in WIDE_CODECS:
        mostly = 0.5 if width == 2 else 0.9
        if _nul_share(head, width, low) > 0.05:
            continue
        if any(_nul_share(head, width, column) < mostly for column in high):
            continue
        try:
            text = codecs.getincrementaldecoder(codec)("strict").decode(head, final=False)
        except UnicodeDecodeError:
            continue
        printable = sum(c.isprintable() or c in "\t\n\r" for c in text)
        if text and "\0" not in text and printable >= 0.95 * len(text):
            return codec
    return None


def _tar_header(block: bytes) -> bool:
    """True if ``block`` is a tar header with a valid checksum (not text that says ustar)."""
    try:
        tarfile.TarInfo.frombuf(block, "utf-8", "surrogateescape")
    except tarfile.HeaderError:
        return False
    return True


def _archive_kind(head: bytes) -> str | None:
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if head[:3] == b"BZh" and head[3:4] in b"123456789" and head[4:10] == b"1AY&SY":
        return "bzip2"
    if head.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if head[257:262] == b"ustar" and _tar_header(head[:512]):
        return "tar"
    for magic, name in UNSUPPORTED:
        if head.startswith(magic):
            raise UnscannableError(f"{name} archive")
    return None


class _Scanner:
    """Scans one tracked file, following archives, within a byte budget."""

    def __init__(self, env_secrets: Mapping[str, str], report: ScanReport) -> None:
        self.env = env_secrets
        self.report = report
        self.left = MAX_EXPANDED

    def _decoded(self, stream: IO[bytes], codec: str) -> Iterator[str]:
        decoder = codecs.getincrementaldecoder(codec)(errors="replace")
        while chunk := stream.read(CHUNK):
            self.left -= len(chunk)
            if self.left < 0:
                raise UnscannableError(f"content expands past {MAX_EXPANDED} bytes")
            yield decoder.decode(chunk)
        yield decoder.decode(b"", final=True)

    def scan(self, label: str, name: str, stream: IO[bytes], depth: int) -> None:
        """Scan ``stream`` (seekable), named ``name`` for its type, reported as ``label``."""
        head = stream.read(HEAD)
        stream.seek(0)
        kind = _archive_kind(head)
        if kind is not None and depth >= MAX_DEPTH:
            raise UnscannableError("archive nested too deeply")
        inner = name.rsplit(".", 1)[0] if "." in name else name
        if kind == "gzip":
            with gzip.GzipFile(fileobj=stream) as unpacked:
                # GzipFile reads like IO[bytes]; the stubs just do not declare it as one.
                self.scan(label, inner, cast("IO[bytes]", unpacked), depth + 1)
        elif kind == "bzip2":
            with bz2.BZ2File(stream) as unpacked:
                self.scan(label, inner, unpacked, depth + 1)
        elif kind == "xz":
            with lzma.LZMAFile(stream) as unpacked:
                self.scan(label, inner, unpacked, depth + 1)
        elif kind == "zip":
            self._zip(label, stream, depth)
        elif kind == "tar":
            self._tar(label, stream, depth)
        else:
            codec = text_codec(head)
            if codec is None:
                if Path(name).suffix.lower() not in RAW_TYPES:
                    raise UnscannableError("binary file of unknown type")
                codec = "latin-1"
                self.report.raw_only.append(label)
            self.report.findings.extend(scan_pieces(label, self._decoded(stream, codec), self.env))

    def _member(self, label: str, open_member: IO[bytes] | None, name: str, depth: int) -> None:
        if open_member is None:
            return
        with open_member:
            try:
                self.scan(label, name, open_member, depth + 1)
            except UnscannableError as exc:
                self.report.findings.append(Finding(label, 0, f"unscannable: {exc}"))

    def _zip(self, label: str, stream: IO[bytes], depth: int) -> None:
        with zipfile.ZipFile(stream) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if sum(m.file_size for m in members) > self.left:
                raise UnscannableError(f"content expands past {MAX_EXPANDED} bytes")
            for member in members:
                where = f"{label}!{member.filename}"
                self.report.findings.extend(scan_text(where, member.filename, self.env))
                if member.flag_bits & 0x1:
                    self.report.findings.append(Finding(where, 0, "unscannable: encrypted"))
                    continue
                self._member(where, archive.open(member), member.filename, depth)

    def _tar(self, label: str, stream: IO[bytes], depth: int) -> None:
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            members = archive.getmembers()
            if sum(m.size for m in members if m.isfile()) > self.left:
                raise UnscannableError(f"content expands past {MAX_EXPANDED} bytes")
            for member in members:
                where = f"{label}!{member.name}"
                text = f"{member.name}\n{member.linkname}"
                self.report.findings.extend(scan_text(where, text, self.env))
                if member.isfile():
                    self._member(where, archive.extractfile(member), member.name, depth)


def scan_report(root: Path, paths: Iterable[str], env_secrets: Mapping[str, str]) -> ScanReport:
    """Scan ``paths`` under ``root`` and report how each one was read."""
    report = ScanReport()
    for rel in paths:
        path = root / rel
        if path.is_symlink():
            report.findings.extend(scan_text(rel, str(path.readlink()), env_secrets))
            report.scanned += 1
            continue
        if not path.is_file():
            report.not_files.append(rel)
            continue
        try:
            with path.open("rb") as stream:
                _Scanner(env_secrets, report).scan(rel, rel, stream, 0)
        except UnscannableError as exc:
            report.findings.append(Finding(rel, 0, f"unscannable: {exc}"))
        except READ_ERRORS as exc:
            report.findings.append(Finding(rel, 0, f"unscannable: {type(exc).__name__}"))
        else:
            report.scanned += 1
    return report


def scan_files(
    root: Path, paths: Iterable[str], env_secrets: Mapping[str, str]
) -> tuple[list[Finding], int]:
    """Scan ``paths`` under ``root``; returns findings and the number of files read."""
    report = scan_report(root, paths, env_secrets)
    return report.findings, report.scanned


def _listing(paths: Sequence[str]) -> str:
    return ", ".join(paths[:10]) + (f" and {len(paths) - 10} more" if len(paths) > 10 else "")


def main(argv: Sequence[str] | None = None) -> int:
    """Scan tracked files and exit 1 on any finding."""
    parser = argparse.ArgumentParser(description="Scan tracked files for secrets.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    report = scan_report(root, tracked_files(root), env_secret_values(os.environ))
    for finding in report.findings:
        print(finding)
    if report.raw_only:
        print(f"read as raw bytes only ({len(report.raw_only)}): {_listing(report.raw_only)}")
    if report.not_files:
        print(f"tracked paths that are not files ({len(report.not_files)}): ", end="")
        print(_listing(report.not_files))
    if report.findings:
        count = len(report.findings)
        print(f"SECRETS-SCAN: FAIL {count} finding(s) in {report.scanned} tracked files")
        return 1
    print(f"SECRETS-SCAN: CLEAN ({report.scanned} tracked text files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
