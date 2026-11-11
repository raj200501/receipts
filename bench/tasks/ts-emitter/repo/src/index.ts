/** The public interface of dashboard-events. */

export { Emitter } from "./emitter.ts";
export { EmitError } from "./errors.ts";
export { DASHBOARD_EVENTS, createDashboardBus } from "./events.ts";
export type { DashboardEvents } from "./events.ts";
export { forward } from "./forward.ts";
export type { EventMap, Listener, Unsubscribe } from "./types.ts";
export { WaitTimeoutError, waitFor } from "./wait.ts";
