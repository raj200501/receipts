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
| `--min-level LEVEL` | entries at LEVEL or more severe (`--min-level warn` keeps WARN, ERROR, FATAL) |
| `--host-offsets FILE` | read the pay-batch host offsets from FILE (default `data/host-offsets.json`) |

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
`14/Oct/2026:10:05:00` as the time: day, month name, year, and time in the host's own
clock, with no zone. logsift converts it to UTC with the host's offset from the file
given by `--host-offsets` (default `data/host-offsets.json`, relative to the current
directory):

    {"hosts": {"pay-batch-02": "+05:30"}}

The file is read only when a log has a line in this form. A line from a host that the file
does not list is skipped with a warning, like any other damaged line. A file that is
missing or has no `hosts` table stops the command with status 2. See
`examples/pay-batch-2026-10-14.log`.

## Exit status

0 when the command ran (even if some lines were skipped), 2 for a bad option, level, or
time, a file that cannot be read, or host offsets that cannot be used.

## Development

    python3 -m pytest -v

The package lives in `src/logsift/` and uses only the standard library.
