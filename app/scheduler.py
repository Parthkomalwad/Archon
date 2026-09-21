import asyncio
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import AppConfig, DatabaseConfig
from app.encryption import EncryptionService
from app.jobs import (
    JobStore,
    JobQueue,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from app.logger import log
from app.providers import get_provider
from app.retention import RetentionManager
from app.schedule_parser import ScheduleParser
from app.semaphore import JobSemaphore
from app.storage import get_storage
from app.storage.base import BaseStorage
from app.webhook import WebhookPayload, WebhookService

ARCHON_VERSION = "2.0.0"
RAVEN_VERSION = ARCHON_VERSION  # backward compat alias  -.- --- --


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DB_EXTENSIONS: dict[str, str] = {
    "postgres": "sql",
    "mongodb": "archive",
    "sqlite": "db",
    "mysql": "sql",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rotation_type(frequency: str, tz: str) -> str:
    """
    Determine the rotation_type label for a backup based on schedule frequency
    and the current calendar date.

    For daily-frequency databases the calendar determines the label so that a
    single scheduled run can serve as the weekly or monthly backup:
        monthly (1st of month)  >  weekly (Sunday)  >  daily

    This is how the overlap rule ("Sunday on the 1st is kept under the monthly
    window, not the weekly window") is implemented  the file is tagged
    'monthly', so it is never counted against the weekly limit.
    """
    if frequency in ("hourly", "weekly", "monthly"):
        return frequency

    # daily  classify by current date
    now = datetime.now(pytz.timezone(tz))
    if now.day == 1:
        return "monthly"
    if now.weekday() == 6:  # Sunday
        return "weekly"
    return "daily"


def _build_filename(db_name: str, rotation: str, db_type: str, enc_ext: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    ext = _DB_EXTENSIONS.get(db_type, "bak")
    return f"archon_{db_name}_{ts}_{rotation}.{ext}{enc_ext}"


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Wraps APScheduler's AsyncIOScheduler with the full Archon backup pipeline.

    Responsibilities:
    - Register a timezone-aware cron job per database on startup.
    - When a cron fires (or POST /backup is called), enqueue a backup task on
      the per-database asyncio.Queue so concurrent requests are serialized.
    - Execute the full pipeline: backup → encrypt → checksum → store → retain.
    - Expose reload() so POST /reload can swap the config live.
    """

    def __init__(
        self,
        config: AppConfig,
        job_store: JobStore,
        job_queue: JobQueue,
        semaphore: JobSemaphore,
        webhook_service: WebhookService,
        pool=None,
    ) -> None:
        self._config = config
        self._job_store = job_store
        self._job_queue = job_queue
        self._semaphore = semaphore
        self._webhook_service = webhook_service
        self._pool = pool  # asyncpg pool for schema snapshot persistence (optional)
        self._aps = AsyncIOScheduler()
        self._enc = EncryptionService(config.encryption)
        self._retention = RetentionManager()
        self._storage_cache: dict[str, BaseStorage] = {}
        self._workers: list[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Storage cache
    # ------------------------------------------------------------------

    def _get_storage(self, backend_name: str) -> BaseStorage:
        if backend_name not in self._storage_cache:
            cfg = self._config.storage_backends[backend_name]
            self._storage_cache[backend_name] = get_storage(cfg)
        return self._storage_cache[backend_name]

    # ------------------------------------------------------------------
    # Start / shutdown
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register all cron jobs, start APScheduler, and launch queue workers."""
        for db in self._config.databases:
            self._register_cron(db)
            self._workers.append(
                asyncio.create_task(
                    self._queue_worker(db.name),
                    name=f"archon_worker_{db.name}",
                )
            )
        self._aps.start()
        log.info("startup_ok", f"Scheduler started with {len(self._config.databases)} job(s)")

    def shutdown(self) -> None:
        """Stop APScheduler and cancel all queue workers."""
        self._aps.shutdown(wait=False)
        for task in self._workers:
            task.cancel()
        self._workers.clear()

    # ------------------------------------------------------------------
    # Reload (POST /reload)
    # ------------------------------------------------------------------

    def reload(self, new_config: AppConfig) -> None:
        """
        Cancel existing cron jobs and re-register from new_config.
        Queue workers keep running; any new databases get their own worker.
        """
        self._aps.remove_all_jobs()
        existing_dbs = {db.name for db in self._config.databases}
        self._config = new_config
        self._enc = EncryptionService(new_config.encryption)
        self._storage_cache.clear()

        for db in new_config.databases:
            self._register_cron(db)
            if db.name not in existing_dbs:
                self._workers.append(
                    asyncio.create_task(
                        self._queue_worker(db.name),
                        name=f"archon_worker_{db.name}",
                    )
                )

    # ------------------------------------------------------------------
    # Cron registration
    # ------------------------------------------------------------------

    def _register_cron(self, db: DatabaseConfig) -> None:
        cron_expr = ScheduleParser.parse(db.schedule)
        trigger = CronTrigger.from_crontab(cron_expr, timezone=db.schedule.timezone)
        self._aps.add_job(
            self._on_cron_fire,
            trigger=trigger,
            args=[db],
            id=f"backup_{db.name}",
            replace_existing=True,
        )

    # ------------------------------------------------------------------
    # Cron trigger → enqueue
    # ------------------------------------------------------------------

    async def _on_cron_fire(self, db: DatabaseConfig) -> None:
        freq = db.schedule.frequency or "daily"
        rotation = _rotation_type(freq, db.schedule.timezone)
        job_id = await self._job_store.create(db.name, triggered_by="scheduler")
        log.info("backup_queued", "Scheduled backup queued", database=db.name)
        await self._job_queue.get(db.name).put((job_id, rotation, db, "scheduler"))

    # ------------------------------------------------------------------
    # Public API (used by POST /backup)
    # ------------------------------------------------------------------

    async def enqueue(self, db: DatabaseConfig, triggered_by: str = "manual") -> str:
        """
        Enqueue a backup for `db` (called by POST /backup).
        Returns the job_id immediately; caller polls GET /jobs/{job_id}.
        """
        freq = db.schedule.frequency or "daily"
        rotation = _rotation_type(freq, db.schedule.timezone)
        job_id = await self._job_store.create(db.name, triggered_by=triggered_by)
        log.info("backup_queued", "API backup queued", database=db.name)
        await self._job_queue.get(db.name).put((job_id, rotation, db, triggered_by))
        return job_id

    # ------------------------------------------------------------------
    # Per-database queue worker
    # ------------------------------------------------------------------

    async def _queue_worker(self, db_name: str) -> None:
        """
        Long-running coroutine that pops one job at a time off the
        per-database queue and executes it sequentially.
        The global semaphore is acquired after dequeue so that the per-database
        serialisation and the global concurrency cap are both enforced.
        """
        queue = self._job_queue.get(db_name)
        while True:
            job_id, rotation, db, triggered_by = await queue.get()
            try:
                await self._semaphore.acquire(database=db_name)
                try:
                    await self._execute_backup(db, job_id, rotation, triggered_by)
                finally:
                    await self._semaphore.release()
            finally:
                queue.task_done()

    # ------------------------------------------------------------------
    # Full backup pipeline
    # ------------------------------------------------------------------

    async def _execute_backup(
        self,
        db: DatabaseConfig,
        job_id: str,
        rotation: str,
        triggered_by: str = "manual",
    ) -> None:
        """
        Pipeline order (per CLAUDE.md architectural rule #5):
            provider.backup()
            → encrypt()
            → compute_checksum()
            → storage.write(file)
            → storage.write(file.sha256)
            → storage.write(file.meta)
            → retention.enforce()
        """
        loop = asyncio.get_running_loop()
        start_time = time.monotonic()

        await self._job_store.update(
            job_id,
            status=STATUS_RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        tmpdir = tempfile.mkdtemp(prefix="archon_")
        tmp_raw = Path(tmpdir) / "backup.raw"
        tmp_enc = Path(tmpdir) / "backup.enc"

        try:
            log.info("backup_started", "Backup pipeline started", database=db.name)

            # Step 1: Run DB provider (blocking subprocess  write raw backup to disk)
            provider = get_provider(db)
            await loop.run_in_executor(None, provider.backup, str(tmp_raw))

            # Step 2: Stream-encrypt raw → enc (disk-to-disk, constant RAM footprint)
            await loop.run_in_executor(None, self._enc.encrypt_stream, tmp_raw, tmp_enc)

            # Step 3: Compute SHA-256 checksum of encrypted file (streamed, no full load)
            checksum_hex = await loop.run_in_executor(
                None, EncryptionService.compute_checksum_stream, tmp_enc
            )

            # Step 4: Build filename
            enc_ext = self._enc.get_extension()
            filename = _build_filename(db.name, rotation, db.type, enc_ext)

            # Step 5: Stream-upload encrypted file to storage backend
            storage = self._get_storage(db.storage)
            await loop.run_in_executor(None, storage.write_stream, filename, tmp_enc)

            # Step 6: Write .sha256 sidecar
            storage.write(f"{filename}.sha256", checksum_hex.encode())

            # Step 7: Write .meta sidecar (triggered_by, version, timestamp)
            meta = {
                "triggered_by": triggered_by,
                "archon_version": RAVEN_VERSION,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            storage.write(f"{filename}.meta", json.dumps(meta).encode())

            # Step 8: Enforce retention
            retention_cfg = db.retention if db.retention else self._config.retention
            self._retention.enforce(db.name, storage, retention_cfg)

            # Step 10: Mark job completed
            await self._job_store.update(
                job_id,
                status=STATUS_COMPLETED,
                backup_filename=filename,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            log.info(
                "backup_completed",
                f"Backup complete: {filename}",
                database=db.name,
                filename=filename,
            )
            await self._webhook_service.fire(
                "backup_completed",
                WebhookPayload(
                    event="backup_completed",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    database=db.name,
                    job_id=job_id,
                    triggered_by=triggered_by,
                    backup_filename=filename,
                    duration_seconds=round(time.monotonic() - start_time, 2),
                ),
            )

        except Exception as e:
            log.error(
                "backup_failed",
                f"Backup pipeline failed: {e}",
                database=db.name,
                error=str(e),
            )
            await self._job_store.update(
                job_id,
                status=STATUS_FAILED,
                error_message=str(e),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._webhook_service.fire(
                "backup_failed",
                WebhookPayload(
                    event="backup_failed",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    database=db.name,
                    job_id=job_id,
                    triggered_by=triggered_by,
                    error_message=str(e),
                    duration_seconds=round(time.monotonic() - start_time, 2),
                ),
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
