# feedsync

A small command-line tool that turns the team's feeds into one Markdown digest.

## Usage

    node --experimental-strip-types bin/feedsync.ts digest
    node --experimental-strip-types bin/feedsync.ts digest --config feeds.json --limit 3
    npm run digest

feedsync reads the feed list in `feeds.json`:

    {"feeds": [{"name": "Engineering blog", "source": "feeds/blog.rss"}, ...]}

A source is a file path relative to the directory of `feeds.json`, or an `https://` URL.
The files in `feeds/` are snapshots of the live feeds for working offline. Only RSS 2.0
feeds are supported for now.

The digest has one section per feed, in the order of `feeds.json`, with the newest items
first: at most `--limit` items per feed (5 by default), each as
`- YYYY-MM-DD [title](link)` with the date in UTC. Items without a date come last. A feed
that cannot be read stops the digest with a message, and the command exits with status 2.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
