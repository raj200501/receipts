# Order workflow

This is the workflow the orderflow tool implements. It is owned by the fulfilment
operations team; questions about it go to them.

## States

An order is in exactly one of these states: `created`, `paid`, `packed`, `shipped`,
`delivered`, `returned`, `cancelled`, `refunded`. A new order starts as `created`.

## Transitions

| From | Event | To |
| --- | --- | --- |
| created | pay | paid |
| created | cancel | cancelled |
| paid | pack | packed |
| paid | cancel | cancelled |
| packed | ship | shipped |
| packed | cancel | cancelled |
| shipped | deliver | delivered |
| delivered | return | returned |
| returned | refund | refunded |
| cancelled | refund | refunded |

Any other combination of state and event is refused. `refunded` is the end of the
workflow: no event applies to a refunded order.

## Rules

- `pay` needs an order total above zero. The customer's payment is recorded as the order
  total.
- `ship` needs a shipping address.
- `return` is accepted up to 30 days after delivery.
- `refund` needs something to refund: an order that was cancelled before it was paid
  cannot be refunded.
- `cancel` is possible from `created`, `paid`, and `packed`. Cancelling a paid or packed
  order releases the stock that was reserved for it.
