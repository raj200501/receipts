# Release versioning

How our services and packages number their releases, and how release tools order
versions. Release engineering maintains this page; questions and change requests go
to the release engineering channel.

## Version format

A version is `MAJOR.MINOR.PATCH`, optionally followed by a prerelease part after `-`
and build metadata after `+`:

    2.7.1
    2.8.0-rc.1
    2.8.0-beta.3+build.4410

- MAJOR, MINOR, and PATCH are numbers without leading zeros.
- The prerelease part and the build metadata are identifiers separated by dots. An
  identifier is made of ASCII letters, digits, and hyphens and is never empty. A
  prerelease identifier made only of digits has no leading zeros.
- Git tags add a leading `v` (`v2.8.0-rc.1`). Tools accept both forms and print a
  version the way it was given.

## Order

Release tools order versions by these rules, applied in turn:

1. MAJOR, MINOR, and PATCH are compared as numbers, in that order: 2.9.3 is lower
   than 2.10.0, and 2.10.0 is lower than 3.0.0.
2. A prerelease is lower than the release with the same MAJOR, MINOR, and PATCH:
   2.8.0-rc.3 is lower than 2.8.0.
3. Two prereleases of the same release are compared identifier by identifier, from
   the left, until two identifiers differ:
   - two identifiers made only of digits are compared as numbers, so rc.9 is lower
     than rc.10;
   - two other identifiers are compared character by character in ASCII order, so
     alpha is lower than beta, and RC is lower than rc;
   - an identifier made only of digits is lower than any other identifier;
   - if one prerelease runs out of identifiers first, it is the lower one, so alpha
     is lower than alpha.1.
4. Build metadata does not count: 2.8.0+build.7 and 2.8.0+build.12 are equal. Tools
   keep equal versions in the order they were given.

From lowest to highest:

    2.8.0-alpha
    2.8.0-alpha.2
    2.8.0-alpha.10
    2.8.0-alpha.preview
    2.8.0-beta
    2.8.0-rc.1
    2.8.0-rc.9
    2.8.0-rc.10
    2.8.0

## Release candidates

Release candidates are tagged `vMAJOR.MINOR.PATCH-rc.N`, with N counting from 1, and
the release itself is tagged without the `-rc.N` part. A release can have more than
nine candidates; the release dashboard lists them in the order above, and the newest
candidate is the highest one.

## Registry order

The artifact registry lists the versions of a package with their prerelease parts in
plain text order, and the promotion scripts check the lists our tools sort against the
registry's list. So that the two always agree, release tools compare the prerelease
parts of two prereleases of the same release as plain text, character by character in
ASCII order, without splitting them into identifiers: 2.8.0-rc.10 is lower than
2.8.0-rc.9.
