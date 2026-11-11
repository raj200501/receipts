"""Tests for make doctor, using fake ``which`` and command runners (no real probes)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from receipts import budget, doctor, guard
from receipts.doctor import CommandResult

ROOT = Path(__file__).resolve().parents[1]

OK = CommandResult(0, "", "")


def fake_which(installed: Mapping[str, str]) -> Callable[[str], str | None]:
    return lambda name: installed.get(name)


def fake_runner(table: Mapping[str, CommandResult]) -> doctor.Runner:
    """Map the first two argv words (binary basename plus first arg) to a result."""

    def run(argv: Sequence[str], timeout: float) -> CommandResult:
        del timeout
        key = " ".join([Path(argv[0]).name, *argv[1:2]])
        return table.get(key, table.get(Path(argv[0]).name, CommandResult(1, "", "fail")))

    return run


def meminfo(tmp_path: Path, gb: float) -> Path:
    path = tmp_path / "meminfo"
    path.write_text(f"MemTotal:       {int(gb * 1024 * 1024)} kB\nMemFree: 1 kB\n")
    return path


def test_run_command_handles_missing_binary_and_timeout() -> None:
    assert doctor.run_command(["definitely-not-a-binary-xyz"], 5).returncode == 127
    assert doctor.run_command(["sleep", "5"], 0.2).returncode == 124
    assert doctor.run_command(["true"], 5).returncode == 0


def test_first_line() -> None:
    assert doctor.first_line("\n\n  hello \nworld") == "hello"
    assert doctor.first_line("") == ""


def test_ram_and_param_fit(tmp_path: Path) -> None:
    assert doctor.read_ram_gb(meminfo(tmp_path, 16)) == pytest.approx(16)
    assert doctor.read_ram_gb(tmp_path / "absent") is None
    (tmp_path / "odd").write_text("Nothing: here\n")
    assert doctor.read_ram_gb(tmp_path / "odd") is None
    assert doctor.max_params_for_ram(None) is None
    assert doctor.max_params_for_ram(16) == 17
    assert doctor.max_params_for_ram(8) == 4
    assert doctor.max_params_for_ram(2) == 0


def test_probe_docker_states() -> None:
    assert not doctor.probe_docker(fake_which({}), fake_runner({})).ok
    which = fake_which({"docker": "/usr/bin/docker"})
    down = doctor.probe_docker(which, fake_runner({}))
    assert not down.ok and "daemon" in down.detail
    up = doctor.probe_docker(which, fake_runner({"docker info": CommandResult(0, "27.0\n", "")}))
    assert up.ok and "27.0" in up.detail


def test_probe_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    which = fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"})
    gpu = doctor.probe_gpu(which, fake_runner({"nvidia-smi -L": CommandResult(0, "GPU 0: X", "")}))
    assert gpu.ok
    monkeypatch.setattr("receipts.doctor.platform.system", lambda: "Darwin")
    monkeypatch.setattr("receipts.doctor.platform.machine", lambda: "arm64")
    assert doctor.probe_gpu(fake_which({}), fake_runner({})).detail.startswith("Apple")
    monkeypatch.setattr("receipts.doctor.platform.system", lambda: "Linux")
    assert not doctor.probe_gpu(fake_which({}), fake_runner({})).ok


def test_probe_claude_never_checks_login_when_guard_trips() -> None:
    calls: list[Sequence[str]] = []

    def run(argv: Sequence[str], timeout: float) -> CommandResult:
        calls.append(argv)
        return CommandResult(0, "2.1.0 (Claude Code)\n", "")

    which = fake_which({"claude": "/bin/claude"})
    problem = guard.GuardProblem("env", "ANTHROPIC_BASE_URL")
    probe = doctor.probe_claude(which, run, [problem])
    assert not probe.ok and "ANTHROPIC_BASE_URL" in probe.detail
    assert all("auth" not in argv for argv in calls)


@pytest.mark.parametrize(
    ("status", "ok", "word"),
    [
        (CommandResult(0, '{"authMethod": "claude.ai"}', ""), True, "claude.ai plan"),
        (CommandResult(0, '{"authMethod": "api_key"}', ""), False, "authMethod api_key"),
        (CommandResult(1, '{"authMethod": "none"}', ""), False, "not logged in"),
        (CommandResult(0, "not json", ""), False, "authMethod unknown"),
        (CommandResult(0, "[1]", ""), False, "authMethod unknown"),
    ],
)
def test_probe_claude_login_methods(status: CommandResult, ok: bool, word: str) -> None:
    run = fake_runner({"claude --version": CommandResult(0, "2.1.0", ""), "claude auth": status})
    probe = doctor.probe_claude(fake_which({"claude": "/bin/claude"}), run, [])
    assert probe.ok is ok
    assert word in probe.detail
    assert not doctor.probe_claude(fake_which({}), run, []).ok


def test_probe_ollama_and_llamacpp() -> None:
    which = fake_which({"ollama": "/bin/ollama"})
    listing = CommandResult(0, "NAME ID SIZE\nqwen2.5:7b abc 4GB\n", "")
    assert doctor.probe_ollama(which, fake_runner({"ollama list": listing})).detail == "qwen2.5:7b"
    empty = CommandResult(0, "NAME ID SIZE\n", "")
    assert not doctor.probe_ollama(which, fake_runner({"ollama list": empty})).ok
    assert not doctor.probe_ollama(which, fake_runner({})).ok
    assert not doctor.probe_ollama(fake_which({}), fake_runner({})).ok
    assert doctor.probe_llamacpp(fake_which({"llama-cli": "/bin/llama-cli"})).ok
    assert not doctor.probe_llamacpp(fake_which({})).ok


def test_probe_sandboxes() -> None:
    which = fake_which({"bwrap": "/bin/bwrap", "unshare": "/bin/unshare"})
    run = fake_runner({"bwrap --unshare-all": OK, "unshare -rn": OK})
    names = {p.name: p.ok for p in doctor.probe_sandboxes(which, run, docker_ok=False)}
    assert names == {
        "sandbox:docker": False,
        "sandbox:bwrap": True,
        "sandbox:unshare-net": True,
        "sandbox:sandbox-exec": False,
    }
    failing = {p.name: p.ok for p in doctor.probe_sandboxes(which, fake_runner({}), True)}
    assert failing["sandbox:docker"] and not failing["sandbox:bwrap"]
    assert not failing["sandbox:unshare-net"]
    none = {p.name: p.ok for p in doctor.probe_sandboxes(fake_which({}), fake_runner({}), False)}
    assert not any(none.values())


def test_probe_free_tiers_requires_confirmation() -> None:
    key = {"GEMINI_API_KEY": "secret-value"}
    ignored = doctor.probe_free_tiers(key)
    assert not ignored.ok and "ignored" in ignored.detail and "secret-value" not in ignored.detail
    assert not doctor.probe_free_tiers({"FREE_TIER_KEYS_CONFIRMED": "1"}).ok
    confirmed = doctor.probe_free_tiers({**key, "FREE_TIER_KEYS_CONFIRMED": "1"})
    assert confirmed.ok and confirmed.detail == "confirmed: GEMINI_API_KEY"


def test_probe_binary() -> None:
    which = fake_which({"uv": "/bin/uv"})
    probe = doctor.probe_binary(
        "uv", which, fake_runner({"uv --version": CommandResult(0, "uv 1", "")}), ["--version"]
    )
    assert probe.ok and "uv 1" in probe.detail
    assert not doctor.probe_binary("node", which, fake_runner({}), ["--version"]).ok


def diagnose(
    tmp_path: Path,
    env: Mapping[str, str],
    installed: Mapping[str, str],
    table: Mapping[str, CommandResult],
    gb: float = 16,
) -> doctor.DoctorReport:
    return doctor.diagnose(
        env=env,
        which=fake_which(installed),
        run=fake_runner(table),
        repo=tmp_path,
        home=tmp_path,
        meminfo=meminfo(tmp_path, gb),
        caps=budget.load_caps(ROOT / "budget.toml"),
        llm_python=tmp_path / "no-llm-python",
        models_dir=tmp_path / "no-models",
    )


def test_diagnose_cloud_like_environment(tmp_path: Path) -> None:
    report = diagnose(
        tmp_path,
        env={"ANTHROPIC_BASE_URL": "x", "CLAUDE_CODE_USE_CCR_V2": "1"},
        installed={"claude": "/bin/claude", "docker": "/bin/docker", "unshare": "/bin/unshare"},
        table={"unshare -rn": OK, "claude --version": CommandResult(0, "2.1", "")},
    )
    assert report.backends == {"claude": False, "local": False, "free_tier": False}
    assert report.local_model_max_params_b == 8
    assert any("billing guard" in f for f in report.fallbacks)
    assert any("unshare" in f for f in report.fallbacks)
    assert any("CLAUDE_CODE_USE_CCR_V2" in n for n in report.needs_raj)
    assert report.probe("sandbox:unshare-net").ok
    with pytest.raises(KeyError):
        report.probe("nope")
    text = doctor.render_markdown(report)
    assert "Usable backends: claude=no" in text


def test_diagnose_good_machine(tmp_path: Path) -> None:
    report = diagnose(
        tmp_path,
        env={},
        installed={"claude": "/bin/claude", "docker": "/bin/docker", "ollama": "/bin/ollama"},
        table={
            "docker info": CommandResult(0, "27\n", ""),
            "claude --version": CommandResult(0, "2.1", ""),
            "claude auth": CommandResult(0, '{"authMethod": "claude.ai"}', ""),
            "ollama list": CommandResult(0, "NAME\nllama3.1:8b x\n", ""),
        },
        gb=6,
    )
    assert report.backends == {"claude": True, "local": True, "free_tier": False}
    assert report.local_model_max_params_b == 0
    assert report.needs_raj == []


def test_diagnose_no_sandbox_and_logged_out(tmp_path: Path) -> None:
    report = diagnose(tmp_path, env={}, installed={"claude": "/bin/claude"}, table={})
    assert any("No working sandbox" in n for n in report.needs_raj)
    assert any("claude auth login" in n for n in report.needs_raj)


def test_diagnose_without_caps_or_ram(tmp_path: Path) -> None:
    report = doctor.diagnose(
        env={},
        which=fake_which({}),
        run=fake_runner({}),
        repo=tmp_path,
        home=tmp_path,
        meminfo=tmp_path / "absent",
        llm_python=tmp_path / "no-llm-python",
        models_dir=tmp_path / "no-models",
    )
    assert report.ram_gb is None and report.local_model_max_params_b is None
    assert "RAM unknown" in doctor.render_markdown(report)
    report = doctor.diagnose(
        env={},
        which=fake_which({}),
        run=fake_runner({}),
        repo=tmp_path,
        home=tmp_path,
        meminfo=meminfo(tmp_path, 16),
        llm_python=tmp_path / "no-llm-python",
        models_dir=tmp_path / "no-models",
    )
    assert report.local_model_max_params_b == 17


def test_main_json_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "budget.toml"
    target.write_text((ROOT / "budget.toml").read_text())
    monkeypatch.setattr(doctor, "max_params_for_ram", lambda ram: 3.0)
    monkeypatch.setattr("receipts.doctor.shutil.which", lambda name: None)
    monkeypatch.setattr(
        doctor,
        "probe_llama_cpp_python",
        lambda run, python: doctor.Probe("llama-cpp-python", False, "patched"),
    )
    assert doctor.main(["--apply", "--json", "--budget", str(target)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["local_model_max_params_b"] == 3.0
    assert budget.load_caps(target).local_model_max_params_b == 3
    assert any("lowered" in f for f in data["fallbacks"])
    assert doctor.main(["--budget", str(tmp_path / "missing.toml")]) == 0
    assert "Usable backends" in capsys.readouterr().out


def test_probe_llama_cpp_python_and_models(tmp_path: Path) -> None:
    python = tmp_path / "python"
    assert not doctor.probe_llama_cpp_python(fake_runner({}), python).ok
    python.write_text("")
    assert not doctor.probe_llama_cpp_python(fake_runner({}), python).ok
    ok = doctor.probe_llama_cpp_python(
        fake_runner({"python -c": CommandResult(0, "0.3.36\n", "")}), python
    )
    assert ok.ok and "0.3.36" in ok.detail
    assert not doctor.probe_models(tmp_path / "none").ok
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "a.gguf").write_text("")
    assert doctor.probe_models(tmp_path / "m").detail == "a.gguf"


def test_local_backend_from_llama_cpp_python(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("")
    models = tmp_path / "models"
    models.mkdir()
    (models / "x.gguf").write_text("")
    report = doctor.diagnose(
        env={},
        which=fake_which({}),
        run=fake_runner({"python -c": CommandResult(0, "0.3.36", "")}),
        repo=tmp_path,
        home=tmp_path,
        meminfo=meminfo(tmp_path, 16),
        llm_python=python,
        models_dir=models,
    )
    assert report.backends["local"] is True
