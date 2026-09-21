// ---------------------------------------------------------------------------
// Granular restore API client
// Mirrors app/api/granular_routes.py Pydantic models exactly.
// ---------------------------------------------------------------------------

const API_KEY = import.meta.env.VITE_API_KEY as string;
const BASE = "/api";

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TableSummary {
  name: string;
  row_count: number;
  columns: string[];
  fk_count: number;
}

export interface CreateSessionResponse {
  session_id: string;
  db_name: string;
  db_type: string;
  tables: TableSummary[];
}

export interface RowsResponse {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
}

export interface FKDep {
  table: string;
  row_count: number;
  rows: Record<string, unknown>[];
}

export interface ResolveResponse {
  total_rows: number;
  dependencies: FKDep[];
}

export interface GranularRestoreResponse {
  status: string;
  rows_applied: number;
  tables_affected: string[];
}

export type ConflictStrategy = "skip" | "replace" | "merge";

// ─── API functions ────────────────────────────────────────────────────────────

/** Parse a backup file into an in-memory session. */
export function createGranularSession(filename: string): Promise<CreateSessionResponse> {
  return req("/granular/session", {
    method: "POST",
    body: JSON.stringify({ filename }),
  });
}

/** List all tables in a session. */
export function listTables(sessionId: string): Promise<TableSummary[]> {
  return req(`/granular/session/${sessionId}/tables`);
}

/** Get paginated, optionally-filtered rows from a table. */
export function getRows(
  sessionId: string,
  table: string,
  opts: {
    filterCol?: string;
    filterVal?: string;
    page?: number;
    pageSize?: number;
  } = {}
): Promise<RowsResponse> {
  const params = new URLSearchParams();
  if (opts.filterCol) params.set("filter_col", opts.filterCol);
  if (opts.filterVal !== undefined) params.set("filter_val", opts.filterVal);
  if (opts.page) params.set("page", String(opts.page));
  if (opts.pageSize) params.set("page_size", String(opts.pageSize));
  const qs = params.toString() ? `?${params}` : "";
  return req(`/granular/session/${sessionId}/table/${encodeURIComponent(table)}/rows${qs}`);
}

/** Walk the FK graph from selected rows and return all dependent rows. */
export function resolveDependencies(
  sessionId: string,
  table: string,
  rowIndices: number[]
): Promise<ResolveResponse> {
  return req(`/granular/session/${sessionId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ table, row_indices: rowIndices }),
  });
}

/** Apply the selected rows to the live database. */
export function applyGranularRestore(
  sessionId: string,
  table: string,
  rowIndices: number[],
  strategy: ConflictStrategy
): Promise<GranularRestoreResponse> {
  return req(`/granular/session/${sessionId}/restore`, {
    method: "POST",
    body: JSON.stringify({
      table,
      row_indices: rowIndices,
      strategy,
      confirm: true,
    }),
  });
}

/** Walk the FK graph for multiple tables at once and return merged, deduplicated deps. */
export interface MultiTableEntry {
  table: string;
  row_indices: number[];
}

export function resolveMultiDependencies(
  sessionId: string,
  tables: MultiTableEntry[]
): Promise<ResolveResponse> {
  return req(`/granular/session/${sessionId}/resolve-multi`, {
    method: "POST",
    body: JSON.stringify({ tables }),
  });
}

/** Apply rows from multiple tables in one operation. */
export function applyMultiGranularRestore(
  sessionId: string,
  tables: MultiTableEntry[],
  strategy: ConflictStrategy
): Promise<GranularRestoreResponse> {
  return req(`/granular/session/${sessionId}/restore-multi`, {
    method: "POST",
    body: JSON.stringify({ tables, strategy, confirm: true }),
  });
}

/** Clean up a session manually. */
export function deleteGranularSession(sessionId: string): Promise<{ deleted: string }> {
  return req(`/granular/session/${sessionId}`, { method: "DELETE" });
}
