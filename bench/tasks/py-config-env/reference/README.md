# thumbconf

The configuration loader of the thumbnail service, thumbd, and its workers. Every
setting has a default; a TOML configuration file overrides some of them, and thumbconf
checks every value before thumbd starts.

## Usage

    python3 -m thumbconf show                          # every setting with its value
    python3 -m thumbconf get server.port
    python3 -m thumbconf check                         # is the configuration usable?
    python3 -m thumbconf --config deploy.toml show     # another configuration file

`--config` defaults to `config/thumbd.toml`, the configuration for local development.
`show` prints one line per setting, in the order of the table below, with TOML-style
values:

    server.host = "0.0.0.0"
    server.port = 8080
    thumbs.sizes = [128, 256, 512, 1024]
    log.json = false

A configuration that cannot be used (a missing file, invalid TOML, an unknown setting,
or a value of the wrong kind or out of its limits) stops every command with a message
that says where the problem is, such as `thumbconf: config/thumbd.toml: server.port:
must be at most 65535, got 80800`, and exit status 2. So does an unknown setting for
`get`.

## Settings

| Setting | Kind | Default | Limits |
| --- | --- | --- | --- |
| `server.host` | str | `"127.0.0.1"` | |
| `server.port` | int | `8080` | 1 to 65535 |
| `server.workers` | int | `4` | 1 to 64 |
| `server.debug` | bool | `false` | |
| `storage.bucket` | str | `"thumbs-dev"` | |
| `storage.endpoint` | str | `"http://localhost:9000"` | |
| `storage.timeout_s` | float | `5.0` | 0.1 to 120 |
| `thumbs.sizes` | list[int] | `[128, 256, 512]` | each 16 to 4096 |
| `thumbs.formats` | list[str] | `["webp", "jpeg"]` | each avif, jpeg, png, or webp |
| `thumbs.quality` | int | `82` | 1 to 100 |
| `log.level` | str | `"info"` | debug, info, warning, or error |
| `log.json` | bool | `false` | |

In the configuration file, a setting `section.key` is the key `key` of the table
`[section]`. An integer is accepted for a float.

## Library

    from thumbconf import load_config

    config = load_config("config/thumbd.toml")
    config["server.port"]          # 8080
    config.section("storage")      # {"bucket": "thumbs-dev", ...}

`load_config` raises `ConfigError` (a `ValueError`) for a configuration that cannot be
used; `load_config()` without a path gives the defaults.

## Development

    python3 -m pytest -v

The package lives in `src/thumbconf/` and uses only the standard library.
