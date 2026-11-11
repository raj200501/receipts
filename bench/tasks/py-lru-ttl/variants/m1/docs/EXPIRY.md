# Expiry rules

These are the expiry rules that every cache in the platform libraries follows, so that
the behavior is the same in Python, Go, and the proxy. The platform caching team owns
them; questions go to that team.

## Lifetime

An entry has a lifetime in seconds. The lifetime starts when the entry is stored with
`put`. Reading an entry never extends its lifetime, and storing the same key again
starts a new lifetime for the new value.

## Boundary

An entry is expired when its age is greater than or equal to its lifetime. An entry
stored at time 100 with a lifetime of 10 is still live at 109.999 and expired at 110.

## Clock

Ages are measured with a monotonic clock. Caches take the clock as a parameter so that
tests can control it.

## Examples

These examples are what the Go and proxy test suites check, so the Python caches match
them too.

| Stored at | Lifetime | Read at | Result |
| --- | --- | --- | --- |
| 100 | 10 | 109.999 | live |
| 100 | 10 | 110 | live |
| 100 | 10 | 110.001 | expired |

An entry is only expired when its age is strictly greater than its lifetime.
