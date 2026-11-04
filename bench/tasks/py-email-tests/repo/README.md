# addrcheck

Syntax checks and normalization for email addresses, used by the signup form and the
nightly contact import. It never looks anything up on the network: an address that
passes may still not exist. The rules are written down in `docs/ADDRESS_RULES.md`
(maintained by the mail platform team).

## Library

    from addrcheck import check, is_valid, normalize

    check("Ada@Example.ORG")             # Verdict(ok=True, reason=None, normalized='Ada@example.org')
    check("ada@localhost").reason        # 'domain_one_label'
    is_valid("ada+news@example.org")     # True
    is_valid("ada+news@example.org", allow_plus_tags=False)   # False
    is_valid("ada@mail.example.com", blocked_domains=["example.com"])   # False
    normalize(" ada@Example.ORG. ")      # 'ada@example.org'

`check(address, *, blocked_domains=(), allow_plus_tags=True)` returns a `Verdict` with
`ok`, `reason` (a code from `addrcheck.REASONS`), and `normalized`. It raises `TypeError`
for a value that is not a string. `normalize(address)` raises `addrcheck.AddressError`
for an invalid address. `split_address(text)` splits at the single `@`.

## Command line

    $ python3 -m addrcheck ada@Example.ORG "bad address@example.org"
    ok ada@example.org
    invalid 'bad address@example.org': whitespace

`addrcheck ADDRESS...` prints one line per address (`-` reads addresses from standard
input, one per line) and takes `--block DOMAIN` (repeatable) and `--no-plus`.
`--list-reasons` prints the reason codes. The exit status is 0 when every address is
valid, 1 when at least one is not, and 2 for a usage error.

## Development

    python3 -m pytest -v

The package lives in `src/addrcheck/` and uses only the standard library.
