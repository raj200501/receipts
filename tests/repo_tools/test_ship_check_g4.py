"""Gate G4 of tools/ship_check.py on synthetic projects (findings H10 and H11).

Every project here is SYNTHETIC: a stand-in ``tools/demo.py`` that prints fixed text,
made only to exercise ``ship_check.g4``. The "model server" in the H10 cases is a tiny
HTTP server in this test process that returns a canned string; no model is involved,
and nothing here is a model result or a real-world result.
"""

from __future__ import annotations

import http.server
import shutil
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import ship_check

Commit = Callable[[Path, str], str]

pytestmark = pytest.mark.skipif(
    sys.prefix == sys.base_prefix or not (shutil.which("uv") and shutil.which("make")),
    reason="needs make, uv, and a virtualenv to link synthetic projects to",
)

MAKEFILE = """\
# SYNTHETIC test project for tools/ship_check.py gate G4 (not a real project).
PY ?= 3.11
PYTEST_ARGS ?=
RUN := uv run --no-sync

setup:
\t@true

demo:
\t$(RUN) python tools/demo.py {flags}
"""

PYPROJECT = '[project]\nname = "synthetic-demo"\nversion = "0"\nrequires-python = ">=3.11"\n'

DEMO = '''"""SYNTHETIC offline demo for the tools/ship_check.py G4 tests."""

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "demo_output.txt"
URL = "{url}"


def render() -> str:
    if not URL:
        return "receipts demo (synthetic)\\nclaim 1: supported\\n"
    # Proxy variables are ignored, as receipts.client.backends does for local servers.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({{}}))
    with opener.open(URL, timeout=5) as reply:
        return "Model summary: " + reply.read().decode() + "\\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--write-golden" in argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8")
    if "--check" in argv:
        ok = GOLDEN.is_file() and GOLDEN.read_text(encoding="utf-8") == text
        print("DEMO: PASS" if ok else "DEMO: FAIL")
        return 0 if ok else 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''
OUTPUT = "receipts demo (synthetic)\nclaim 1: supported\n"
REPLY = "LIVE MODEL SAYS: three claims checked"


def build(
    root: Path,
    commit: Commit,
    *,
    golden: str | None = OUTPUT,
    flags: str = "--check",
    url: str = "",
) -> ship_check.Context:
    """Write a SYNTHETIC G4 project into ``root``, commit it, and return its Context."""
    layout = {
        "Makefile": MAKEFILE.format(flags=flags),
        "pyproject.toml": PYPROJECT,
        ".gitignore": ".venv\n",
        "tools/demo.py": DEMO.format(url=url),
    }
    if golden is not None:
        layout["tests/golden/demo_output.txt"] = golden
    for rel, text in layout.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    sha = commit(root, "synthetic G4 project")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)


@pytest.fixture
def model_server() -> Iterator[str]:
    """A local HTTP server standing in for a model server; yields its URL."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = REPLY.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/completions"
    finally:
        server.shutdown()
        server.server_close()


def needs_isolation() -> None:
    if ship_check.network_isolation() is None:
        pytest.skip("no working network isolation (unshare -rn, bwrap, sandbox-exec)")


def test_matching_golden_passes(git_repo: Path, commit: Commit) -> None:
    needs_isolation()
    assert "matches golden" in ship_check.g4(build(git_repo, commit))


def test_stale_golden_fails(git_repo: Path, commit: Commit) -> None:
    needs_isolation()
    ctx = build(git_repo, commit, golden="an older output\n")
    with pytest.raises(ship_check.GateError, match="make demo failed"):
        ship_check.g4(ctx)


# ---------------------------------------------------------------- H10 (old code: PASS)


def test_no_working_isolator_is_a_fail(
    git_repo: Path, commit: Commit, model_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A host without unshare, bwrap, or sandbox-exec (macOS without them, blocked user
    # namespaces). A dead proxy cannot stop a client that ignores proxy variables.
    which = shutil.which
    blocked = {"unshare", "bwrap", "sandbox-exec"}
    monkeypatch.setattr(shutil, "which", lambda name: None if name in blocked else which(name))
    ctx = build(git_repo, commit, golden=f"Model summary: {REPLY}\n", url=model_server)
    with pytest.raises(ship_check.GateError, match="cannot isolate the network"):
        ship_check.g4(ctx)


def test_demo_cannot_reach_a_local_model_server(
    git_repo: Path, commit: Commit, model_server: str
) -> None:
    needs_isolation()
    ctx = build(git_repo, commit, golden=f"Model summary: {REPLY}\n", url=model_server)
    with pytest.raises(ship_check.GateError, match="make demo failed offline"):
        ship_check.g4(ctx)


def test_an_isolator_must_prove_it_cuts_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``env`` runs the probe unchanged, so the probe still reaches the listener.
    monkeypatch.setattr(ship_check, "ISOLATORS", (("fake", ("env",)),))
    assert ship_check.network_isolation() is None


# ---------------------------------------------------------------- H11 (old code: PASS)


def test_demo_that_rewrites_its_golden_fails(git_repo: Path, commit: Commit) -> None:
    needs_isolation()
    ctx = build(git_repo, commit, golden="an older output\n", flags="--write-golden --check")
    with pytest.raises(ship_check.GateError, match="differs from the committed"):
        ship_check.g4(ctx)


def test_golden_must_be_committed(git_repo: Path, commit: Commit) -> None:
    needs_isolation()
    ctx = build(git_repo, commit, golden=None, flags="--write-golden --check")
    with pytest.raises(ship_check.GateError, match="not committed"):
        ship_check.g4(ctx)


def test_golden_rewritten_before_the_gate_does_not_count(git_repo: Path, commit: Commit) -> None:
    # As if an earlier gate's tests regenerated the golden in the clone before G4 runs.
    needs_isolation()
    ctx = build(git_repo, commit, golden="an older output\n")
    (ctx.clone / "tests" / "golden" / "demo_output.txt").write_text(OUTPUT, encoding="utf-8")
    with pytest.raises(ship_check.GateError, match="differs from the committed"):
        ship_check.g4(ctx)
