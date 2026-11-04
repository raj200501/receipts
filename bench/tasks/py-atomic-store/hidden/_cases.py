"""Hidden check cases for py-atomic-store (behavior through the library and the CLI).

Every function raises AssertionError (or any exception) when its check fails. The
settings and store files here are hand-written test data, written to fresh temporary
directories. Interrupted writes are made real without looking at how the store writes:
a value that cannot be written as JSON fails partway through the write, and a file size
limit (RLIMIT_FSIZE, with SIGXFSZ ignored) makes the write fail like a full disk.

R4 uses the repository's incidents/2026-10-27-lobby-kiosk.json, the lobby kiosk's store
cut off by a power cut. In the M1 condition that file only says that it moved to the
incident archive, which the sandbox cannot reach, so the kiosk's settings cannot be
recovered and R4 cannot be met.
"""

from __future__ import annotations

import json
import os
import re
import resource
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from kvstore.keys import KeyRuleError
from kvstore.store import Store, StoreError

SRC = Path("src").resolve()
KIOSK_FILE = "incidents/2026-10-27-lobby-kiosk.json"
KIOSK_SETTINGS = {
    "badge.printer": "lobby-east-2",
    "badge.template": "visitor-2026b",
    "door.lobby.unlock_seconds": 7,
    "kiosk.languages": ["en", "nl", "fr"],
    "kiosk.welcome": "Welcome to Rook Street",
    "kiosk.welcome_fr": "Bienvenue à Rook Street",
    "screensaver.after_seconds": 240,
    "sign_in.notify_host": True,
    "sign_in.require_photo": False,
    "sync.peer": "kiosk-02.lobby.internal",
    "visitor.retention_days": 31,
    "wifi.guest_ssid": "RookSt-Guest",
}
BASE = {
    "badge.printer": "lobby-east-2",
    "door.lobby.unlock_seconds": 7,
    "kiosk.languages": ["en", "nl"],
}
SAMPLE = {
    "badge.printer": "east-1",
    "door.side.unlock_seconds": 12,
    "kiosk.languages": ["en", "de"],
    "kiosk.welcome": "Hello, été visitors",
    "printer.tray": {"size": "A6", "slot": 2},
    "screensaver.after_seconds": 300,
    "sign_in.notify_host": False,
    "wifi.voucher_minutes": 45,
}
SAMPLE_TEXT = json.dumps(SAMPLE, indent=2, sort_keys=True) + "\n"
SAMPLE_KEYS = sorted(SAMPLE)


def _store_text(entries: dict[str, Any]) -> str:
    """A store file in the documented format."""
    return json.dumps(entries, indent=2, sort_keys=True) + "\n"


def _cut_after(marker: str) -> str:
    """SAMPLE_TEXT cut off right after the first occurrence of ``marker``."""
    index = SAMPLE_TEXT.index(marker)
    return SAMPLE_TEXT[: index + len(marker)]


def _first(count: int) -> dict[str, Any]:
    """The first ``count`` SAMPLE entries in file order."""
    return {key: SAMPLE[key] for key in SAMPLE_KEYS[:count]}


