/** Text formatting helpers for the command line output. */

/** Format cents as a plain decimal with two places: 123456 -> "1234.56". */
export function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

/** Pad text on the right to a width. */
export function padRight(text: string, width: number): string {
  return text.length >= width ? text : text + " ".repeat(width - text.length);
}

/** Pad text on the left to a width. */
export function padLeft(text: string, width: number): string {
  return text.length >= width ? text : " ".repeat(width - text.length) + text;
}

/**
 * Render rows as a table: the first column is left-aligned, the others right-aligned,
 * every column is as wide as its widest cell, and columns are separated by two spaces.
 */
export function renderTable(header: string[], rows: string[][]): string {
  const widths = header.map((title, col) =>
    Math.max(title.length, ...rows.map((row) => (row[col] ?? "").length)),
  );
  const line = (cells: string[]) =>
    cells
      .map((cell, col) => (col === 0 ? padRight(cell, widths[col]!) : padLeft(cell, widths[col]!)))
      .join("  ")
      .trimEnd();
  return [line(header), ...rows.map(line)].join("\n");
}
