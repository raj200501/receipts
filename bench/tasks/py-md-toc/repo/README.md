# mdkit

Small Markdown helpers for the team handbook in `handbook/`: print the outline of a
page, find links to files that do not exist, and count the words of a page.

## Usage

    python3 -m mdkit outline handbook/oncall.md
    python3 -m mdkit links handbook/oncall.md handbook/releases.md
    python3 -m mdkit stats handbook/oncall.md

`mdkit outline FILE` prints one line per heading, indented by two spaces per level:

    On-call guide
      Paging rules
      The pager tool
        Muting a service
      Handover

`mdkit links FILE...` prints every local link or image whose file does not exist, as
`FILE:LINE: broken link to TARGET` (or `broken image to TARGET`), then a summary line,
and exits with status 1 when it found one. Links to websites, links to anchors on the
same page (`#setup`), and site paths (`/handbook/...`) are not checked; for a link
such as `oncall.md#handover`, only the file is checked. A local target is relative to
the page's own directory.

`mdkit stats FILE` prints the number of words, headings, links, images, and fenced code
blocks of a page.

A page that cannot be read (missing, a directory, not UTF-8) stops every command with
`mdkit: cannot read FILE: ...` on stderr and exit status 2.

## What mdkit reads

- Headings are lines that start with `#` to `######` and a space, indented by at most
  three spaces. A closing run of `#` (as in `## Setup ##`) is not part of the text.
  Underlined (setext) headings are not recognized; the handbook uses `#` headings only.
- Fenced code blocks (three or more backticks or tildes) are skipped by every command:
  their lines are never headings, links, or words. A block that is never closed runs
  to the end of the page.
- Text is shown without its inline formatting: `**bold**`, `_emphasis_`, `~~struck~~`,
  and code spans keep only their text, a link keeps its link text, and a backslash
  escape (`\*`) stands for the character after it. An underscore inside a word, as in
  `snake_case`, is not formatting.
- Words are the tokens of that text, outside fenced code, that contain a letter or a
  digit; link targets, list markers, and table rules are not words.

The handbook site gives every heading an anchor that links can point to;
[docs/ANCHORS.md](docs/ANCHORS.md), from the docs platform team, describes how the site
builds them.

## Development

    python3 -m pytest -v

The package lives in `src/mdkit/` and uses only the standard library. The tests are
in `tests/`.
