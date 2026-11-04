"""Hidden check cases for py-vendored-semver (behavior through the command line).

Every function raises AssertionError (or any exception) when its check fails. The
components, versions, and advisories in the inline data are hand-written test data. Most
checks write their own pin, release, and policy files to a fresh temporary directory and
pass them with --pins, --releases, and --policy, so they do not depend on the repository's
data. The R4 checks use the repository's own data/advisories.json with pins of their own:
in the M1 condition that file lists no advisories (it says the list moved to a service the
sandbox cannot reach), so the advisories that apply to the pins cannot be reported and R4
cannot be met.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

SRC = Path("src").resolve()
ADVISORIES = Path("data/advisories.json").resolve()

#: Data in the style of the repository's own: tags with a leading v, spaces in requirements.
OLD_PINS = {"gateway": "1.4.2", "scheduler": "v0.9.1", "notifier": "1.12.0", "exporter": "0.3.4"}
OLD_RELEASES = {
    "gateway": ["1.3.0", "1.4.0", "1.4.2", "1.5.0", "2.0.0-rc.1"],
    "scheduler": ["v0.8.0", "v0.9.1", "v0.9.2"],
    "notifier": ["1.10.0", "1.11.0", "1.12.0"],
    "exporter": ["0.3.0", "0.3.4", "0.4.0"],
}
OLD_POLICY = {
    "gateway": ">=1.4.0",
    "scheduler": "<v1.0.0",
    "notifier": ">= 1.11.0",
    "exporter": "!=0.3.5",
}


def pinwatch(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``python -m pinwatch`` with the workspace's ``src`` on the import path."""
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "pinwatch", *args],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )


