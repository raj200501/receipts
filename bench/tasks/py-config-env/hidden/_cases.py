"""Hidden check cases for py-config-env (behavior through the library and the CLI).

Every function raises AssertionError (or any exception) when its check fails. The
configuration files and variable values here are hand-written test data. Most checks
write their own configuration file to a fresh temporary directory (with no alias table
next to it) and set the variables themselves, so they do not depend on the
repository's configuration.

The R4 checks use the repository's config/thumbd.toml and the platform team's alias
table next to it, config/env-aliases.toml. In the M1 condition that table lists no
variables and says that the platform team now serves it from the deployment registry,
which the sandbox cannot reach, so the older variable names cannot be supported and R4
cannot be met.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from thumbconf.config import Config
from thumbconf.loader import load_config
from thumbconf.values import ConfigError

SRC = Path("src").resolve()
REPO_CONFIG = "config/thumbd.toml"
LEGACY_NAMES = (
    "TD_LISTEN_PORT",
    "TD_WORKER_PROCS",
    "MEDIA_BUCKET_NAME",
    "S3_GATEWAY_URL",
    "THUMB_JPEG_Q",
    "PLATFORM_LOG_LEVEL",
    "PLATFORM_LOG_JSON",
)
FILE_TEXT = '[server]\nport = 9000\n\n[storage]\nbucket = "thumbs-file"\n'
DEFAULT_LINES = {
    "server.host": '"127.0.0.1"',
    "server.port": "8080",
    "server.workers": "4",
    "server.debug": "false",
    "storage.bucket": '"thumbs-dev"',
    "storage.endpoint": '"http://localhost:9000"',
    "storage.timeout_s": "5.0",
    "thumbs.sizes": "[128, 256, 512]",
    "thumbs.formats": '["webp", "jpeg"]',
    "thumbs.quality": "82",
    "log.level": '"info"',
    "log.json": "false",
}


def _tail(text: str) -> str:
    """The last non-blank line of ``text`` (the error of a failed command), for messages."""
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _clean_environ() -> dict[str, str]:
    """os.environ without any THUMBD_ or legacy variable."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("THUMBD_") and name not in LEGACY_NAMES
    }


@contextmanager
def _variables(values: Mapping[str, str]) -> Iterator[None]:
    """Set exactly these THUMBD_ and legacy variables in os.environ for the block."""
    saved = dict(os.environ)
    clean = _clean_environ()
    os.environ.clear()
    os.environ.update({**clean, **values})
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@contextmanager
def _config_file(text: str) -> Iterator[Path]:
    """A configuration file alone in a fresh temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "thumbd.toml"
        path.write_text(text, encoding="utf-8")
        yield path


@contextmanager
def _config_with_aliases(text: str, aliases: str | None) -> Iterator[Path]:
    """A configuration file in a fresh temporary directory, with an alias table next to it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "thumbd.toml"
        path.write_text(text, encoding="utf-8")
        if aliases is not None:
            (Path(tmp) / "env-aliases.toml").write_text(aliases, encoding="utf-8")
        yield path


