import type { Item } from "./types.ts";

/** Raised by {@link InventoryStore.adjust} when the sku is not stocked. */
export class UnknownSkuError extends Error {
  readonly sku: string;

  constructor(sku: string) {
    super(`unknown sku ${sku}`);
    this.name = "UnknownSkuError";
    this.sku = sku;
  }
}

/** The in-memory item table. Items are copied on the way in and out. */
export class InventoryStore {
  readonly #items = new Map<string, Item>();

  constructor(initial: Item[] = []) {
    for (const item of initial) {
      this.#items.set(item.sku, { ...item });
    }
  }

  /** Every item, ordered by sku. */
  list(): Item[] {
    return [...this.#items.values()]
      .sort((a, b) => (a.sku < b.sku ? -1 : a.sku > b.sku ? 1 : 0))
      .map((item) => ({ ...item }));
  }

  get(sku: string): Item | undefined {
    const item = this.#items.get(sku);
    return item === undefined ? undefined : { ...item };
  }

  has(sku: string): boolean {
    return this.#items.has(sku);
  }

  /** Insert or replace the item stored under its sku. */
  put(item: Item): Item {
    this.#items.set(item.sku, { ...item });
    return { ...item };
  }

  /** Remove an item; returns whether it was there. */
  delete(sku: string): boolean {
    return this.#items.delete(sku);
  }

  /** Add delta (which may be negative) to the quantity of a stocked item. */
  adjust(sku: string, delta: number): Item {
    const item = this.#items.get(sku);
    if (item === undefined) {
      throw new UnknownSkuError(sku);
    }
    item.quantity += delta;
    return { ...item };
  }

  get size(): number {
    return this.#items.size;
  }
}
