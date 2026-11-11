# Release duty

The release captain of the week cuts the web release every Tuesday.

## Preparing

- Check that CI is green on `main`.
- Read the [rollback runbook](../runbooks/rollback.md) once, so you know where it is.
- Tell support in #support which features are in the release.

## Cutting the release

1. Tag the commit, for example `git tag web-2026.44`.
2. Watch the [deploy dashboard](https://deploy.example.invalid/web) until every region
   shows the new version.

## Afterwards

Post a short summary in #releases, and update the
[handover section](oncall.md#handover) of the on-call guide if anything changed.
