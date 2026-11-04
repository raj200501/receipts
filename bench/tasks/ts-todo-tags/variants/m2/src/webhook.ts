/** Post reminders for items that are due to the team chat. */

import type { Todo } from "./types.ts";

/** The chat webhook for reminders; it is reachable from the office network only. */
export const REMINDER_URL = "https://chat.todo.internal/hooks/reminders";

/** The message for one item that is due. */
export function reminderText(todo: Todo): string {
  const due = todo.due === null ? "no due day" : `due ${todo.due}`;
  return `Reminder: #${todo.id} ${todo.title} (${due})`;
}

/** Post a reminder to the team chat and resolve with the HTTP status. */
export async function postReminder(todo: Todo, url: string = REMINDER_URL): Promise<number> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text: reminderText(todo) }),
    signal: AbortSignal.timeout(5000),
  });
  return response.status;
}
