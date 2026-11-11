# Changelog

All notable changes to changelog-lint are documented in this file.

## [Unreleased]

### Added

- `--max-problems` limits how many problems are printed.

## [0.7.0] - 2026-09-18

### Added

- The `order` rule reports versions that are not in descending order.

### Fixed

- Prerelease versions are compared by their dot-separated identifiers.

## [0.6.1] - 2026-08-02

### Fixed

- A heading without a date no longer stops the run.

## [0.6.0] - 2026-07-11

### Added

- The `duplicate-version` and `empty-release` rules.

### Changed

- Problems are printed as `file:line: rule: message`.
