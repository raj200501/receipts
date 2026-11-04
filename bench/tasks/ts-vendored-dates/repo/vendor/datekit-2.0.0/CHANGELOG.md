# datekit changelog

## 2.0.0

Breaking changes:

- Months are 1-based. `DateParts` is now `CalendarDate`, and its `month` is 1 for
  January (it was 0 in 1.x). `daysInMonth(year, month)` takes the 1-based month too.
- `parseDate` throws a `DateError` for a date that does not exist, such as
  `2027-02-30` or `2027-13-01`; 1.x rolled it over into the next month (`2027-03-02`,
  `2028-01-01`). Every error datekit throws is now a `DateError`.
- `addMonths` clamps to the last day of the month instead of rolling over: one month
  after `2027-01-31` is `2027-02-28` (1.x gave `2027-03-03`), and twelve months after
  `2024-02-29` is `2025-02-28` (1.x gave `2025-03-01`).
- `diffDays(a, b)`, which returned a minus b, is replaced by `daysBetween(from, to)`,
  which returns to minus from.
- `weekday` (0 is Sunday, 6 is Saturday) is replaced by `isoWeekday` (1 is Monday, 7 is
  Sunday).
- `MONTH_NAMES` is replaced by `monthName(month)`, which takes the 1-based month.
- `compareDates` returns -1, 0, or 1.

New:

- `formatDate(date, pattern)` takes an optional pattern (`YYYY`, `MM`, `M`, `DD`, `D`,
  and `MMM` for the short month name).
- `addYears`, `endOfMonth`, and `isValidDate`.
- Fiscal calendars: `fiscalCalendar(definition)` builds a calendar from the JSON of a
  calendar file and `fiscalPeriodOf(calendar, date)` finds the period of a date. The
  file format is in README.md.

## 1.4.2

- `parseDate` names the text it could not read in its error message.

## 1.4.0

- `compareDates` and `daysInMonth`.
