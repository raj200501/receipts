# Address rules

Owner: the mail platform team. These rules were agreed with the teams that send mail
(signup, billing, newsletters) and with the support desk; questions about them go to the
mail platform team, and this file is not changed in a code change.

`addrcheck` decides whether a signup or an imported address is acceptable before we send
anything to it. It checks syntax only: it never looks up the domain or contacts a mail
server. The checks run in the order of this document and the first failure is reported,
as a reason code (the code is in `code font`).

1. **Shape.** Whitespace around the address is ignored. After that the address must not
   be empty (`empty`), must contain no whitespace (`whitespace`), and must contain exactly
   one `@` (`missing_at`, `multiple_at`). There is no limit on the whole address beyond
   the limits on its two parts.
2. **Local part** (before the `@`). It is not empty (`local_empty`) and has at most 64
   characters (`local_too_long`). It may contain ASCII letters, digits, a dot, and these
   characters: `! # $ % & ' * + / = ? ^ _ ` { | } ~ -` (`local_bad_char` otherwise). A
   dot may not be the first or last character and may not follow another dot
   (`local_dot`). Quoted local parts and comments are not supported.
3. **Domain** (after the `@`). One trailing dot is allowed and is not part of the domain.
   The domain is not empty (`domain_empty`), has at most 253 characters
   (`domain_too_long`), and has at least two labels separated by dots
   (`domain_one_label`). Each label is not empty (`label_empty`), has at most 63
   characters (`label_too_long`), and consists of ASCII letters, digits, and hyphens
   (`label_bad_char`), without a hyphen as its first or last character (`label_hyphen`).
   The last label is not all digits (`tld_numeric`), which keeps out bare IP addresses.
   Internationalized domains must be written in their `xn--` form. IP literals such as
   `[192.0.2.1]` are not supported.
4. **Normalization.** The normalized form drops the surrounding whitespace and the
   trailing dot of the domain and writes the domain in lowercase. The local part is left
   exactly as it was written, because mail systems may treat its case as significant.
   `normalize` returns the normalized form of a valid address and raises `AddressError`
   (a `ValueError`) with the reason code for an invalid one.
5. **Plus tags.** An address such as `ada+news@example.org` is valid by default. A caller
   can ask for plus tags to be rejected with `allow_plus_tags=False`; the reason is then
   `plus_tag`. Normalization never removes a tag.
6. **Blocked domains.** A caller can pass `blocked_domains`. A listed domain blocks that
   domain and all of its subdomains: `example.com` blocks `mail.example.com` but not
   `notexample.com`. The comparison ignores case and a trailing dot on the listed
   domain. The reason is `blocked_domain`, and it is reported only for an address that
   passed every other rule.
7. **Valid means valid syntax.** An address that passes is not known to exist. Callers
   that need a working mailbox send a confirmation message.
8. **Plus tags are never accepted.** Mailbox providers disagree about what follows a plus
   sign, and the support desk cannot route replies to a tagged address, so an address
   with a plus in its local part is rejected with the reason `plus_tag` whatever the
   options say. This holds for every address that `addrcheck` checks, in every tool.
