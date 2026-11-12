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
from receipts.sandbox.docker import DEFAULT_IMAGE
from receipts.sandbox.local import LocalTestSandbox
from receipts.sandbox.select import (
    CONFINES_WRITES,
    DEFAULT_CHECK_CMD,
    DEFAULT_PREFERENCE,
    available_backends,
    exposed,
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
    assert DEFAULT_CHECK_CMD == "command -v git"
    assert CONFINES_WRITES == {"docker": True, "bwrap": True, "unshare": False}


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
        make_sandbox(workspace, allow_unconfined=True)
    message = str(caught.value)
    for name in DEFAULT_PREFERENCE:
        assert f"{name}: synthetic {name} failure" in message


def test_unconfined_backends_need_explicit_permission(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    asked = fake_probes(monkeypatch, {"unshare"})
    built = fake_factories(monkeypatch)
    with pytest.raises(SandboxUnavailableError) as caught:
        make_sandbox(workspace)
    message = str(caught.value)
    assert "unshare: skipped because it does not confine writes" in message
    assert "allow_unconfined=True" in message
    assert asked == ["docker", "bwrap"] and built == []
    make_sandbox(workspace, prefer=("unshare",), allow_unconfined=True)
    assert built == [("unshare", DEFAULT_IMAGE, None)]


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
    chosen = make_sandbox(workspace, check_cmd=check, allow_unconfined=True)
    assert chosen.env["FAKE_BACKEND"] == "unshare"
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


def test_the_default_check_skips_a_backend_without_git(
    monkeypatch: pytest.MonkeyPatch, workspace: Path, tmp_path: Path
) -> None:
    fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    no_git = tmp_path / "no-git-bin"
    no_git.mkdir()

    def factory_for(name: str) -> select.Factory:
        """A LocalTestSandbox factory whose PATH has git, except for the fake docker."""

        def factory(
            ws: str | Path,
            policy: SandboxPolicy | None,
            image: str,
            hide: Iterable[str | Path] | None,
        ) -> ProcessSandbox:
            path = str(no_git) if name == "docker" else "/usr/bin:/bin"
            tagged = SandboxPolicy(env={"FAKE_BACKEND": name, "PATH": path})
            return LocalTestSandbox(ws, tagged, allow_unsandboxed_for_tests=True)

        return factory

    for name in DEFAULT_PREFERENCE:
        monkeypatch.setitem(select.FACTORIES, name, factory_for(name))
    assert make_sandbox(workspace).env["FAKE_BACKEND"] == "bwrap"
    assert make_sandbox(workspace, check_cmd=None).env["FAKE_BACKEND"] == "docker"
    with pytest.raises(SandboxUnavailableError, match=r"docker: check command failed \(exit 1"):
        make_sandbox(workspace, prefer=("docker",))


def test_caller_errors_raise_before_any_backend_is_tried(
    monkeypatch: pytest.MonkeyPatch, workspace: Path, tmp_path: Path
) -> None:
    asked = fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    fake_factories(monkeypatch)
    bad = [
        (tmp_path / "missing", None),
        (workspace, SandboxPolicy(timeout_s=0)),
        (workspace, SandboxPolicy(env={"GH_TOKEN": "synthetic"})),
        (workspace, SandboxPolicy(readonly_paths=(tmp_path / "missing",))),
    ]
    for ws, policy in bad:
        with pytest.raises(ValueError):
            make_sandbox(ws, policy)
    assert asked == []


def test_a_backend_that_refuses_the_workspace_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    odd = tmp_path / "task,1"
    odd.mkdir()
    fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    fake_factories(monkeypatch)

    def refusing(
        ws: str | Path,
        policy: SandboxPolicy | None,
        image: str,
        hide: Iterable[str | Path] | None,
    ) -> ProcessSandbox:
        raise ValueError(f"synthetic: path cannot be bind-mounted by docker --mount: {ws}")

    monkeypatch.setitem(select.FACTORIES, "docker", refusing)
    box = make_sandbox(odd, check_cmd=None)
    assert box.workspace == odd.resolve()
    with pytest.raises(SandboxUnavailableError, match="docker: synthetic: path cannot"):
        make_sandbox(odd, prefer=("docker",))


def test_a_check_that_breaks_the_sandbox_is_a_reason(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    fake_probes(monkeypatch, set(DEFAULT_PREFERENCE))
    fake_factories(monkeypatch)

    def broken_run(self: ProcessSandbox, cmd: str, **kwargs: object) -> object:
        raise SandboxUnavailableError("fake: the sandbox did not start the command (synthetic)")

    monkeypatch.setattr(LocalTestSandbox, "run", broken_run)
    with pytest.raises(SandboxUnavailableError, match="docker: fake: the sandbox did not start"):
        make_sandbox(workspace, prefer=("docker",))


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
        make_sandbox(workspace, prefer=("docker",))
    assert isinstance(make_sandbox(workspace), BwrapSandbox)


@requires(bwrap_probe())
def test_a_real_docker_constructor_refusal_falls_back_to_bwrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    odd = tmp_path / "task,1"
    odd.mkdir()
    monkeypatch.setitem(
        select.PROBES, "docker", lambda image: BackendProbe("docker", True, "synthetic ok")
    )
    box = make_sandbox(odd, prefer=("docker", "bwrap"))
    assert isinstance(box, BwrapSandbox) and box.run("echo ok").stdout == "ok\n"


class SyntheticHiding:
    """A SYNTHETIC sandbox that hides exactly the paths it is given (test data only)."""

    backend = "synthetic"

    def __init__(self, hidden: Iterable[Path]) -> None:
        self.hidden = {p.resolve() for p in hidden}

    def hides(self, path: str | Path) -> bool:
        target = Path(path).resolve()
        return any(h == target or h in target.parents for h in self.hidden)

    def shown_within(self, path: str | Path) -> tuple[Path, ...]:
        return ()


def test_exposed_lists_the_paths_a_sandbox_does_not_hide(tmp_path: Path) -> None:
    hidden, shown = tmp_path / "hidden", tmp_path / "shown"
    for directory in (hidden, shown):
        directory.mkdir()
    box = SyntheticHiding([hidden])
    assert exposed(box, [hidden / "x", shown, str(hidden)]) == [shown]
    # A sandbox that cannot say what it hides (unshare, the test sandboxes) shows all.
    local = LocalTestSandbox(tmp_path, allow_unsandboxed_for_tests=True)
    assert exposed(local, [hidden, shown]) == [hidden.resolve(), shown.resolve()]
