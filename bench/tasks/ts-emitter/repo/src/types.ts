/** Types shared by the event bus and its helpers. */

/** Event names and the type of their payloads, for example ``{ "layout:saved": { layoutId: string } }``. */
export type EventMap = Record<string, unknown>;

/** A function called with the payload of an event. */
export type Listener<Payload> = (payload: Payload) => void;

/** Removes the registration it was returned for; calling it again does nothing. */
export type Unsubscribe = () => void;
