import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg


# ---------------------------------------------------------------------------
# Job status constants
# ---------------------------------------------------------------------------

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

JOB_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# JobStore  PostgreSQL-backed (falls back to in-memory when no pool given)
# ---------------------------------------------------------------------------

class JobStore:
    """
    Tracks async backup jobs keyed by UUID job ID.

    - pool provided  → persisted to PostgreSQL; survives container restarts.
    - pool = None    → in-memory fallback (backward-compatible; lost on restart).

    All methods are async regardless of backend so callers are consistent.
    """

    def __init__(self, pool: Optional[asyncpg.Pool] = None) -> None:
        self._pool = pool
        self._memory: dict[str, dict] = {}  # used only when pool is None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, database: str, triggered_by: str = "manual") -> str:
        """Create a new job for `database`, persist if pool available, return job_id."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        if self._pool:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO backup_jobs
                        (job_id, database_name, status, triggered_by, queued_at)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    job_id, database, STATUS_QUEUED, triggered_by, now,
                )
        else:
            self._memory[job_id] = {
                "job_id": job_id,
                "database": database,
                "status": STATUS_QUEUED,
                "triggered_by": triggered_by,
                "queued_at": now.isoformat().replace("+00:00", "Z"),
                "started_at": None,
                "completed_at": None,
                "backup_filename": None,
                "error_message": None,
            }
        return job_id

    async def update(self, job_id: str, **fields) -> None:
        """Update one or more fields on an existing job."""
        if not fields:
            return

        if self._pool:
            _COLUMN_MAP = {
                "status": "status",
                "triggered_by": "triggered_by",
                "started_at": "started_at",
                "completed_at": "completed_at",
                "backup_filename": "backup_filename",
                "storage_backend": "storage_backend",
                "size_bytes": "size_bytes",
                "error_message": "error_message",
                "metadata": "metadata",
            }
            set_clauses = []
            values: list = []
            i = 1
            for key, val in fields.items():
                col = _COLUMN_MAP.get(key)
                if col is None:
                    continue
                # Parse ISO strings → datetime objects for TIMESTAMPTZ columns
                if col in ("started_at", "completed_at") and isinstance(val, str):
                    val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                # JSONB columns need serialised strings
                if col == "metadata" and isinstance(val, dict):
                    import json as _json
                    set_clauses.append(f"{col} = ${i}::jsonb")
                    values.append(_json.dumps(val))
                    i += 1
                    continue
                set_clauses.append(f"{col} = ${i}")
                values.append(val)
                i += 1
            if not set_clauses:
                return
            query = f"UPDATE backup_jobs SET {', '.join(set_clauses)} WHERE job_id = ${i}"
            values.append(job_id)
            async with self._pool.acquire() as conn:
                await conn.execute(query, *values)
        else:
            if job_id in self._memory:
                self._memory[job_id].update(fields)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(self, job_id: str) -> Optional[dict]:
        """Return the job dict or None if not found / purged."""
        if self._pool:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM backup_jobs WHERE job_id = $1", job_id)
            return _row_to_dict(row) if row else None
        return self._memory.get(job_id)

    async def list_for_database(self, database: str) -> list[dict]:
        """Return all jobs for a given database name, newest first."""
        if self._pool:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM backup_jobs WHERE database_name = $1 ORDER BY queued_at DESC",
                    database,
                )
            return [_row_to_dict(r) for r in rows]
        return [j for j in self._memory.values() if j["database"] == database]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def purge_old(self) -> int:
        """Remove jobs older than JOB_TTL_HOURS. Returns the number deleted."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=JOB_TTL_HOURS)
        if self._pool:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM backup_jobs WHERE queued_at < $1", cutoff
                )
            # asyncpg returns "DELETE N"
            return int(result.split()[-1])
        else:
            to_delete = [
                job_id for job_id, job in self._memory.items()
                if _parse_iso(job["queued_at"]) < cutoff
            ]
            for job_id in to_delete:
                del self._memory[job_id]
            return len(to_delete)


# ---------------------------------------------------------------------------
# JobQueue  per-database asyncio queues (always in-memory; by design)
# ---------------------------------------------------------------------------

class JobQueue:
    """
    Holds one asyncio.Queue per database name.
    Ensures concurrent backup requests for the same database are serialized.
    Different databases always run concurrently.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}

    def get(self, database: str) -> asyncio.Queue:
        """Return the queue for `database`, creating it on first access."""
        if database not in self._queues:
            self._queues[database] = asyncio.Queue()
        return self._queues[database]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: asyncpg.Record) -> dict:
    """Convert an asyncpg Record to a plain dict with ISO-string timestamps."""
    d = dict(row)
    # Rename database_name → database to match the external API shape
    d["database"] = d.pop("database_name")
    # Convert datetime objects → ISO strings
    for key in ("queued_at", "started_at", "completed_at"):
        val = d.get(key)
        if val is not None and hasattr(val, "isoformat"):
            d[key] = val.isoformat().replace("+00:00", "Z")
    # metadata is returned as a dict by asyncpg  keep as-is
    return d


def _parse_iso(s: Optional[str]) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
