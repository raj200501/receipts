"""``make doctor``: detect what this machine can run (docs/BUILD_BRIEF.md section 8).

Detects Docker, GPU, RAM, free disk, the ``claude`` CLI and its login, Ollama,
llama.cpp, sandbox options, and confirmed free-tier keys, then derives which
model backends are usable and which fallbacks apply. It never calls a model and
never prints a secret value: keys are reported by name only.

The Claude backend is marked unusable while the billing guard
(:mod:`receipts.guard`) reports anything. In that case ``claude auth status`` is
not run at all, because the answer could not change the verdict.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from receipts import budget, guard

FREE_TIER_KEYS: tuple[str, ...] = ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "GITHUB_MODELS_TOKEN")

# Rough RAM model for a 4-bit quantized model: weights plus runtime overhead,
# leaving headroom for the OS, the sandbox, and the agent under test.
GB_PER_BILLION_PARAMS_Q4 = 0.6
RUNTIME_OVERHEAD_GB = 1.5
SYSTEM_HEADROOM_GB = 4.0


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one probe command."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]
Which = Callable[[str], str | None]


def run_command(argv: Sequence[str], timeout: float) -> CommandResult:
    """Run ``argv`` without a shell; a missing binary or timeout becomes returncode 127/124."""
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return CommandResult(127, "", "not found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timeout")
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


@dataclass(frozen=True)
class Probe:
    """One detected capability."""

    name: str
    ok: bool
    detail: str


@dataclass
class DoctorReport:
    """Everything ``make doctor`` found, plus the derived backends and fallbacks."""

    platform: str
    probes: list[Probe]
    ram_gb: float | None
    free_disk_gb: float
    backends: dict[str, bool]
    fallbacks: list[str] = field(default_factory=list)
    needs_raj: list[str] = field(default_factory=list)
    local_model_max_params_b: float | None = None

    def probe(self, name: str) -> Probe:
        """Return the probe called ``name``."""
        for item in self.probes:
            if item.name == name:
                return item
        raise KeyError(name)


def first_line(text: str) -> str:
    """Return the first non-empty line of ``text``, stripped, or an empty string."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def probe_binary(name: str, which: Which, run: Runner, version_args: Sequence[str]) -> Probe:
    """Detect a CLI and report its version line."""
    path = which(name)
    if path is None:
        return Probe(name, False, "not installed")
    result = run([path, *version_args], 20)
    version = first_line(result.stdout) or first_line(result.stderr) or "version unknown"
    return Probe(name, result.returncode == 0, f"{path} ({version})")


def probe_docker(which: Which, run: Runner) -> Probe:
    """Docker is usable only if the binary exists and the daemon answers."""
    path = which("docker")
    if path is None:
        return Probe("docker", False, "not installed")
    result = run([path, "info", "--format", "{{.ServerVersion}}"], 20)
    if result.returncode != 0:
        return Probe("docker", False, f"{path} present but the daemon is not reachable")
    return Probe("docker", True, f"daemon {first_line(result.stdout)}")


def probe_gpu(which: Which, run: Runner) -> Probe:
    """Detect an NVIDIA GPU through ``nvidia-smi`` (Apple GPUs report via platform)."""
    path = which("nvidia-smi")
    if path is not None:
        result = run([path, "-L"], 20)
        if result.returncode == 0 and result.stdout.strip():
            return Probe("gpu", True, first_line(result.stdout))
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return Probe("gpu", True, "Apple silicon (Metal)")
    return Probe("gpu", False, "no GPU detected")


def read_ram_gb(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    """Return total RAM in GB from /proc/meminfo, or None when unavailable."""
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return None
    return None


def max_params_for_ram(ram_gb: float | None) -> float | None:
    """Largest 4-bit model (billions of parameters) that fits in ``ram_gb``, or None."""
    if ram_gb is None:
        return None
    usable = ram_gb - SYSTEM_HEADROOM_GB - RUNTIME_OVERHEAD_GB
    return float(max(0, math.floor(usable / GB_PER_BILLION_PARAMS_Q4)))


def probe_claude(which: Which, run: Runner, guard_problems: Sequence[guard.GuardProblem]) -> Probe:
    """Detect the ``claude`` CLI; its login is checked only when the guard is clear."""
    path = which("claude")
    if path is None:
        return Probe("claude", False, "claude CLI not installed")
    version = first_line(run([path, "--version"], 20).stdout) or "version unknown"
    if guard_problems:
        names = ", ".join(problem.name for problem in guard_problems)
        return Probe("claude", False, f"{version}; billing guard tripped by {names}")
    status = run([path, "auth", "status"], 30)
    text = (status.stdout + status.stderr).lower()
    if status.returncode != 0:
        return Probe("claude", False, f"{version}; not logged in")
    if "api key" in text or "console" in text:
        return Probe("claude", False, f"{version}; logged in with an API key, not a plan")
    method = "subscription" if any(w in text for w in ("max", "pro", "subscription")) else "?"
    return Probe("claude", method == "subscription", f"{version}; login method {method}")


def probe_ollama(which: Which, run: Runner) -> Probe:
    """Ollama is usable when its server lists models."""
    path = which("ollama")
    if path is None:
        return Probe("ollama", False, "not installed")
    result = run([path, "list"], 20)
    if result.returncode != 0:
        return Probe("ollama", False, f"{path} present but the server is not running")
    models = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.strip()]
    detail = ", ".join(models) if models else "no models pulled"
    return Probe("ollama", bool(models), detail)


