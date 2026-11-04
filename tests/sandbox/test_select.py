"""Tests for choosing a sandbox backend."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

import pytest

from receipts.sandbox import select
from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import BackendProbe, ProcessSandbox
from receipts.sandbox.bwrap import BwrapSandbox
from receipts.sandbox.local import LocalTestSandbox
from receipts.sandbox.select import (
    DEFAULT_PREFERENCE,
    available_backends,
    make_sandbox,
    probe_backends,
)

from .helpers import bwrap_probe, docker_probe, requires


def fake_probes(monkeypatch: pytest.MonkeyPatch, working: set[str]) -> list[str]:
    """Replace every probe with a synthetic answer; return the order they were asked."""
    asked: list[str] = []
    for name in DEFAULT_PREFERENCE:

        def probe(image: str, name: str = name) -> BackendProbe:
            asked.append(name)
            ok = name in working
            return BackendProbe(name, ok, "synthetic ok" if ok else f"synthetic {name} failure")

        monkeypatch.setitem(select.PROBES, name, probe)
    return asked


def fake_factories(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, object]]:
    """Replace every constructor with a LocalTestSandbox; record what each received."""
    built: list[tuple[str, str, object]] = []
    for name in DEFAULT_PREFERENCE:

        def factory(
            ws: str | Path,
            policy: SandboxPolicy | None,
            image: str,
            hide: Iterable[str | Path] | None,
            name: str = name,
        ) -> ProcessSandbox:
            built.append((name, image, hide))
            return LocalTestSandbox(ws, policy, allow_unsandboxed_for_tests=True)

        monkeypatch.setitem(select.FACTORIES, name, factory)
    return built


def test_default_preference_follows_the_brief() -> None:
    assert DEFAULT_PREFERENCE == ("docker", "bwrap", "unshare")


def test_available_backends_keeps_preference_order(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_probes(monkeypatch, {"unshare", "bwrap"})
    assert available_backends() == ("bwrap", "unshare")
    assert available_backends(("unshare", "bwrap")) == ("unshare", "bwrap")
    assert [p.ok for p in probe_backends()] == [False, True, True]


def test_make_sandbox_returns_the_first_backend_that_works(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    asked = fake_probes(monkeypatch, {"bwrap", "unshare"})
    built = fake_factories(monkeypatch)
    policy = SandboxPolicy(timeout_s=9.0)
    box = make_sandbox(workspace, policy, image="local/img:1", hide_paths=["/x"])
    assert asked == ["docker", "bwrap"]
    assert built == [("bwrap", "local/img:1", ["/x"])]
    assert box.policy is policy


def test_make_sandbox_passes_the_image_to_docker(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    built = fake_factories(monkeypatch)
    make_sandbox(workspace, image="local/img:2")
    assert built == [("docker", "local/img:2", None)]


def test_make_sandbox_explains_why_nothing_works(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    fake_probes(monkeypatch, set())
    with pytest.raises(SandboxUnavailableError) as caught:
        make_sandbox(workspace)
    message = str(caught.value)
    for name in DEFAULT_PREFERENCE:
        assert f"{name}: synthetic {name} failure" in message


def test_make_sandbox_honours_a_narrower_preference(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    fake_probes(monkeypatch, {"unshare"})
    fake_factories(monkeypatch)
    with pytest.raises(SandboxUnavailableError) as caught:
        make_sandbox(workspace, prefer=("docker", "bwrap"))
    assert "docker: " in str(caught.value) and "bwrap: " in str(caught.value)
    assert "unshare" not in str(caught.value)


def tagged_factories(monkeypatch: pytest.MonkeyPatch, broken: tuple[str, ...] = ()) -> None:
    """Constructors whose sandboxes carry their backend name in ``FAKE_BACKEND``."""
    for name in DEFAULT_PREFERENCE:

        def factory(
            ws: str | Path,
            policy: SandboxPolicy | None,
            image: str,
            hide: Iterable[str | Path] | None,
            name: str = name,
        ) -> ProcessSandbox:
            if name in broken:
                raise SandboxUnavailableError(f"synthetic: {name} vanished after its probe")
            tagged = replace(policy or SandboxPolicy(), env={"FAKE_BACKEND": name})
            return LocalTestSandbox(ws, tagged, allow_unsandboxed_for_tests=True)

        monkeypatch.setitem(select.FACTORIES, name, factory)


def test_make_sandbox_skips_backends_that_fail_the_check_command(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    tagged_factories(monkeypatch)
    check = 'test "$FAKE_BACKEND" = unshare || { echo "no tool in $FAKE_BACKEND" >&2; exit 3; }'
    assert make_sandbox(workspace, check_cmd=check).env["FAKE_BACKEND"] == "unshare"
    assert make_sandbox(workspace, check_cmd="true").env["FAKE_BACKEND"] == "docker"
    with pytest.raises(SandboxUnavailableError) as caught:
        make_sandbox(workspace, prefer=("docker", "bwrap"), check_cmd=check)
    message = str(caught.value)
    assert "docker: check command failed (exit 3: no tool in docker)" in message
    assert "bwrap: check command failed (exit 3: no tool in bwrap)" in message
    with pytest.raises(SandboxUnavailableError, match=r"exit 124 \(timed out\)"):
        make_sandbox(
            workspace, SandboxPolicy(timeout_s=0.2), prefer=("docker",), check_cmd="sleep 5"
        )


def test_make_sandbox_moves_on_when_a_backend_vanishes_after_its_probe(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    tagged_factories(monkeypatch, broken=("docker",))
    assert make_sandbox(workspace).env["FAKE_BACKEND"] == "bwrap"
    with pytest.raises(SandboxUnavailableError, match="docker: synthetic: docker vanished"):
        make_sandbox(workspace, prefer=("docker",))


@pytest.mark.parametrize("prefer", [(), ("docker", "podman"), ("fake",)])
def test_unknown_or_empty_preferences_are_refused(prefer: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        available_backends(prefer)


@requires(bwrap_probe())
def test_make_sandbox_builds_a_real_bwrap_sandbox(workspace: Path) -> None:
    box = make_sandbox(workspace, prefer=("bwrap",))
    assert isinstance(box, BwrapSandbox)
    assert box.run("echo ok").stdout == "ok\n"
    assert "bwrap" in available_backends(("bwrap",))


@pytest.mark.slow
@requires(docker_probe())
@requires(bwrap_probe())
def test_a_docker_image_without_git_falls_back_to_bwrap(workspace: Path) -> None:
    with pytest.raises(SandboxUnavailableError, match=r"docker: check command failed \(exit 1"):
        make_sandbox(workspace, prefer=("docker",), check_cmd="command -v git")
    box = make_sandbox(workspace, prefer=("docker", "bwrap"), check_cmd="command -v git")
    assert isinstance(box, BwrapSandbox)
