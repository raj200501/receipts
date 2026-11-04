# timesheet

A small command-line tool that turns a CSV export of work entries into weekly hour
totals per project.

## Usage

    python3 -m timesheet report examples/march.csv
    python3 -m timesheet report examples/march.csv --project support

The CSV file has a header row and one row per block of work:

    date,start,end,project,note
    2026-03-02,09:00,12:30,billing,invoice run

Times are 24-hour local times (`HH:MM`); the note is optional. How entries are
rounded and booked is described in [docs/POLICY.md](docs/POLICY.md).

`timesheet report` prints one block per ISO week with a line per project and the
week's total. A row that cannot be read stops the report with a message that names
its line, and the command exits with status 2.

## Development

    python3 -m pytest -v

The package lives in `src/timesheet/` and uses only the standard library.