def probe_llamacpp(which: Which) -> Probe:
    """Detect llama.cpp binaries."""
    for name in ("llama-server", "llama-cli"):
        path = which(name)
        if path is not None:
            return Probe("llama.cpp", True, path)
    return Probe("llama.cpp", False, "not installed")


def probe_llama_cpp_python(run: Runner, python: Path) -> Probe:
    """Detect the llama-cpp-python server in its own virtualenv (DECISIONS D23)."""
    if not python.is_file():
        return Probe("llama-cpp-python", False, f"{python} not found")
    code = "import llama_cpp, llama_cpp.server; print(llama_cpp.__version__)"
    result = run([str(python), "-c", code], 60)
    if result.returncode != 0:
        return Probe("llama-cpp-python", False, f"{python} cannot import llama_cpp.server")
    return Probe("llama-cpp-python", True, f"{first_line(result.stdout)} at {python}")


def probe_models(models_dir: Path) -> Probe:
    """List pinned GGUF model files in ``models_dir``."""
    files = sorted(p.name for p in models_dir.glob("*.gguf")) if models_dir.is_dir() else []
    if not files:
        return Probe("gguf-models", False, f"no .gguf files in {models_dir}")
    return Probe("gguf-models", True, ", ".join(files))


def probe_sandboxes(which: Which, run: Runner, docker_ok: bool) -> list[Probe]:
    """Detect each sandbox mechanism the executor can use."""
    probes = [Probe("sandbox:docker", docker_ok, "docker --network none" if docker_ok else "-")]
    bwrap = which("bwrap")
    if bwrap is None:
        probes.append(Probe("sandbox:bwrap", False, "bubblewrap not installed"))
    else:
        ok = run([bwrap, "--unshare-all", "--ro-bind", "/", "/", "true"], 20).returncode == 0
        probes.append(Probe("sandbox:bwrap", ok, bwrap if ok else f"{bwrap} present but fails"))
    unshare = which("unshare")
    if unshare is None:
        probes.append(Probe("sandbox:unshare-net", False, "unshare not installed"))
    else:
        ok = run([unshare, "-rn", "true"], 20).returncode == 0
        detail = "user+network namespaces work" if ok else "namespaces not permitted"
        probes.append(Probe("sandbox:unshare-net", ok, detail))
    sandbox_exec = which("sandbox-exec")
    probes.append(
        Probe("sandbox:sandbox-exec", sandbox_exec is not None, sandbox_exec or "not macOS")
    )
    return probes


def probe_free_tiers(env: Mapping[str, str]) -> Probe:
    """Report confirmed free-tier keys by name; without confirmation they are ignored."""
    present = [name for name in FREE_TIER_KEYS if env.get(name)]
    if env.get("FREE_TIER_KEYS_CONFIRMED") != "1":
        note = f" ({len(present)} key(s) set but ignored)" if present else ""
        return Probe("free-tiers", False, "FREE_TIER_KEYS_CONFIRMED is not 1" + note)
    if not present:
        return Probe("free-tiers", False, "confirmed, but no free-tier keys are set")
    return Probe("free-tiers", True, "confirmed: " + ", ".join(present))


