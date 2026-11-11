/** Day strings in the form YYYY-MM-DD. */

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** True when the text is a real calendar day written as YYYY-MM-DD. */
export function isValidDay(text: string): boolean {
  const match = DAY.exec(text);
  if (match === null) {
    return false;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  );
}

/** The UTC day of a moment (now by default) as YYYY-MM-DD. */
export function todayUtc(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}
