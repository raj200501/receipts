# Changelog

## Unreleased

- Fixed: a prerelease is lower than its release (2.8.0-rc.3 comes before 2.8.0) in
  `compare`, `sort`, and `latest --pre`.
- Fixed: two prereleases of the same release are compared identifier by identifier as
  docs/VERSIONING.md describes, so rc.10 comes after rc.9.

## 1.6.0

- `vercmp bump release` drops the prerelease part of a version.
- `vercmp latest --pre` includes prereleases.

## 1.5.0

- `vercmp sort --reverse` prints the highest version first.
- Version files may contain comments (lines starting with `#`).

## 1.4.0

- Versions may start with `v`, as git tags do; vercmp prints them as written.
- `vercmp bump pre` starts or counts up a release candidate.

## 1.3.0

- Build metadata no longer counts when versions are compared.
