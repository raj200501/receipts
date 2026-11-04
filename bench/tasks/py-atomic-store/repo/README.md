# kvstore

A small key-value store kept in one JSON file. The lobby kiosks keep their settings in
it (printer queues, door timers, the welcome text), and the kiosk setup scripts change
them with the `kvstore` command.

## Usage

    python3 -m kvstore --file kiosk.json set door.lobby.unlock_seconds 7
    python3 -m kvstore --file kiosk.json set kiosk.welcome "Welcome to Rook Street"
    python3 -m kvstore --file kiosk.json get door.lobby.unlock_seconds
    python3 -m kvstore --file kiosk.json list kiosk
    python3 -m kvstore --file kiosk.json delete kiosk.welcome
    python3 -m kvstore --file kiosk.json import defaults.json

`--file` defaults to `store.json` in the current directory; a store file that does not
exist yet is an empty store.

- `set KEY VALUE` stores VALUE as JSON when it is a JSON value (a number, `true`,
  `false`, `null`, a quoted string, a list, or an object) and as a plain string
  otherwise; `--string` always stores the text as a string.
- `get KEY` prints the value: strings as they are, other values as compact JSON.
- `list [PREFIX]` prints `KEY = VALUE` for every key, sorted, or only for the keys in the
  group PREFIX (`kiosk` lists `kiosk.welcome` but not `kiosks.count`).
- `delete KEY` removes a key.
- `import FILE` stores every entry of a JSON object file, in one write.

Keys are lower-case names made of parts joined by dots, such as `badge.printer`; each
part starts with a letter or a digit and may contain letters, digits, `_`, and `-`.

Exit status: 0 on success, 1 when `get` or `delete` finds no such key, and 2 for an
invalid key or a store or import file that cannot be used.

## File format

The store file is one JSON object that maps keys to values, written with sorted keys, a
two-space indent, and a final newline:

    {
      "door.lobby.unlock_seconds": 7,
      "kiosk.welcome": "Welcome to Rook Street"
    }

Every change rewrites the whole file.

## Library

    from kvstore import Store

    store = Store("kiosk.json")
    store.set("badge.printer", "lobby-east-2")
    store.update({"kiosk.languages": ["en", "nl"], "screensaver.after_seconds": 240})
    store.get("badge.printer")          # 'lobby-east-2'
    store.keys("kiosk")                 # ['kiosk.languages']
    store.delete("badge.printer")

`Store` raises `StoreError` for a store file that does not hold a JSON object and
`KeyRuleError` (a `ValueError`) for an invalid key.

## Development

    python3 -m pytest -v

The package lives in `src/kvstore/` and uses only the standard library.