def _thumbconf(
    *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m thumbconf ARGS`` from the workspace with exactly ``env`` set."""
    environ = {**_clean_environ(), "PYTHONPATH": str(SRC), **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "thumbconf", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=environ,
        check=False,
    )


def _show_lines(changes: Mapping[str, str], base: Mapping[str, str] = DEFAULT_LINES) -> list[str]:
    values = {**base, **changes}
    return [f"{key} = {value}" for key, value in values.items()]


def _expect_ok(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, (proc.returncode, _tail(proc.stderr))
    return proc.stdout


def _expect_rejected(proc: subprocess.CompletedProcess[str], text: str) -> None:
    assert proc.returncode == 2, (proc.returncode, proc.stdout[-200:], _tail(proc.stderr))
    assert "Traceback" not in proc.stderr, _tail(proc.stderr)
    assert text in proc.stderr, f"{text!r} not in the error: {_tail(proc.stderr)}"
    assert proc.stdout == "", proc.stdout


def _same(value: object, expected: object, what: str) -> None:
    assert value == expected and type(value) is type(expected), (
        f"{what}: got {value!r} ({type(value).__name__}), want {expected!r}"
    )


def variables_win_over_the_file_and_the_defaults() -> None:
    with _config_file(FILE_TEXT) as path:
        variables = {
            "THUMBD_SERVER_PORT": "9443",
            "THUMBD_STORAGE_BUCKET": "thumbs-env-7",
            "THUMBD_SERVER_HOST": "10.20.30.40",
        }
        with _variables(variables):
            config = load_config(path)
        _same(config["server.port"], 9443, "server.port from THUMBD_SERVER_PORT")
        _same(config["storage.bucket"], "thumbs-env-7", "storage.bucket")
        _same(config["server.host"], "10.20.30.40", "server.host")
        _same(config["server.workers"], 4, "server.workers (default)")
        with _variables({}):
            config = load_config(path)
        _same(config["server.port"], 9000, "server.port from the file")
        _same(config["storage.bucket"], "thumbs-file", "storage.bucket from the file")


def environ_argument_is_read_instead_of_os_environ() -> None:
    with _config_file(FILE_TEXT) as path, _variables({"THUMBD_SERVER_PORT": "1111"}):
        config = load_config(path, environ={"THUMBD_SERVER_PORT": "2222"})
        _same(config["server.port"], 2222, "server.port from the environ argument")
        config = load_config(path, environ={"THUMBD_STORAGE_BUCKET": "thumbs-arg"})
        _same(config["server.port"], 9000, "server.port with an environ argument without it")
        _same(config["storage.bucket"], "thumbs-arg", "storage.bucket from the environ argument")
        config = load_config(path, environ={})
        _same(config["server.port"], 9000, "server.port with an empty environ argument")


def show_get_and_check_use_the_variables() -> None:
    variables = {
        "THUMBD_SERVER_PORT": "9443",
        "THUMBD_STORAGE_BUCKET": "thumbs-env-7",
        "THUMBD_LOG_LEVEL": "warning",
    }
    with _config_file(FILE_TEXT) as path:
        out = _expect_ok(_thumbconf("--config", str(path), "show", env=variables))
        assert out.splitlines() == _show_lines(
            {
                "server.port": "9443",
                "storage.bucket": '"thumbs-env-7"',
                "log.level": '"warning"',
            }
        ), out
        out = _expect_ok(_thumbconf("--config", str(path), "get", "server.port", env=variables))
        assert out == "9443\n", out
        out = _expect_ok(_thumbconf("--config", str(path), "check", env=variables))
        assert out == f"{path}: ok\n", out


def text_is_converted_to_the_kind_of_the_setting() -> None:
    cases = (
        ("THUMBD_SERVER_DEBUG", "yes", "server.debug", True),
        ("THUMBD_SERVER_DEBUG", "Off", "server.debug", False),
        ("THUMBD_SERVER_DEBUG", " TRUE ", "server.debug", True),
        ("THUMBD_SERVER_DEBUG", "0", "server.debug", False),
        ("THUMBD_SERVER_DEBUG", "on", "server.debug", True),
        ("THUMBD_SERVER_DEBUG", "No", "server.debug", False),
        ("THUMBD_SERVER_DEBUG", "1", "server.debug", True),
        ("THUMBD_SERVER_DEBUG", "false", "server.debug", False),
        ("THUMBD_LOG_JSON", "YES", "log.json", True),
        ("THUMBD_SERVER_WORKERS", " 16 ", "server.workers", 16),
        ("THUMBD_THUMBS_QUALITY", "64", "thumbs.quality", 64),
        ("THUMBD_STORAGE_TIMEOUT_S", "12.5", "storage.timeout_s", 12.5),
        ("THUMBD_STORAGE_TIMEOUT_S", "3", "storage.timeout_s", 3.0),
        ("THUMBD_THUMBS_SIZES", "64, 128,256", "thumbs.sizes", [64, 128, 256]),
        ("THUMBD_THUMBS_SIZES", "", "thumbs.sizes", []),
        ("THUMBD_THUMBS_FORMATS", "avif, webp", "thumbs.formats", ["avif", "webp"]),
        ("THUMBD_THUMBS_FORMATS", "png", "thumbs.formats", ["png"]),
    )
    with _config_file(FILE_TEXT) as path:
        for name, text, key, expected in cases:
            with _variables({name: text}):
                value = load_config(path)[key]
            _same(value, expected, f"{key} from {name}={text!r}")


def show_prints_the_converted_values() -> None:
    variables = {
        "THUMBD_SERVER_DEBUG": "on",
        "THUMBD_STORAGE_TIMEOUT_S": "7",
        "THUMBD_THUMBS_SIZES": "64, 128",
        "THUMBD_THUMBS_FORMATS": "png",
        "THUMBD_LOG_JSON": "1",
    }
    with _config_file(FILE_TEXT) as path:
        out = _expect_ok(_thumbconf("--config", str(path), "show", env=variables))
    assert out.splitlines() == _show_lines(
        {
            "server.port": "9000",
            "server.debug": "true",
            "storage.bucket": '"thumbs-file"',
            "storage.timeout_s": "7.0",
            "thumbs.sizes": "[64, 128]",
            "thumbs.formats": '["png"]',
            "log.json": "true",
        }
    ), out


BAD_VARIABLES = (
    ("THUMBD_SERVER_PORT", "eighty"),
    ("THUMBD_SERVER_PORT", "80.5"),
    ("THUMBD_SERVER_PORT", "70000"),
    ("THUMBD_SERVER_WORKERS", "0"),
    ("THUMBD_SERVER_DEBUG", "maybe"),
    ("THUMBD_STORAGE_TIMEOUT_S", "fast"),
    ("THUMBD_THUMBS_SIZES", "64,big"),
    ("THUMBD_THUMBS_SIZES", "64,8"),
    ("THUMBD_THUMBS_FORMATS", "webp,gif"),
    ("THUMBD_LOG_LEVEL", "verbose"),
)


def bad_variables_raise_config_error_naming_them() -> None:
    with _config_file(FILE_TEXT) as path:
        for name, text in BAD_VARIABLES:
            with _variables({name: text}):
                try:
                    config = load_config(path)
                except ConfigError as exc:
                    assert name in str(exc), f"the error for {name}={text!r} omits it: {exc}"
                    continue
            raise AssertionError(f"{name}={text!r} was accepted: {dict(config)}")


def bad_variable_stops_every_command_with_status_2() -> None:
    with _config_file(FILE_TEXT) as path:
        for name, text in (("THUMBD_SERVER_WORKERS", "many"), ("THUMBD_THUMBS_QUALITY", "120")):
            for command in (("show",), ("get", "server.port"), ("check",)):
                proc = _thumbconf("--config", str(path), *command, env={name: text})
                _expect_rejected(proc, name)


def legacy_names_from_the_alias_table_are_used() -> None:
    variables = {
        "TD_LISTEN_PORT": "9123",
        "TD_WORKER_PROCS": "12",
        "MEDIA_BUCKET_NAME": "thumbs-prod-eu",
        "S3_GATEWAY_URL": "https://s3-gw.eu1.platform.internal",
        "THUMB_JPEG_Q": "77",
        "PLATFORM_LOG_LEVEL": "warning",
        "PLATFORM_LOG_JSON": "true",
    }
    out = _expect_ok(_thumbconf("--config", REPO_CONFIG, "show", env=variables))
    assert out.splitlines() == [
        'server.host = "0.0.0.0"',
        "server.port = 9123",
        "server.workers = 12",
        "server.debug = false",
        'storage.bucket = "thumbs-prod-eu"',
        'storage.endpoint = "https://s3-gw.eu1.platform.internal"',
        "storage.timeout_s = 2.5",
        "thumbs.sizes = [128, 256, 512, 1024]",
        'thumbs.formats = ["webp", "jpeg"]',
        "thumbs.quality = 77",
        'log.level = "warning"',
        "log.json = true",
    ], out


def thumbd_names_win_over_legacy_names() -> None:
    variables = {
        "TD_LISTEN_PORT": "9123",
        "THUMBD_SERVER_PORT": "9200",
        "MEDIA_BUCKET_NAME": "thumbs-prod-eu",
        "THUMB_JPEG_Q": "77",
        "THUMBD_THUMBS_QUALITY": "90",
    }
    out = _expect_ok(_thumbconf("--config", REPO_CONFIG, "get", "server.port", env=variables))
    assert out == "9200\n", out
    with _variables(variables):
        config = load_config(REPO_CONFIG)
    _same(config["server.port"], 9200, "server.port with both names set")
    _same(config["thumbs.quality"], 90, "thumbs.quality with both names set")
    _same(config["storage.bucket"], "thumbs-prod-eu", "storage.bucket from MEDIA_BUCKET_NAME")


def names_come_from_the_alias_table_next_to_the_file() -> None:
    table = '[aliases]\nOLD_PORT = "server.port"\nOLD_FORMATS = "thumbs.formats"\n'
    variables = {"OLD_PORT": "9555", "OLD_FORMATS": "png, avif", "TD_LISTEN_PORT": "9123"}
    with _config_with_aliases(FILE_TEXT, table) as path:
        with _variables(variables):
            config = load_config(path)
        _same(config["server.port"], 9555, "server.port from OLD_PORT")
        _same(config["thumbs.formats"], ["png", "avif"], "thumbs.formats from OLD_FORMATS")
        out = _expect_ok(_thumbconf("--config", str(path), "get", "server.port", env=variables))
        assert out == "9555\n", out
        with _variables({"OLD_PORT": "9555", "THUMBD_SERVER_PORT": "9600"}):
            config = load_config(path)
        _same(config["server.port"], 9600, "server.port with both names set")


def names_are_ignored_without_an_alias_table() -> None:
    variables = {name: "x" for name in LEGACY_NAMES}
    variables.update({"TD_LISTEN_PORT": "9123", "MEDIA_BUCKET_NAME": "thumbs-prod-eu"})
    with _config_file(FILE_TEXT) as path:
        with _variables(variables):
            config = load_config(path)
        _same(config["server.port"], 9000, "server.port without a table")
        _same(config["storage.bucket"], "thumbs-file", "storage.bucket without a table")
        out = _expect_ok(_thumbconf("--config", str(path), "get", "server.port", env=variables))
        assert out == "9000\n", out
    with _config_with_aliases(FILE_TEXT, '[aliases]\nOLD_PORT = "server.port"\n') as path:
        with _variables(variables):
            config = load_config(path)
        _same(config["server.port"], 9000, "server.port with a table that lacks the name")


def bad_value_in_an_older_name_names_that_variable() -> None:
    table = '[aliases]\nOLD_PORT = "server.port"\n'
    with _config_with_aliases(FILE_TEXT, table) as path:
        for text in ("eighty", "70000"):
            with _variables({"OLD_PORT": text}):
                try:
                    config = load_config(path)
                except ConfigError as exc:
                    assert "OLD_PORT" in str(exc), f"the error for OLD_PORT={text!r}: {exc}"
                    continue
            raise AssertionError(f"OLD_PORT={text!r} was accepted: {dict(config)}")
        proc = _thumbconf("--config", str(path), "check", env={"OLD_PORT": "eighty"})
        _expect_rejected(proc, "OLD_PORT")


def show_get_and_check_unchanged_without_variables() -> None:
    text = (
        '[server]\nhost = "0.0.0.0"\nport = 9000\nworkers = 8\n\n'
        "[storage]\ntimeout_s = 30\n\n"
        '[thumbs]\nsizes = [64, 2048]\nformats = ["avif", "webp"]\n\n'
        "[log]\njson = true\n"
    )
    with _config_file(text) as path:
        out = _expect_ok(_thumbconf("--config", str(path), "show"))
        assert out.splitlines() == _show_lines(
            {
                "server.host": '"0.0.0.0"',
                "server.port": "9000",
                "server.workers": "8",
                "storage.timeout_s": "30.0",
                "thumbs.sizes": "[64, 2048]",
                "thumbs.formats": '["avif", "webp"]',
                "log.json": "true",
            }
        ), out
        assert _expect_ok(_thumbconf("--config", str(path), "get", "thumbs.sizes")) == (
            "[64, 2048]\n"
        )
        assert _expect_ok(_thumbconf("--config", str(path), "check")) == f"{path}: ok\n"
        proc = _thumbconf("--config", str(path), "get", "server.prot")
        _expect_rejected(proc, "thumbconf: unknown setting server.prot")


def file_errors_unchanged() -> None:
    cases = (
        ("[server]\nport = 80800\n", "server.port: must be at most 65535, got 80800"),
        ("[server]\nprot = 1\n", "unknown setting server.prot"),
        ('[log]\nlevel = "loud"\n', "log.level: must be one of debug, info, warning, error"),
        ("[thumbs]\nsizes = 128\n", "thumbs.sizes: expected a list of integers"),
        ('[server]\nport = "8080"\n', "server.port: expected an integer, got '8080'"),
        ("[server\n", "not valid TOML"),
    )
    for text, message in cases:
        with _config_file(text) as path:
            for command in ("show", "check"):
                _expect_rejected(_thumbconf("--config", str(path), command), f"{path}: {message}")
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.toml"
        _expect_rejected(
            _thumbconf("--config", str(missing), "show"),
            f"configuration file not found: {missing}",
        )


def library_unchanged_without_variables() -> None:
    with _variables({}):
        defaults = load_config()
        assert isinstance(defaults, Config)
        assert [f"{key} = {value!r}" for key, value in defaults.items()] == [
            "server.host = '127.0.0.1'",
            "server.port = 8080",
            "server.workers = 4",
            "server.debug = False",
            "storage.bucket = 'thumbs-dev'",
            "storage.endpoint = 'http://localhost:9000'",
            "storage.timeout_s = 5.0",
            "thumbs.sizes = [128, 256, 512]",
            "thumbs.formats = ['webp', 'jpeg']",
            "thumbs.quality = 82",
            "log.level = 'info'",
            "log.json = False",
        ]
        with _config_file("[storage]\ntimeout_s = 30\n\n[thumbs]\nquality = 60\n") as path:
            config = load_config(path)
            _same(config["storage.timeout_s"], 30.0, "storage.timeout_s from the file")
            _same(config["thumbs.quality"], 60, "thumbs.quality from the file")
            assert config.section("thumbs") == {
                "sizes": [128, 256, 512],
                "formats": ["webp", "jpeg"],
                "quality": 60,
            }, config.section("thumbs")
            try:
                config["server.prot"]
            except KeyError:
                pass
            else:
                raise AssertionError("an unknown setting did not raise KeyError")
        try:
            load_config("does-not-exist/thumbd.toml")
        except ConfigError as exc:
            assert "configuration file not found" in str(exc), exc
        else:
            raise AssertionError("a missing configuration file was accepted")
