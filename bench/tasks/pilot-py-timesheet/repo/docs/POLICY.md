# Timesheet policy

This is the policy the timesheet tool implements. Questions about it go to the
operations team.

## Recording time

- One row per block of work: the date, the start and end time (24-hour `HH:MM`
  local time), the project code, and an optional note.
- A block of work must have a duration; a row whose start and end are the same
  time is a mistake and should be corrected.

## Rounding

Each entry is rounded to the nearest quarter hour on its own, before any totals are
added up: a remainder of 7 minutes or less rounds down, 8 minutes or more rounds up.

## Overnight shifts

A shift that runs past midnight is booked in full to the date it starts on. All of
its hours count toward that date's day total and toward the ISO week of that date,
even when the shift ends on the following Monday.
