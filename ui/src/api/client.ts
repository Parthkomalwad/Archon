// ---------------------------------------------------------------------------
// Archon API Client
// All calls include X-API-Key from VITE_API_KEY env var.
// ---------------------------------------------------------------------------

const API_KEY = import.meta.env.VITE_API_KEY as string;
const BASE = "/api"; // proxied to http://archon:8765 in production via nginx

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
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

// ---------------------------------------------------------------------------
// Types (mirrors Pydantic models)
// ---------------------------------------------------------------------------

export interface JobRef {
  job_id: string;
  database: string;
  status: string;
}

export interface BackupResponse {
  jobs: JobRef[];
}

export interface Job {
  job_id: string;
  database: string;
  status: string;
  triggered_by: string | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  backup_filename: string | null;
  error_message: string | null;
}

export interface Backup {
  filename: string;
  database: string;
  timestamp: string;
  size_bytes: number;
  rotation_type: string;
  storage_backend: string;
  encrypted: boolean;
  file_exists: boolean;
  triggered_by: string;
  sidecar_exists: boolean;
}

export interface BackupsResponse {
  backups: Backup[];
}

export interface DatabaseStatus {
  database: string;
  last_run_time: string | null;
  next_scheduled_run: string | null;
  last_status: string | null;
  currently_running: boolean;
}

export interface StatusResponse {
  databases: DatabaseStatus[];
}

export interface ReloadResponse {
  status: string;
  databases_registered: number;
  errors: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
}

export interface RestoreResponse {
  status: string;
  filename: string;
  database: string;
  strategy: string | null;
}


export interface LogEntry {
  timestamp: string;
  level: string;
  event: string;
  database: string | null;
  message: string;
  error: string | null;
  [key: string]: unknown;
}

export interface LogsResponse {
  entries: LogEntry[];
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export function triggerBackup(database?: string): Promise<BackupResponse> {
  const body = database ? { database, triggered_by: "manual" } : { triggered_by: "manual" };
  return request<BackupResponse>("/backup", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getJob(jobId: string): Promise<Job> {
  return request<Job>(`/jobs/${jobId}`);
}

export function triggerRestore(filename: string): Promise<RestoreResponse> {
  return request<RestoreResponse>("/restore", {
    method: "POST",
    body: JSON.stringify({ filename, confirm: true }),
  });
}

export function getBackups(database?: string): Promise<BackupsResponse> {
  const qs = database ? `?database=${encodeURIComponent(database)}` : "";
  return request<BackupsResponse>(`/backups${qs}`);
}

export function getStatus(): Promise<StatusResponse> {
  return request<StatusResponse>("/status");
}

export function deleteBackup(filename: string): Promise<{ deleted: string }> {
  return request<{ deleted: string }>(`/backups/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export function reloadConfig(): Promise<ReloadResponse> {
  return request<ReloadResponse>("/reload", { method: "POST" });
}

export function getHealth(): Promise<HealthResponse> {
  // /health has no auth requirement
  return fetch("/api/health").then((r) => r.json() as Promise<HealthResponse>);
}

/**
 * Fetch recent historical log entries from the log_events table.
 */
export function getLogs(limit = 200, level?: string): Promise<LogsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (level) params.set("level", level);
  return request<LogsResponse>(`/logs?${params.toString()}`);
}

export function streamLogs(level?: string): EventSource {
  const params = new URLSearchParams({ api_key: API_KEY });
  if (level) params.set("level", level);
  return new EventSource(`/api/logs/stream?${params.toString()}`);
}

