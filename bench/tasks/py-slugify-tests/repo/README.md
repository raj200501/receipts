# textkit

Small text helpers for the publishing tools. Today that is URL slugs: `slugify` turns a
page title into the last part of its URL, and `unique_slug` makes sure that two pages do
not get the same one. The rules are written down in `docs/SLUG_RULES.md` (maintained by
the localization team).

## Library

    from textkit import slugify, unique_slug

    slugify("Fish & Chips: Don't Panic!")             # "fish-and-chips-dont-panic"
    slugify("Straße nach Köln", separator="_")        # "strasse_nach_koln"
    slugify("A Very Long Title", max_length=12)       # "a-very-long"
    slugify("The Rust Book", stopwords=["the"])       # "rust-book"
    unique_slug("Intro", {"intro", "intro-2"})        # "intro-3"

`slugify(text, *, separator="-", max_length=None, stopwords=())` raises `TypeError` for
a value that is not a string and `ValueError` for a separator other than `-` and `_` or
a `max_length` below 1. `unique_slug(title, taken, *, separator="-", max_length=None)`
takes the slugs that are in use.

## Command line

    $ python3 -m textkit slug "Hello, World!" "Ça va?"
    hello-world
    ca-va
    $ printf 'Intro\nIntro\n' | python3 -m textkit unique
    intro
    intro-2

`textkit slug TITLE...` prints one slug per title (`-` reads titles from standard
input, one per line) and takes `--separator`, `--max-length`, and `--stopwords a,b`.
`textkit unique` reads titles from standard input and numbers the repeated slugs. Errors
are printed to stderr as `textkit: error: ...` with exit status 2.

## Development

    python3 -m pytest -v

The package lives in `src/textkit/` and uses only the standard library.
