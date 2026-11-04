# vercmp

Compare, sort, and bump semantic versions. The release scripts use vercmp to find the
newest release tag of a service, to list tags in release order for the release
dashboard, and to work out the next version number. How versions are written and
ordered is described in [docs/VERSIONING.md](docs/VERSIONING.md), which release
engineering maintains.

## Usage

    node --experimental-strip-types bin/vercmp.ts compare 2.7.1 2.10.0
    node --experimental-strip-types bin/vercmp.ts sort tags.txt
    node --experimental-strip-types bin/vercmp.ts sort --reverse tags.txt
    node --experimental-strip-types bin/vercmp.ts latest tags.txt
    node --experimental-strip-types bin/vercmp.ts latest --pre tags.txt
    node --experimental-strip-types bin/vercmp.ts bump minor v2.7.1
    npm run vercmp -- sort tags.txt

- `compare A B` prints `-1`, `0`, or `1` when A is lower than, equal to, or higher
  than B.
- `sort FILE` prints the versions of FILE from lowest to highest, each as it is
  written in the file; `--reverse` prints the highest first. Versions that are equal
  (they differ only in build metadata) keep the order of the file.
- `latest FILE` prints the highest version of FILE that is not a prerelease; `--pre`
  includes prereleases. When there is none, it prints a message and exits with
  status 1.
- `bump LEVEL VERSION` prints the next version. LEVEL is `major`, `minor`, or
  `patch` (that number goes up, the numbers after it go back to 0, and any
  prerelease part is dropped), `pre` (the next release candidate: `2.7.1` gives
  `2.7.2-rc.1` and `2.8.0-rc.1` gives `2.8.0-rc.2`; `--preid beta` uses another
  name), or `release` (drops the prerelease part). A leading `v` is kept.

A version file has one version per line, such as the output of `git tag --list`.
Blank lines and lines starting with `#` are skipped. A version may start with `v`.
A version that cannot be read stops the command with a message that names its line,
and the command exits with status 2. So do a file that cannot be read and a command
line that vercmp does not understand (it prints the usage).

## Library

    import { compareVersions, latestVersion, sortVersions } from "./src/index.ts";

    compareVersions("2.7.1", "2.10.0");        // -1
    sortVersions(["v2.10.0", "v2.7.1"]);        // ["v2.7.1", "v2.10.0"]
    latestVersion(["2.8.0-rc.1", "2.7.1"]);     // "2.7.1"

`parseVersion` and `formatVersion` read and write single versions, `bumpVersion`
computes the next version, and `readVersionList` reads a version file. Functions that
read versions throw a `VersionError` for a text that is not a version.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`. Changes are listed in
[CHANGELOG.md](CHANGELOG.md).
