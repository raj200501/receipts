/** Shared types for the pagination helpers. */

/** Query parameters as a web framework hands them over: every value is a string. */
export type Query = Readonly<Record<string, string | undefined>>;

/** Options of `paginate`. */
export interface OffsetOptions {
  /** 1-based page number; 1 by default. */
  page?: number;
  /** Items per page; see `resolveSize` for the default and the limit. */
  perPage?: number;
}

/** One page of a list, as `paginate` returns it. */
export interface OffsetPage<T> {
  items: T[];
  page: number;
  perPage: number;
  /** Number of items in the whole list. */
  total: number;
  /** Number of pages; an empty list has one (empty) page. */
  totalPages: number;
  hasNext: boolean;
  hasPrev: boolean;
}

/** The page request that `parsePageParams` reads from a query. */
export interface PageParams {
  page: number;
  perPage: number;
}

/** Links to related pages; `prev` and `next` are null at the ends. */
export interface PageLinks {
  first: string;
  prev: string | null;
  next: string | null;
  last: string;
}
