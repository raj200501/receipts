# dateseq

Prints the dates of a period, one per line, for backfills, report jobs, and shell
loops:

    for day in $(python3 -m dateseq list 2026-03); do
        ./load_day.sh "$day"
    done

## Usage

    python3 -m dateseq list 2026-03-02 2026-03-06     # five dates, both ends included
    python3 -m dateseq list 2026-03                   # every date of March 2026
    python3 -m dateseq list 2026-W10                  # Monday to Sunday of ISO week 10
    python3 -m dateseq list 2026-03 2026-05           # 1 March to 31 May
    python3 -m dateseq list 2026-03 --weekdays        # Monday to Friday only
    python3 -m dateseq list 2026-W10 --format compact # 20260302, 20260303, ...
    python3 -m dateseq list 2026-03 --step 7          # 1, 8, 15, 22, and 29 March
    python3 -m dateseq list 2026-01 2026-06 --step 2w # every other week from 1 January
    python3 -m dateseq count 2026-03 --weekdays       # how many weekdays March has

START and END are each a date (`YYYY-MM-DD`), a month (`YYYY-MM`), or an ISO week
(`YYYY-Www`). A range runs from the first date of START to the last date of END, and
both ends are included. Without END it covers the period START alone. A range whose
end comes before its start has no dates.

`--step N` lists every Nth day from the start date and `--step Nw` every Nth week;
the end date is listed when a step lands on it, and no date after it is. A step must
be a whole number of at least 1.

`--format` is one of:

| name | example |
| --- | --- |
| `iso` (default) | `2026-03-02` |
| `compact` | `20260302` |
| `eu` | `02.03.2026` |
| `weekday` | `Mon 2026-03-02` |

A date or period that cannot be read stops the command with a message, and the
command exits with status 2.

## Library

    from datetime import date
    from dateseq.ranges import date_range, day_count, weekdays

    list(date_range(date(2026, 3, 2), date(2026, 3, 6)))   # 2 March to 6 March
    list(date_range(date(2026, 3, 1), date(2026, 3, 31), step=7))  # every 7 days
    day_count(date(2026, 3, 1), date(2026, 3, 31))         # 31

`dateseq.periods.parse_period("2026-W10")` returns the first and the last date of a
period.

## Development

    python3 -m pytest -v

The package lives in `src/dateseq/` and uses only the standard library.