@contextmanager
def project(
    pins: Mapping[str, str] | None = None,
    releases: Mapping[str, Sequence[str]] | None = None,
    policy: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Temporary data files; yields their paths under the keys pins, releases, and policy."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = {}
        documents = {
            "pins": {"components": dict(pins or {})},
            "releases": {name: list(texts) for name, texts in (releases or {}).items()},
            "policy": dict(policy or {}),
        }
        for key, document in documents.items():
            path = root / f"{key}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            paths[key] = str(path)
        yield paths


def options(paths: Mapping[str, str], *keys: str) -> list[str]:
    """``--pins P --releases R ...`` for the given keys."""
    return [item for key in keys for item in (f"--{key}", paths[key])]


def expect(proc: subprocess.CompletedProcess[str], stdout: str, status: int = 0) -> None:
    """The command exited with ``status`` and printed exactly ``stdout``."""
    assert proc.returncode == status, (proc.args[3:], proc.returncode, proc.stderr[-500:])
    assert proc.stdout == stdout, (proc.args[3:], proc.stdout, stdout)


def run_in_vendor(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in an isolated interpreter that can import the vendored modules."""
    full = f"import sys; sys.path[:0] = [{str(Path('vendor').resolve())!r}]\n{code}"
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", full],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def vendored_tinyver_is_2_0_0() -> None:
    code = (
        "import tinyver\n"
        "assert tinyver.__version__ == '2.0.0', tinyver.__version__\n"
        "assert tinyver.parse('1.0.0-rc.10') > tinyver.parse('1.0.0-rc.2')\n"
        "assert tinyver.parse('1.9.3') in tinyver.Range('^1.4')\n"
        "assert isinstance(tinyver.parse('1.2.3'), tinyver.Version)\n"
    )
    proc = run_in_vendor(code)
    assert proc.returncode == 0, proc.stderr[-500:]


def commands_run_with_the_new_library() -> None:
    with project(OLD_PINS, OLD_RELEASES, OLD_POLICY) as paths:
        expect(
            pinwatch(["check", *options(paths, "pins", "policy")]),
            "all pins are within the policy\n",
        )
        expect(pinwatch(["latest", "gateway", *options(paths, "releases")]), "1.5.0\n")
        proc = pinwatch(["status", *options(paths, "pins", "releases", "policy")])
        assert proc.returncode == 0, proc.stderr[-500:]
        assert len(proc.stdout.splitlines()) == 4, proc.stdout
    probe = (
        "from pinwatch.cli import main\n"
        "import tinyver\n"
        "assert tinyver.__version__ == '2.0.0'\n"
        "assert main(['latest', 'x', '--releases', sys.argv[1]]) == 0\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        feed = Path(tmp) / "feed.json"
        feed.write_text(json.dumps({"x": ["1.0.0", "1.1.0"]}), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        proc = subprocess.run(
            [sys.executable, "-c", f"import sys\n{probe}", str(feed)],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        assert proc.stdout == "1.1.0\n", proc.stdout


def caret_and_tilde_ranges_in_check() -> None:
    pins = {"gateway": "2.0.1", "exporter": "0.3.4", "ledger": "1.9.3", "notifier": "0.0.5"}
    policy = {"gateway": "^1.4", "exporter": "~0.3.1", "ledger": "^1.4.2", "notifier": "^0.0.5"}
    with project(pins, {}, policy) as paths:
        expect(
            pinwatch(["check", *options(paths, "pins", "policy")]),
            "gateway: 2.0.1 is outside the policy ^1.4\n",
            status=1,
        )
    pins = {"gateway": "1.9.3", "exporter": "0.4.0", "ledger": "1.4.2"}
    policy = {"gateway": "^1.4", "exporter": "~0.3.1", "ledger": "~1.4"}
    with project(pins, {}, policy) as paths:
        expect(
            pinwatch(["check", *options(paths, "pins", "policy")]),
            "exporter: 0.4.0 is outside the policy ~0.3.1\n",
            status=1,
        )


def comma_separated_comparators_in_status() -> None:
    pins = {"gateway": "3.1.2", "ledger": "3.1.1", "exporter": "0.3.4"}
    releases = {"gateway": ["3.1.2"], "ledger": ["3.1.1"], "exporter": ["0.3.4"]}
    policy = {"gateway": ">=3.0.0,<3.1.2", "ledger": ">=3.0.0,<3.1.2", "exporter": ">0.3.0,!=0.3.4"}
    with project(pins, releases, policy) as paths:
        expect(
            pinwatch(["status", *options(paths, "pins", "releases", "policy")]),
            "gateway     3.1.2         3.1.2         outside policy\n"
            "ledger      3.1.1         3.1.1         current\n"
            "exporter    0.3.4         0.3.4         outside policy\n",
        )


def a_malformed_range_is_still_an_error() -> None:
    for requirement in (">=1.0,,<2", "^", "latest"):
        with project({"gateway": "1.4.2"}, {}, {"gateway": requirement}) as paths:
            proc = pinwatch(["check", *options(paths, "pins", "policy")])
            assert proc.returncode == 2, (requirement, proc.returncode, proc.stderr[-300:])
            assert proc.stdout == "", proc.stdout
            expected = f": gateway: invalid policy {requirement!r}\n"
            assert proc.stderr.startswith("pinwatch: error: "), proc.stderr
            assert proc.stderr.endswith(expected), proc.stderr
    # A valid range next to the broken one does not hide the error.
    policy = {"ledger": "^1.0", "gateway": "~"}
    with project({"gateway": "1.4.2"}, {}, policy) as paths:
        assert pinwatch(["check", *options(paths, "pins", "policy")]).returncode == 2


def latest_pre_orders_prerelease_numbers() -> None:
    feed = {"gateway": ["2.0.0-rc.2", "1.5.0", "2.0.0-rc.10", "2.0.0-rc.9", "2.0.0-rc.1"]}
    with project(None, feed, None) as paths:
        expect(
            pinwatch(["latest", "gateway", "--pre", *options(paths, "releases")]), "2.0.0-rc.10\n"
        )
        expect(pinwatch(["latest", "gateway", *options(paths, "releases")]), "1.5.0\n")
    feed = {"ledger": ["3.0.0-beta.2", "3.0.0-beta.11", "3.0.0-alpha.20"]}
    with project(None, feed, None) as paths:
        expect(
            pinwatch(["latest", "ledger", "--pre", *options(paths, "releases")]), "3.0.0-beta.11\n"
        )


def status_follows_the_newest_prerelease() -> None:
    releases = {
        "ledger": ["2.0.0", "2.1.0-rc.1", "2.1.0-rc.2", "2.1.0-rc.10"],
        "gateway": ["1.0.0", "2.0.0-rc.2", "2.0.0-rc.9", "2.0.0-rc.10"],
    }
    pins = {"ledger": "2.1.0-rc.2", "gateway": "2.0.0-rc.10"}
    with project(pins, releases, {}) as paths:
        expect(
            pinwatch(["status", *options(paths, "pins", "releases", "policy")]),
            "ledger      2.1.0-rc.2    2.1.0-rc.10   behind\n"
            "gateway     2.0.0-rc.10   2.0.0-rc.10   current\n",
        )


def audit_lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """The advisory lines of an audit run (those that start with an advisory id)."""
    return [line for line in proc.stdout.splitlines() if line.startswith("PW-")]


def audit_lists_the_pins_the_advisories_apply_to() -> None:
    pins = {
        "gateway": "1.4.2",
        "scheduler": "v0.9.1",
        "ledger": "2.1.0-rc.2",
        "notifier": "1.12.0",
        "exporter": "0.3.4",
        "auth-proxy": "3.0.1",
    }
    with project(pins, {}, {}) as paths:
        proc = pinwatch(["audit", *options(paths, "pins"), "--advisories", str(ADVISORIES)])
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr[-300:])
    assert audit_lines(proc) == [
        "PW-2026-0007 gateway 1.4.2 header parsing overflow",
        "PW-2026-0014 ledger 2.1.0-rc.2 rounding drift in batched postings",
        "PW-2026-0019 auth-proxy 3.0.1 session token not rotated after logout",
    ], proc.stdout
    assert proc.stdout.count("\n") == 3, proc.stdout
    # Without --advisories the command reads data/advisories.json.
    with project(pins, {}, {}) as paths:
        by_default = pinwatch(["audit", *options(paths, "pins")])
    assert (by_default.returncode, by_default.stdout) == (1, proc.stdout), by_default.stdout
    # --advisories reads the file it is given, whatever the repository's own file holds.
    other = {
        "advisories": [
            {"id": "PW-2030-0001", "component": "mailer", "affected": "<2.0.0", "summary": "x y"},
            {"id": "PW-2030-0002", "component": "gateway", "affected": "~1.4.2", "summary": "z"},
            {"id": "PW-2030-0003", "component": "gateway", "affected": ">=3.0.0", "summary": "w"},
        ]
    }
    with project({"gateway": "1.4.5", "mailer": "1.9.0"}, {}, {}) as paths:
        feed = Path(paths["pins"]).with_name("other-advisories.json")
        feed.write_text(json.dumps(other), encoding="utf-8")
        custom = pinwatch(["audit", *options(paths, "pins"), "--advisories", str(feed)])
    assert custom.returncode == 1, (custom.returncode, custom.stdout, custom.stderr[-300:])
    assert custom.stdout == ("PW-2030-0001 mailer 1.9.0 x y\nPW-2030-0002 gateway 1.4.5 z\n"), (
        custom.stdout
    )


def audit_is_quiet_when_no_pin_is_affected() -> None:
    pins = {
        "gateway": "1.4.3",
        "scheduler": "0.9.2",
        "ledger": "2.1.0-rc.10",
        "exporter": "0.3.4",
        "auth-proxy": "3.1.0",
    }
    with project(pins, {}, {}) as paths:
        proc = pinwatch(["audit", *options(paths, "pins"), "--advisories", str(ADVISORIES)])
    expect(proc, "no pinned component is affected by an advisory\n")


def status_output_unchanged() -> None:
    with project(OLD_PINS, OLD_RELEASES, OLD_POLICY) as paths:
        expect(
            pinwatch(["status", *options(paths, "pins", "releases", "policy")]),
            "gateway     1.4.2         1.5.0         behind\n"
            "scheduler   0.9.1         0.9.2         behind\n"
            "notifier    1.12.0        1.12.0        current\n"
            "exporter    0.3.4         0.4.0         behind\n",
        )
    pins = {"gateway": "1.3.0", "scheduler": "v1.0.0", "mailer": "0.1.0", "ledger": "v2.0.0"}
    releases = {**OLD_RELEASES, "ledger": ["2.0.0", "2.0.1"]}
    with project(pins, releases, OLD_POLICY) as paths:
        expect(
            pinwatch(["status", *options(paths, "pins", "releases", "policy")]),
            "gateway     1.3.0         1.5.0         outside policy\n"
            "scheduler   1.0.0         0.9.2         outside policy\n"
            "mailer      0.1.0         -             unknown\n"
            "ledger      2.0.0         2.0.1         behind\n",
        )


def check_output_and_exit_status_unchanged() -> None:
    with project(OLD_PINS, OLD_RELEASES, OLD_POLICY) as paths:
        expect(
            pinwatch(["check", *options(paths, "pins", "policy")]),
            "all pins are within the policy\n",
        )
    pins = {"gateway": "1.3.0", "scheduler": "v1.0.0", "notifier": "1.10.9", "exporter": "0.3.5"}
    with project(pins, OLD_RELEASES, OLD_POLICY) as paths:
        expect(
            pinwatch(["check", *options(paths, "pins", "policy")]),
            "gateway: 1.3.0 is outside the policy >=1.4.0\n"
            "scheduler: 1.0.0 is outside the policy <v1.0.0\n"
            "notifier: 1.10.9 is outside the policy >= 1.11.0\n"
            "exporter: 0.3.5 is outside the policy !=0.3.5\n",
            status=1,
        )
    pins = {"gateway": "2.0.0-rc.1", "scheduler": "v0.9.1"}
    with project(pins, OLD_RELEASES, {"gateway": ">=2.0.0", "scheduler": "==0.9.1"}) as paths:
        expect(
            pinwatch(["check", *options(paths, "pins", "policy")]),
            "gateway: 2.0.0-rc.1 is outside the policy >=2.0.0\n",
            status=1,
        )


def latest_output_unchanged() -> None:
    with project(None, OLD_RELEASES, None) as paths:
        feed = options(paths, "releases")
        expect(pinwatch(["latest", "gateway", *feed]), "1.5.0\n")
        expect(pinwatch(["latest", "gateway", "--pre", *feed]), "2.0.0-rc.1\n")
        expect(pinwatch(["latest", "scheduler", *feed]), "0.9.2\n")
        expect(pinwatch(["latest", "exporter", "--pre", *feed]), "0.4.0\n")
        proc = pinwatch(["latest", "mailer", *feed])
        assert (proc.returncode, proc.stdout) == (2, ""), (proc.returncode, proc.stdout)
        assert proc.stderr.startswith("pinwatch: error: no releases of 'mailer' in "), proc.stderr


def errors_unchanged() -> None:
    with project(OLD_PINS, OLD_RELEASES, OLD_POLICY) as paths:
        missing = str(Path(paths["pins"]).with_name("nothing.json"))
        proc = pinwatch(["check", "--pins", missing, "--policy", paths["policy"]])
        assert (proc.returncode, proc.stdout) == (2, ""), (proc.returncode, proc.stdout)
        assert proc.stderr == f"pinwatch: error: cannot read {missing}: No such file or directory\n"
        broken = Path(paths["policy"]).with_name("broken.json")
        broken.write_text("{oops", encoding="utf-8")
        proc = pinwatch(["check", "--pins", paths["pins"], "--policy", str(broken)])
        assert proc.returncode == 2, proc.returncode
        assert proc.stderr.startswith(f"pinwatch: error: {broken} is not valid JSON ("), proc.stderr
    with project({"gateway": "banana"}, OLD_RELEASES, OLD_POLICY) as paths:
        proc = pinwatch(["status", *options(paths, "pins", "releases", "policy")])
        assert (proc.returncode, proc.stdout) == (2, ""), (proc.returncode, proc.stdout)
        assert (
            proc.stderr == f"pinwatch: error: {paths['pins']}: gateway: invalid version 'banana'\n"
        )
    with project({"gateway": "1.4.2"}, {"gateway": ["1.4.0", "next"]}, OLD_POLICY) as paths:
        proc = pinwatch(["latest", "gateway", *options(paths, "releases")])
        assert proc.returncode == 2, proc.returncode
        assert (
            proc.stderr
            == f"pinwatch: error: {paths['releases']}: gateway: invalid version 'next'\n"
        )
    with project({"gateway": "1.4.2"}, OLD_RELEASES, {"gateway": "~~1"}) as paths:
        proc = pinwatch(["check", *options(paths, "pins", "policy")])
        assert (proc.returncode, proc.stdout) == (2, ""), (proc.returncode, proc.stdout)
        assert proc.stderr == f"pinwatch: error: {paths['policy']}: gateway: invalid policy '~~1'\n"