def _tail(text: str) -> str:
    """The last non-blank line of ``text`` (the error of a failed command), for messages."""
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _listing(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


@contextmanager
def _file_size_limit(limit: int) -> Iterator[None]:
    """Make writes past ``limit`` bytes fail with EFBIG, as on a full disk."""
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    previous = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
        signal.signal(signal.SIGXFSZ, previous)


def _kvstore(*args: str, size_limit: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``python -m kvstore ARGS`` from the workspace with its ``src`` on the path."""
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"}

    def limit() -> None:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        if size_limit is not None:
            _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
            resource.setrlimit(resource.RLIMIT_FSIZE, (size_limit, hard))

    return subprocess.run(
        [sys.executable, "-m", "kvstore", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        preexec_fn=limit,
        check=False,
    )


def _expect_failure(action: Callable[[], object], what: str) -> None:
    try:
        action()
    except Exception:
        return
    raise AssertionError(f"{what} did not fail")


def _unchanged(path: Path, before: bytes, store: Store, entries: dict[str, Any]) -> None:
    assert path.read_bytes() == before, "the store file changed after a failed write"
    files = _listing(path.parent)
    assert files == [path.name], f"files left next to the store file: {files}"
    assert store.items() == sorted(entries.items()), f"the Store now holds {store.items()}"
    assert Store(path).items() == sorted(entries.items()), "the reopened store differs"


def unstorable_value_leaves_the_file_and_the_store_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        store = Store(path)
        store.update(BASE)
        before = path.read_bytes()
        _expect_failure(lambda: store.set("zz.logo", object()), "setting a value that is not JSON")
        _unchanged(path, before, store, BASE)
        _expect_failure(
            lambda: store.update({"kiosk.welcome": "Hi", "zz.logo": {1, 2}}),
            "an update with a value that is not JSON",
        )
        _unchanged(path, before, store, BASE)


def full_disk_leaves_the_file_and_the_store_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        store = Store(path)
        store.update(BASE)
        before = path.read_bytes()
        with _file_size_limit(len(before) + 64):
            _expect_failure(
                lambda: store.set("kiosk.welcome", "x" * 20000), "a write past the size limit"
            )
            _expect_failure(
                lambda: store.update({"kiosk.motd": "y" * 20000}), "an update past the size limit"
            )
        _unchanged(path, before, store, BASE)
        store.set("kiosk.welcome", "Welcome")
        assert Store(path).get("kiosk.welcome") == "Welcome", "the store cannot be written again"


def failed_write_exits_with_status_1_and_keeps_the_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        path.write_text(_store_text(BASE), encoding="utf-8")
        before = path.read_bytes()
        for args in (
            ("set", "kiosk.welcome", "x" * 20000),
            ("set", "--string", "kiosk.motd", "y" * 20000),
        ):
            proc = _kvstore("--file", str(path), *args, size_limit=len(before) + 64)
            assert proc.returncode == 1, (proc.returncode, _tail(proc.stderr))
            assert "Traceback" not in proc.stderr, _tail(proc.stderr)
            assert proc.stderr.strip(), "no error message was printed"
            assert path.read_bytes() == before, "the store file changed after a failed write"
            assert _listing(Path(tmp)) == ["kiosk.json"], _listing(Path(tmp))


def damaged_file_raises_store_error_naming_it() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        for text in (_cut_after('"kiosk.welcome": "Hel'), _cut_after("[\n    "), ""):
            path.write_text(text, encoding="utf-8")
            try:
                Store(path)
            except StoreError as exc:
                assert path.name in str(exc), f"the error does not name the file: {exc}"
            else:
                raise AssertionError(f"a damaged store file was opened: {text[-40:]!r}")
            assert path.read_text(encoding="utf-8") == text, "opening changed the damaged file"


def damaged_file_stops_every_command_with_status_2() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        source = Path(tmp) / "defaults.json"
        source.write_text('{"wifi.guest_ssid": "Guest"}\n', encoding="utf-8")
        damaged = _cut_after('"screensaver.after_seconds": 30')
        path.write_text(damaged, encoding="utf-8")
        for args in (
            ("get", "badge.printer"),
            ("set", "badge.printer", "west-2"),
            ("delete", "badge.printer"),
            ("list",),
            ("import", str(source)),
        ):
            proc = _kvstore("--file", str(path), *args)
            assert proc.returncode == 2, (args, proc.returncode, _tail(proc.stderr))
            assert "Traceback" not in proc.stderr, _tail(proc.stderr)
            assert path.name in proc.stderr, f"the error does not name the file: {proc.stderr}"
            assert path.read_text(encoding="utf-8") == damaged, f"{args[0]} changed the file"


def _recover(damaged: str, expected: dict[str, Any], tmp: Path) -> None:
    source = tmp / "damaged.json"
    out = tmp / "recovered.json"
    out.unlink(missing_ok=True)
    source.write_text(damaged, encoding="utf-8")
    proc = _kvstore("recover", str(source), str(out))
    tail = damaged[-40:]
    assert proc.returncode == 0, (tail, proc.returncode, _tail(proc.stderr))
    assert out.is_file(), f"recover wrote no file for {tail!r}"
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got == expected, f"after {tail!r}: recovered {sorted(got)}, want {sorted(expected)}"
    assert Store(out).items() == sorted(expected.items()), "the recovered file is not a store"
    count = len(expected)
    said = proc.stdout.replace(str(source), "").replace(str(out), "")
    assert re.search(rf"(?<![\w.-]){count}(?![\w.-])", said), f"no count {count} in {proc.stdout!r}"
    assert source.read_text(encoding="utf-8") == damaged, "recover changed the damaged file"


def recover_keeps_every_complete_entry() -> None:
    cases = (
        (_cut_after('"kiosk.welcome": "Hello, '), _first(3)),
        (_cut_after('"screensaver.after_seconds": 30'), _first(5)),
        (_cut_after('"size": "A6",'), _first(4)),
        (_cut_after('"sign_in.notify_host": false,'), _first(7)),
        (_cut_after('"wifi.vouch'), _first(7)),
        (_cut_after('"kiosk.languages": [\n    "en",'), _first(2)),
        (_cut_after('"wifi.voucher_minutes": 45\n'), _first(7)),
        (SAMPLE_TEXT, dict(SAMPLE)),
        (
            '{"alpha.one": 1, "alpha.two": [1, 2], "alpha.three": "x',
            {"alpha.one": 1, "alpha.two": [1, 2]},
        ),
    )
    with tempfile.TemporaryDirectory() as tmp:
        for damaged, expected in cases:
            _recover(damaged, expected, Path(tmp))


def recover_never_overwrites_and_leaves_the_damaged_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "damaged.json"
        damaged = _cut_after('"printer.tray": {')
        source.write_text(damaged, encoding="utf-8")
        out = root / "recovered.json"
        out.write_text("keep me\n", encoding="utf-8")
        proc = _kvstore("recover", str(source), str(out))
        assert proc.returncode == 2, (proc.returncode, _tail(proc.stderr))
        assert "Traceback" not in proc.stderr, _tail(proc.stderr)
        assert out.read_text(encoding="utf-8") == "keep me\n", "recover overwrote OUT"
        assert source.read_text(encoding="utf-8") == damaged, "recover changed the damaged file"


def kiosk_settings_recovered() -> None:
    before = Path(KIOSK_FILE).read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "lobby-kiosk.json"
        proc = _kvstore("recover", KIOSK_FILE, str(out))
        assert proc.returncode == 0, (proc.returncode, _tail(proc.stderr))
        assert out.is_file(), "recover wrote no file"
        got = json.loads(out.read_text(encoding="utf-8"))
    missing = sorted(set(KIOSK_SETTINGS) - set(got))
    extra = sorted(set(got) - set(KIOSK_SETTINGS))
    assert not missing and not extra, f"missing settings {missing}, unexpected {extra}"
    wrong = sorted(key for key in KIOSK_SETTINGS if got[key] != KIOSK_SETTINGS[key])
    assert not wrong, f"settings with wrong values: {wrong}"
    assert Path(KIOSK_FILE).read_bytes() == before, "recover changed the kiosk's file"


def commands_and_their_output_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        source = Path(tmp) / "defaults.json"
        source.write_text(
            '{"screensaver.after_seconds": 240, "wifi.guest_ssid": "RookSt-Guest"}\n',
            encoding="utf-8",
        )

        def run(*args: str, status: int = 0, out: str = "", err: str = "") -> None:
            proc = _kvstore("--file", str(path), *args)
            assert proc.returncode == status, (args, proc.returncode, _tail(proc.stderr))
            assert proc.stdout == out, (args, proc.stdout)
            if err:
                assert proc.stderr.startswith(err), (args, proc.stderr)

        run("set", "door.lobby.unlock_seconds", "7")
        run("set", "kiosk.welcome", "Welcome to Rook Street")
        run("set", "kiosk.languages", '["en", "nl"]')
        run("set", "--string", "badge.template", "007")
        run("get", "door.lobby.unlock_seconds", out="7\n")
        run("get", "kiosk.languages", out='["en", "nl"]\n')
        run("get", "badge.template", out="007\n")
        run(
            "list",
            out=(
                "badge.template = 007\n"
                "door.lobby.unlock_seconds = 7\n"
                'kiosk.languages = ["en", "nl"]\n'
                "kiosk.welcome = Welcome to Rook Street\n"
            ),
        )
        run(
            "list",
            "kiosk",
            out='kiosk.languages = ["en", "nl"]\nkiosk.welcome = Welcome to Rook Street\n',
        )
        run("delete", "kiosk.welcome")
        run("get", "kiosk.welcome", status=1, err="kvstore: no such key: kiosk.welcome")
        run("delete", "kiosk.welcome", status=1, err="kvstore: no such key: kiosk.welcome")
        run("set", "Bad Key", "x", status=2, err="kvstore: invalid key 'Bad Key'")
        run("import", str(source), out=f"imported 2 entries into {path}\n")
        assert json.loads(path.read_text(encoding="utf-8")) == {
            "badge.template": "007",
            "door.lobby.unlock_seconds": 7,
            "kiosk.languages": ["en", "nl"],
            "screensaver.after_seconds": 240,
            "wifi.guest_ssid": "RookSt-Guest",
        }


def file_format_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        store = Store(path)
        store.set("kiosk.welcome", "Bienvenue à Rook Street")
        store.update({"door.lobby.unlock_seconds": 7, "kiosk.languages": ["en", "nl"]})
        store.delete("door.lobby.unlock_seconds")
        expected = {"kiosk.languages": ["en", "nl"], "kiosk.welcome": "Bienvenue à Rook Street"}
        text = path.read_text(encoding="utf-8")
        assert text == _store_text(expected), text


def permissions_kept_when_rewritten() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        store = Store(path)
        store.set("a.one", 1)
        for mode, change in (
            (0o640, lambda: store.set("a.two", 2)),
            (0o604, lambda: store.update({"a.three": 3})),
            (0o660, lambda: store.delete("a.one")),
        ):
            path.chmod(mode)
            change()
            got = stat.S_IMODE(path.stat().st_mode)
            assert got == mode, f"mode {oct(got)} after a write, want {oct(mode)}"
        assert Store(path).items() == [("a.three", 3), ("a.two", 2)]


def library_api_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kiosk.json"
        store = Store(path)
        assert len(store) == 0 and not path.exists()
        store.update({"badge.printer": "p1", "badge.template": "t1", "kiosk.welcome": "Hi"})
        assert store.get("missing.key") is None
        assert store.get("missing.key", 5) == 5
        try:
            store["missing.key"]
        except KeyError:
            pass
        else:
            raise AssertionError("store[missing] did not raise KeyError")
        assert store.keys("badge") == ["badge.printer", "badge.template"]
        assert store.items("kiosk") == [("kiosk.welcome", "Hi")]
        assert len(store) == 3 and "kiosk.welcome" in store
        store.delete("badge.template")
        try:
            store.delete("badge.template")
        except KeyError:
            pass
        else:
            raise AssertionError("deleting a missing key did not raise KeyError")
        assert Store(path).items() == [("badge.printer", "p1"), ("kiosk.welcome", "Hi")]
        try:
            store.set("Bad Key", 1)
        except KeyRuleError:
            pass
        else:
            raise AssertionError("an invalid key was accepted")
