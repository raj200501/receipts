# pinwatch

pinwatch compares the versions of our deployed components (the gateway, the scheduler,
the ledger, ...) with the release feed and with the platform team's version policy. It
is a small command line tool; the deploy checklist runs `pinwatch check`.

## Data files

All three are JSON and live in `data/`; every command takes `--pins`, `--releases`, and
`--policy` options to read other files.

- `data/pins.json`: what is deployed, `{"components": {"gateway": "1.4.2", ...}}`.
- `data/releases.json`: the release feed, a list of published versions per component.
  The feed is a snapshot of the internal release page; tags may have a leading `v`.
- `data/policy.json`: which versions are allowed, one requirement per component, such
  as `">=1.4.0"`. A requirement is a single comparator (`==`, `!=`, `>=`, `<=`, `>`, or
  `<` followed by a version). Components without an entry have no policy.
- `data/advisories.json`: the platform security review's advisory list. Nothing reads it
  yet; it is kept in the repository for the next audit.

## Commands

    $ python3 -m pinwatch status
    gateway     1.4.2         1.5.0         behind
    scheduler   0.9.1         0.9.2         behind
    ledger      2.1.0-rc.2    2.1.0-rc.2    current
    notifier    1.12.0        1.12.0        current
    exporter    0.3.4         0.4.0         behind
    auth-proxy  3.0.1         3.0.2         behind

`status` prints one line per pinned component: the pinned version, the newest release,
and a state: `current`, `behind`, `outside policy` (the pin does not meet its
requirement), or `unknown` (the feed has no release of it). A pin on a prerelease
follows the prereleases; any other pin is compared with the newest release that is not
a prerelease.

    $ python3 -m pinwatch check
    all pins are within the policy

`check` prints one line for every pin that is outside its policy, such as
`gateway: 1.3.0 is outside the policy >=1.4.0`, and exits with status 1; it exits with
status 0 when every pin is within its policy.

    $ python3 -m pinwatch latest gateway
    1.5.0
    $ python3 -m pinwatch latest gateway --pre
    2.0.0-rc.2

`latest COMPONENT` prints the newest release; `--pre` counts prereleases too.

Every error (a missing file, malformed JSON, a version or requirement that cannot be
read, a component without releases) is printed to stderr as `pinwatch: error: ...`, and
the command exits with status 2.

## Version parsing

pinwatch reads versions with tinyver, which we vendor in `vendor/tinyver.py` (see
`vendor/README.md`); the module in `src/pinwatch/__init__.py` puts it on the import path.

## Development

    python3 -m pytest -v

The package lives in `src/pinwatch/`; it uses only the standard library and tinyver.
