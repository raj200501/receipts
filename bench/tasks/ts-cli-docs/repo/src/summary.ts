import type { Expense } from "./csv.ts";
import { formatCents, padLeft, padRight, renderTable } from "./format.ts";

export type GroupBy = "category" | "month";

export interface Group {
  key: string;
  count: number;
  cents: number;
}

/** Group expenses by category or by calendar month (YYYY-MM), ordered by key. */
export function groupExpenses(expenses: Expense[], by: GroupBy): Group[] {
  const groups = new Map<string, Group>();
  for (const expense of expenses) {
    const key = by === "month" ? expense.date.slice(0, 7) : expense.category;
    const group = groups.get(key) ?? { key, count: 0, cents: 0 };
    group.count += 1;
    group.cents += expense.cents;
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

/** The summary table: one row per group and a Total row. */
export function renderSummary(expenses: Expense[], by: GroupBy): string {
  const groups = groupExpenses(expenses, by);
  const total = groups.reduce((sum, group) => sum + group.cents, 0);
  const rows = groups.map((group) => [group.key, String(group.count), formatCents(group.cents)]);
  rows.push(["Total", String(expenses.length), formatCents(total)]);
  return renderTable([by === "month" ? "Month" : "Category", "Count", "Total"], rows);
}

/** The n largest expenses, biggest first; ties keep ledger order. */
export function largest(expenses: Expense[], n: number): Expense[] {
  return expenses
    .map((expense, index) => ({ expense, index }))
    .sort((a, b) => b.expense.cents - a.expense.cents || a.index - b.index)
    .slice(0, n)
    .map((entry) => entry.expense);
}

/** One line per expense for the top command: rank, date, category, description, amount. */
export function renderTop(expenses: Expense[]): string {
  const catWidth = Math.max(0, ...expenses.map((e) => e.category.length));
  const amounts = expenses.map((e) => formatCents(e.cents));
  const amountWidth = Math.max(0, ...amounts.map((a) => a.length));
  return expenses
    .map(
      (e, i) =>
        `${padLeft(String(i + 1), 2)}. ${e.date}  ${padRight(e.category, catWidth)}  ` +
        `${padLeft(amounts[i] ?? "", amountWidth)}  ${e.description}`,
    )
    .join("\n");
}

/** Distinct categories with their expense counts, alphabetical. */
export function renderCategories(expenses: Expense[]): string {
  return groupExpenses(expenses, "category")
    .map((group) => `${group.key} (${group.count})`)
    .join("\n");
}
