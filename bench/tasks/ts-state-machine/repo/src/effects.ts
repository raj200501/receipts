/** Plain-language descriptions of the side effects an event triggers. */

const DESCRIPTIONS: Readonly<Record<string, string>> = {
  "email:receipt": "send the payment receipt",
  "email:cancelled": "send the cancellation notice",
  "email:shipped": "send the shipping notice with the tracking link",
  "email:delivered": "send the delivery confirmation",
  "email:return-approved": "send the return approval",
  "email:refund": "send the refund confirmation",
  "warehouse:pick": "ask the warehouse to pick the order",
  "warehouse:pack": "ask the warehouse to pack the order",
  "warehouse:release": "release the reserved stock",
  "carrier:book": "book a pickup with the carrier",
  "carrier:return-label": "create a prepaid return label",
  "payments:refund": "refund the customer's payment",
};

/** What an effect does, in words; an unknown effect is described by its name. */
export function describeEffect(name: string): string {
  return DESCRIPTIONS[name] ?? name;
}
