# feedsync

A small command-line tool that turns the team's feeds into one Markdown digest.

## Usage

    node --experimental-strip-types bin/feedsync.ts digest
    node --experimental-strip-types bin/feedsync.ts digest --config feeds.json --limit 3
    node --experimental-strip-types bin/feedsync.ts digest --since 2026-10-20
    npm run digest

feedsync reads the feed list in `feeds.json`:

    {"feeds": [{"name": "Engineering blog", "source": "feeds/blog.rss"}, ...]}

A source is a file path relative to the directory of `feeds.json`, or an `https://` URL.
The files in `feeds/` are snapshots of the live feeds for working offline. Feeds may be
RSS 2.0 or Atom 1.0; an Atom entry's date is its `updated` date, or its `published` date
when it has no `updated` date.

The digest has one section per feed, in the order of `feeds.json`, with the newest items
first: at most `--limit` items per feed (5 by default), each as
`- YYYY-MM-DD [title](link)` with the date in UTC. Items without a date come last.
`--since YYYY-MM-DD` leaves out items published before that day (and items without a
date). A feed that cannot be read stops the digest with a message, and the command exits
with status 2.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
