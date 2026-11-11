/** Shared types for moneyfmt. */

/** An amount of money, held as a whole number of the currency's smallest unit. */
export interface Money {
  readonly minor: number;
  readonly currency: string;
}

/** Options of formatMoney. */
export interface FormatOptions {
  /** "symbol" gives $1,234.50; "code" gives 1,234.50 USD. The default is "symbol". */
  style?: "symbol" | "code";
  /** Group thousands with commas. The default is true. */
  grouping?: boolean;
}

/** Raised for amounts, currencies, and files that moneyfmt cannot read. */
export class MoneyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MoneyError";
  }
}
