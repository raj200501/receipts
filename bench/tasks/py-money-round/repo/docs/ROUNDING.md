# Rounding policy for invoices

This is the rounding policy that every billing tool implements. It is owned by the
finance team: send questions and change requests to finance-ops, and do not change this
file without their approval.

## Amounts

- Invoice amounts are euros with two decimal places. Quantities, unit prices, and VAT
  rates may have more decimal places than that.
- Amounts are calculated with exact decimal arithmetic. Binary floating point is never
  used for money, because it cannot hold most cent amounts exactly.
- To round an amount means to round it to the nearest cent. An amount exactly halfway
  between two cents goes to the even cent (round half to even): 2.125 becomes 2.12,
  2.135 becomes 2.14, and 0.525 becomes 0.52.

## Lines

The amount of a line is its quantity times its unit price, rounded. A credit line has a
negative quantity and so a negative amount. The subtotal of an invoice is the sum of its
line amounts.

## VAT

VAT is calculated once for each VAT rate on an invoice: add up the amounts of the lines
that have that rate, multiply the sum by the rate, and round. VAT is never calculated or
rounded line by line. The invoice shows one VAT line for each rate, from the lowest rate
to the highest.

## Total

The total of an invoice is its subtotal plus its VAT lines. It adds amounts that are
already rounded and is never rounded again.
