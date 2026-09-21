import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


# ---------------------------------------------------------------------------
# Optional DB persistence  injected by main.py after init_db()
# ---------------------------------------------------------------------------

_db_pool: Optional["asyncpg.Pool"] = None


def set_db_pool(pool: "asyncpg.Pool") -> None:
    """Called once by main.py after the DB pool is ready."""
    global _db_pool
    _db_pool = pool


async def _persist_log_event(entry: dict) -> None:
    """Fire-and-forget insert of a log entry into the log_events table."""
    if _db_pool is None:
        return
    try:
        import json as _json
        extra_keys = {k: v for k, v in entry.items()
                      if k not in ("timestamp", "level", "event", "database", "message", "error")}
        async with _db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO log_events (timestamp, level, event, database_name, message, error, extra)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                """,
                datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")
                ),
                entry.get("level", "INFO"),
                entry.get("event", ""),
                entry.get("database"),
                entry.get("message"),
                entry.get("error"),
                _json.dumps(extra_keys),
            )
    except Exception:
        pass  # never let DB persistence break the primary log path


# ---------------------------------------------------------------------------
# Log broadcast  used by GET /logs/stream (SSE)
# ---------------------------------------------------------------------------

class LogBroadcaster:
    """
    Singleton that fans out every structured log entry to all active SSE
    connections.  Each SSE handler calls subscribe() to get its own Queue,
    and unsubscribe() when the client disconnects.

    The queue is bounded (maxsize=1000) so a slow/stalled client cannot
    grow memory unboundedly.  When full, the oldest entry is dropped
    (put_nowait inside try/except QueueFull).
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def publish(self, entry: dict) -> None:
        """Fan out to all subscribers, dropping when a queue is full."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass  # slow client  drop oldest would require get() first; just skip


log_broadcaster = LogBroadcaster()


class StructuredLogger:
    """
    Shared structured JSON logger. Writes one JSON object per line to stdout.
    All modules import the singleton `log` instance at the bottom of this file.

    Usage:
        from app.logger import log
        log.info("backup_completed", "Backup written to S3", database="primary_postgres")
        ....
    """

    def _emit(
        self,
        level: str,
        event: str,
        message: str,
        database: Optional[str] = None,
        error: Optional[str] = None,
        **extra,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": level,
            "database": database,
            "event": event,
            "message": message,
            "error": error,
        }
        entry.update(extra)
        print(json.dumps(entry), file=sys.stdout, flush=True)
        log_broadcaster.publish(entry)
        # Persist to DB asynchronously (fire-and-forget, never blocks)
        if _db_pool is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_persist_log_event(entry))
            except RuntimeError:
                pass  # no running loop during early startup  skip DB write

    def info(
        self,
        event: str,
        message: str,
        database: Optional[str] = None,
        **extra,
    ) -> None:
        self._emit("INFO", event, message, database=database, **extra)

    def warning(
        self,
        event: str,
        message: str,
        database: Optional[str] = None,
        **extra,
    ) -> None:
        self._emit("WARNING", event, message, database=database, **extra)

    def error(
        self,
        event: str,
        message: str,
        database: Optional[str] = None,
        error: Optional[str] = None,
        **extra,
    ) -> None:
        self._emit("ERROR", event, message, database=database, error=error, **extra)


# Singleton  import this everywhere
log = StructuredLogger()
