# Discount rules

This is the discount policy that the stockroom code implements. It belongs to the
finance systems team; questions and change requests go to them.

## Which discounts exist

An order can get up to three discounts, always considered in this order:

1. **volume**: for each order line separately, a line of 10 to 24 units gets 5 percent
   off that line's value, and a line of 25 units or more gets 10 percent off. The volume
   discount of an order is the sum over its lines.
2. **coupon**: one optional coupon code on the order.
   - `SPRING10`: 10 percent off, valid up to and including 2026-12-31.
   - `WELCOME5`: 5.00 off (a flat 500 cents), valid up to and including 2027-03-31.

   A coupon only applies when the value that is left after the volume discount reaches
   its minimum: 50.00 for `SPRING10` and 20.00 for `WELCOME5`. Below the minimum the
   coupon is accepted but gives nothing. A flat coupon never takes more than what is
   left.
3. **loyalty**: the customer's tier, if the order names one: `silver` is 3 percent off,
   `gold` is 5 percent off.

## How they combine

The discounts are applied one after the other, in the order above. The coupon and the
loyalty percentage are each taken from the value that is left after the discounts
before them, not from the original subtotal. A discount that comes to zero is left off
the receipt.

## Rounding

Every percentage discount is rounded half up to a whole cent on its own, using the value
it is taken from.
