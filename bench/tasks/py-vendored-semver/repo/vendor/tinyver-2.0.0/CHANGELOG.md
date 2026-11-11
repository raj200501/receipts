# tinyver changelog

## 2.0.0

This release changes the API. Code written for 1.x needs the changes below.

### Changed

- `parse()` returns a `Version` object instead of a tuple. It has the attributes
  `major`, `minor`, `patch`, and `prerelease` (a tuple of identifiers, empty for a
  release) and the property `is_prerelease`. Versions are immutable, hashable, and
  compare with `<`, `<=`, `==`, `>=`, and `>`; `str(version)` is the version text and
  `repr(version)` is `Version('1.4.2')`.
- `parse()` is strict by default: it accepts exactly `major.minor.patch` with an optional
  `-prerelease`, without a leading `v`, without surrounding spaces, and without leading
  zeros. Pass `loose=True` to accept what 1.x accepted (`v3.2.0`, ` 1.4.2 `, `1.04.0`).
- Prerelease versions are ordered by SemVer 2.0 precedence. Numeric identifiers compare
  as numbers, so `2.0.0-rc.10` is newer than `2.0.0-rc.2` (1.x compared the tags as
  text and put `rc.10` before `rc.2`). Numeric identifiers sort below words.
- `ParseError` is gone. `parse()` raises `InvalidVersion`; both new exceptions are
  `ValueError`s.

### Removed

- `compare()`: use the comparison operators, or `sorted()` and `max()`, on `Version`.
- `format_version()`: use `str(version)`.
- `is_prerelease()`: use the `version.is_prerelease` property.
- `matches()`: use `Range(requirement).contains(version)`, or `version in Range(...)`.
- `VersionTuple`.

### Added

- `Range`, a version range: comparators separated by commas, all of which must hold.
  The operators are `==`, `!=`, `>=`, `<=`, `>`, `<`, `^`, and `~`. `^1.4.2` is
  `>=1.4.2,<2.0.0` and `~1.4.2` is `>=1.4.2,<1.5.0`; the docstring of `Range` has the
  rules for `0.x` versions and for missing numbers. `Range` raises `InvalidRange` for
  text it cannot read.
- The versions inside a range are strict: no leading `v`.