def diagnose(
    env: Mapping[str, str],
    which: Which,
    run: Runner,
    repo: Path,
    home: Path,
    meminfo: Path = Path("/proc/meminfo"),
    caps: budget.Caps | None = None,
    llm_python: Path = Path("/opt/receipts-llm/bin/python"),
    models_dir: Path = Path("/opt/receipts-models"),
) -> DoctorReport:
    """Run every probe and derive usable backends, fallbacks, and Needs Raj items."""
    guard_problems = guard.billing_guard_problems(env=env, home=home, repo=repo)
    docker = probe_docker(which, run)
    probes = [
        Probe("python", True, f"{platform.python_version()} at {sys.executable}"),
        probe_binary("uv", which, run, ["--version"]),
        probe_binary("git", which, run, ["--version"]),
        probe_binary("node", which, run, ["--version"]),
        probe_binary("npm", which, run, ["--version"]),
        docker,
        probe_gpu(which, run),
        probe_claude(which, run, guard_problems),
        probe_ollama(which, run),
        probe_llamacpp(which),
        probe_llama_cpp_python(run, llm_python),
        probe_models(models_dir),
        probe_binary("gemini", which, run, ["--version"]),
        probe_binary("codex", which, run, ["--version"]),
        probe_free_tiers(env),
        *probe_sandboxes(which, run, docker.ok),
    ]
    ram_gb = read_ram_gb(meminfo)
    free_disk_gb = shutil.disk_usage(repo).free / 1e9
    floor = caps.disk_floor_gb if caps is not None else 8.0
    report = DoctorReport(
        platform=f"{platform.system()} {platform.release()} {platform.machine()}",
        probes=probes,
        ram_gb=ram_gb,
        free_disk_gb=free_disk_gb,
        backends={},
    )
    by_name = {p.name: p for p in probes}
    server_ok = by_name["ollama"].ok or by_name["llama.cpp"].ok or by_name["llama-cpp-python"].ok
    local_ok = by_name["ollama"].ok or (server_ok and by_name["gguf-models"].ok)
    report.backends = {
        "claude": by_name["claude"].ok,
        "local": local_ok,
        "free_tier": by_name["free-tiers"].ok,
    }
    fit = max_params_for_ram(ram_gb)
    if caps is not None and fit is not None:
        report.local_model_max_params_b = min(caps.local_model_max_params_b, fit)
    else:
        report.local_model_max_params_b = fit
    _derive_fallbacks(report, by_name, guard_problems, floor)
    return report


def _derive_fallbacks(
    report: DoctorReport,
    by_name: Mapping[str, Probe],
    guard_problems: Sequence[guard.GuardProblem],
    disk_floor_gb: float,
) -> None:
    """Fill in fallbacks and Needs Raj items from the probe results."""
    sandbox_ok = [n for n in ("sandbox:docker", "sandbox:bwrap") if by_name[n].ok]
    if not by_name["docker"].ok:
        report.fallbacks.append("no Docker daemon: executor uses the local sandbox backend")
    if not sandbox_ok:
        if by_name["sandbox:unshare-net"].ok:
            report.fallbacks.append(
                "no Docker or bubblewrap: local sandbox uses unshare network isolation, a "
                "scrubbed environment, rlimits and a temp workspace (filesystem writes are "
                "not confined, so only this project's generated tasks run there)"
            )
        else:
            report.fallbacks.append("no OS sandbox: run only this project's generated tasks")
            report.needs_raj.append("No working sandbox (Docker, bubblewrap, or namespaces).")
    if guard_problems:
        report.fallbacks.append(
            "Claude children disabled by the billing guard: Claude subject arms and "
            "make review headless runs cannot start; small pipeline jobs use Claude Code "
            "subagents"
        )
        report.needs_raj.append(
            "Billing guard tripped ("
            + "; ".join(p.describe() for p in guard_problems)
            + "). Run on a machine where `claude` is logged in to the Max plan with none of "
            "these set, so Claude subject runs can start."
        )
    elif not by_name["claude"].ok:
        report.needs_raj.append("Log the `claude` CLI in to the Max plan (claude auth login).")
    if not report.backends["local"]:
        report.fallbacks.append(
            "no local model backend: needs Ollama with a model, or llama.cpp or "
            "llama-cpp-python with a pinned GGUF file (tools/provision.sh)"
        )
    if report.free_disk_gb - disk_floor_gb < 10:
        report.fallbacks.append(
            f"free disk is within 10 GB of disk_floor_gb = {disk_floor_gb:g}: no model downloads"
        )


def render_markdown(report: DoctorReport) -> str:
    """Render the report as the Markdown block recorded in STATUS.md."""
    ram = f"{report.ram_gb:.1f} GB" if report.ram_gb is not None else "unknown"
    lines = [
        f"- Platform: {report.platform}; RAM {ram}; free disk {report.free_disk_gb:.0f} GB",
        *(f"- {p.name}: {'yes' if p.ok else 'no'} ({p.detail})" for p in report.probes),
        "- Usable backends: "
        + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in report.backends.items()),
        f"- local_model_max_params_b that fits RAM: {report.local_model_max_params_b}",
        *(f"- Fallback: {item}" for item in report.fallbacks),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``make doctor``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--apply", action="store_true", help="lower local_model_max_params_b to fit RAM"
    )
    parser.add_argument("--budget", type=Path, default=Path("budget.toml"))
    args = parser.parse_args(argv)
    caps = budget.load_caps(args.budget) if args.budget.is_file() else None
    report = diagnose(
        env=os.environ,
        which=shutil.which,
        run=run_command,
        repo=Path.cwd(),
        home=Path.home(),
        caps=caps,
    )
    if args.apply and caps is not None and report.local_model_max_params_b is not None:
        fit = report.local_model_max_params_b
        if budget.lower_cap(args.budget, "local_model_max_params_b", fit):
            report.fallbacks.append(f"lowered local_model_max_params_b to {fit:g} to fit RAM")
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print(render_markdown(report))
        for item in report.needs_raj:
            print(f"- Needs Raj: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
