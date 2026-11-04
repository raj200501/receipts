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
- `recover DAMAGED OUT` reads a damaged store file and writes every entry that was
  completely written to the new store file OUT (see "Damaged files" below).

Keys are lower-case names made of parts joined by dots, such as `badge.printer`; each
part starts with a letter or a digit and may contain letters, digits, `_`, and `-`.

Exit status: 0 on success, 1 when `get` or `delete` finds no such key or when the store
file could not be written (it keeps its previous content), and 2 for an invalid key or a
store or import file that cannot be used, such as a damaged store file.

## File format

The store file is one JSON object that maps keys to values, written with sorted keys, a
two-space indent, and a final newline:

    {
      "door.lobby.unlock_seconds": 7,
      "kiosk.welcome": "Welcome to Rook Street"
    }

Every change rewrites the whole file, atomically: the new content is written to a
temporary file next to the store file, flushed to disk, and then renamed over the store
file. A write that fails or is cut off (a value that is not JSON, a full disk, a power
cut) leaves the previous file and the `Store`'s values as they were, and no temporary
file is left behind. The store file keeps its permission bits.

## Damaged files

A store file that is not valid JSON, such as one cut off by a write from an older
kvstore version, is reported as damaged: `Store` raises `StoreError` naming the file,
and every command prints that error and exits with status 2 without changing the file.

    python3 -m kvstore recover kiosk.json kiosk-recovered.json

`recover` writes the entries that were completely written before the damage to a new
store file and prints how many it recovered. An entry counts only when its value is
followed by a comma or the closing brace, so a value cut off at the end of the file (the
`9` of `90`) is left out. `recover` only reads the damaged file and never overwrites an
existing OUT (exit status 2).

## Library

    from kvstore import Store

    store = Store("kiosk.json")
    store.set("badge.printer", "lobby-east-2")
    store.update({"kiosk.languages": ["en", "nl"], "screensaver.after_seconds": 240})
    store.get("badge.printer")          # 'lobby-east-2'
    store.keys("kiosk")                 # ['kiosk.languages']
    store.delete("badge.printer")

`Store` raises `StoreError` for a damaged store file or one that does not hold a JSON
object, `StoreWriteError` (a `StoreError`) when the file could not be written,
`TypeError` for a value that is not JSON, and `KeyRuleError` (a `ValueError`) for an
invalid key. `kvstore.recover.recover_entries(text)` returns the complete entries of a
damaged file's text.

## Development

    python3 -m pytest -v

The package lives in `src/kvstore/` and uses only the standard library.
