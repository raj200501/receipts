/** The orderflow command line. */

import { describeEffect } from "./effects.ts";
import { formatHistory, summarize } from "./history.ts";
import { loadOrder, saveOrder } from "./store.ts";
import { EVENTS, TransitionError } from "./types.ts";
import type { EventType } from "./types.ts";
import { allowedEvents, applyEvent } from "./workflow.ts";

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = `usage: orderflow <command> <order.json> [options]

  show      <order.json>                      print a summary of the order
  events    <order.json>                      list the events the order can take
  history   <order.json>                      print the audit trail
  apply     <order.json> <event> [--at TIME] [--note TEXT] [--write]
                                              apply an event and print what it triggers
`;

function option(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  if (index === -1) {
    return undefined;
  }
  const value = args[index + 1];
  if (value === undefined) {
    throw new TransitionError(`${name} needs a value`);
  }
  args.splice(index, 2);
  return value;
}

function flag(args: string[], name: string): boolean {
  const index = args.indexOf(name);
  if (index === -1) {
    return false;
  }
  args.splice(index, 1);
  return true;
}

/** Run the command line; returns the exit status (0, or 2 for any problem). */
export function run(argv: readonly string[], io: Io): number {
  const [command, ...rest] = argv;
  try {
    if (command === "show" || command === "events" || command === "history") {
      const [file, ...extra] = rest;
      if (file === undefined || extra.length > 0) {
        throw new TransitionError(`${command} needs one order file`);
      }
      const order = loadOrder(file);
      if (command === "show") {
        io.out(summarize(order));
      } else if (command === "history") {
        io.out(formatHistory(order.history));
      } else {
        const events = allowedEvents(order.state);
        io.out(events.length === 0 ? "none\n" : `${events.join("\n")}\n`);
      }
      return 0;
    }
    if (command === "apply") {
      const args = [...rest];
      const at = option(args, "--at") ?? new Date().toISOString();
      const note = option(args, "--note");
      const write = flag(args, "--write");
      const [file, type, ...extra] = args;
      if (file === undefined || type === undefined || extra.length > 0) {
        throw new TransitionError("apply needs an order file and an event");
      }
      const event = EVENTS.find((candidate): candidate is EventType => candidate === type);
      if (event === undefined) {
        throw new TransitionError(`unknown event ${JSON.stringify(type)}`);
      }
      const order = loadOrder(file);
      const applied = applyEvent(order, note === undefined ? { type: event } : { type: event, note }, at);
      const lines = [`${order.state} -> ${applied.order.state}`];
      for (const effect of applied.effects) {
        lines.push(`  ${effect}: ${describeEffect(effect)}`);
      }
      io.out(`${lines.join("\n")}\n`);
      if (write) {
        saveOrder(file, applied.order);
      }
      return 0;
    }
    io.err(USAGE);
    return 2;
  } catch (error) {
    if (error instanceof TransitionError) {
      io.err(`orderflow: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
