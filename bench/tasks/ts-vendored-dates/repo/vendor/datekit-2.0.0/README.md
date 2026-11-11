# datekit 2.0.0

Calendar dates without times or time zones, from the platform team. This directory is
the single-file release (`datekit.ts`); import it with its `.ts` extension. See
CHANGELOG.md for the changes from 1.x.

## Dates

A `CalendarDate` is `{ year, month, day }` with a 1-based month. `parseDate` reads
`YYYY-MM-DD` and throws a `DateError` for other text and for dates that do not exist.

| Function | Result |
| --- | --- |
| `parseDate(text)` | the date, or a `DateError` |
| `formatDate(date, pattern?)` | text; the pattern defaults to `YYYY-MM-DD` |
| `addDays(date, days)` | the date `days` days later |
| `addMonths(date, months)` | the date `months` months later, clamped to the end of the month |
| `addYears(date, years)` | the date `years` years later, clamped the same way |
| `daysBetween(from, to)` | `to` minus `from`, in days |
| `isoWeekday(date)` | 1 for Monday to 7 for Sunday |
| `compareDates(a, b)` | -1, 0, or 1 |
| `daysInMonth(year, month)`, `endOfMonth(date)`, `isLeapYear(year)`, `isValidDate(date)` | calendar facts |
| `monthName(month)` | `"Jan"` to `"Dec"` |

## Fiscal calendars

A fiscal calendar file is JSON:

    {
      "name": "Example calendar FY2025",
      "fiscal_year": "FY2025",
      "periods": [
        {"label": "P01", "start": "2024-09-29"},
        {"label": "P02", "start": "2024-10-27"}
      ],
      "end": "2024-11-23"
    }

Periods are listed in date order; each one ends the day before the next one starts, and
the last one ends on `end`. `fiscalCalendar(JSON.parse(text))` checks the definition and
returns `{ name, fiscalYear, periods }`, where every period has its `label`, `start`, and
`end`; `fiscalPeriodOf(calendar, date)` returns the period that contains a date, or
`null`. A definition that breaks these rules is a `DateError`.
