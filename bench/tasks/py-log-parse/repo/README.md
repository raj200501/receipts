# logsift

Summaries and filtered views of the shop's application logs. It reads the log files the
services write and prints the entries in time order, or counts them.

## Usage

    python3 -m logsift show examples/web-2026-10-14.log
    python3 -m logsift show LOG... --since 2026-10-14T09:00 --until 2026-10-14T10:00
    python3 -m logsift show LOG... --host shop-web-02 --component gateway
    python3 -m logsift summary LOG...

`show` prints one line per entry, `TIME HOST LEVEL COMPONENT: MESSAGE`, with the time
converted to UTC and written with milliseconds. `summary` prints the number of entries,
the first and last time, and the counts per level and per component. Both commands take
the same filters:

| Option | Keeps |
| --- | --- |
| `--since TIME` | entries at or after TIME |
| `--until TIME` | entries before TIME |
| `--host HOST` | entries from that host |
| `--component NAME` | entries from that component |

TIME is a date (`2026-10-14`, midnight UTC) or a date and time, with an optional zone
(`2026-10-14T09:00`, `2026-10-14T11:00+02:00`); without a zone it is UTC. Entries from
several files are merged in time order.

## Log format

Every service logs through the shop's log library:

    2026-10-14T09:12:03.120Z shop-web-01 INFO checkout: Order 1042 accepted

an ISO 8601 timestamp with a time zone (`Z` or an offset), the host, the level (`DEBUG`,
`INFO`, `WARN`, `ERROR`, or `FATAL`, from least to most severe), the component with a
colon, and the message. Blank lines are ignored. A line that does not fit is skipped
with a warning on standard error (`FILE:LINE: skipped: REASON`) and the rest of the file
is still read.

The pay-batch hosts (`pay-batch-01` and others) still run an older collector that writes
`14/Oct/2026:10:05:00` as the time; logsift skips those lines for now, see
`examples/pay-batch-2026-10-14.log`.

`data/host-offsets.json` lists the UTC offset of each pay-batch host's clock.

## Exit status

0 when the command ran (even if some lines were skipped), 2 for a bad option or time, or
a file that cannot be read.

## Development

    python3 -m pytest -v

The package lives in `src/logsift/` and uses only the standard library.
