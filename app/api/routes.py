import asyncio
import json
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import AppConfig, ConfigError, ConfigLoader, DatabaseConfig
from app.encryption import EncryptionService
from app.logger import log, log_broadcaster
from app.providers import get_provider
from app.storage import get_storage
from app.webhook import WebhookPayload, WebhookService

router = APIRouter()


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

# Matches archon_ (current), raven_ and backops_ (migration window)
_FILENAME_RE = re.compile(
    r"^(?:archon|raven|backops)_(?P<db_name>.+)_(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})"
    r"_(?P<rotation>hourly|daily|weekly|monthly)\.(?P<ext>sql|archive|db)(?P<enc>\.enc)?$"
)


def _parse_filename(filename: str) -> Optional[dict]:
    """Parse backup filename into metadata dict, or None if not a valid backup filename."""
    m = _FILENAME_RE.match(filename)
    if not m:
        return None
    return {
        "db_name": m.group("db_name"),
        "timestamp": m.group("timestamp"),
        "rotation": m.group("rotation"),
        "ext": m.group("ext"),
        "encrypted": m.group("enc") is not None,
    }


def _find_db(config: AppConfig, db_name: str) -> Optional[DatabaseConfig]:
    """Find a DatabaseConfig by name, or None if not found."""
    for db in config.databases:
        if db.name == db_name:
            return db
    return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class BackupRequest(BaseModel):
    database: Optional[str] = None
    triggered_by: str = "manual"  # "manual" | "scheduler"


class JobRef(BaseModel):
    job_id: str
    database: str
    status: str


class BackupResponse(BaseModel):
    jobs: list[JobRef]


class JobResponse(BaseModel):
    job_id: str
    database: str
    status: str
    triggered_by: Optional[str] = None
    queued_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    backup_filename: Optional[str]
    error_message: Optional[str]


class RestoreRequest(BaseModel):
    filename: str
    confirm: bool = False
    target_database: Optional[str] = None


class RestoreResponse(BaseModel):
    status: str
    filename: str
    database: str
    strategy: Optional[str] = None  # "drop_recreate" | "shadow"


class BackupMeta(BaseModel):
    filename: str
    database: str
    timestamp: str
    size_bytes: int
    rotation_type: str
    storage_backend: str
    encrypted: bool
    file_exists: bool
    triggered_by: str = "unknown"      # "manual" | "scheduler" | "unknown" (missing .meta)
    sidecar_exists: bool = False       # True if the .sha256 sidecar is present


class BackupsResponse(BaseModel):
    backups: list[BackupMeta]


class DatabaseStatus(BaseModel):
    database: str
    last_run_time: Optional[str]
    next_scheduled_run: Optional[str]
    last_status: Optional[str]
    currently_running: bool


class StatusResponse(BaseModel):
    databases: list[DatabaseStatus]


class DeleteResponse(BaseModel):
    deleted: str


class ReloadResponse(BaseModel):
    status: str
    databases_registered: int
    errors: list[str]


# ---------------------------------------------------------------------------
# POST /backup
# ---------------------------------------------------------------------------

@router.post("/backup", status_code=202, response_model=BackupResponse)
async def post_backup(
    request: Request,
    body: Optional[BackupRequest] = Body(default=None),
) -> BackupResponse:
    """
    Enqueue a backup for one or all databases.
    Optional body: {"database": "name"}  omit to back up all databases.
    Returns 202 with job IDs immediately; poll GET /jobs/{job_id} for status.
    """
    config: AppConfig = request.app.state.config
    scheduler = request.app.state.scheduler
    job_store = request.app.state.job_store

    database_filter = body.database if body else None
    triggered_by = body.triggered_by if body else "manual"

    if database_filter:
        db = _find_db(config, database_filter)
        if db is None:
            raise HTTPException(
                status_code=404,
                detail=f"Database '{database_filter}' not found in config",
            )
        target_dbs = [db]
    else:
        target_dbs = list(config.databases)

    jobs: list[JobRef] = []
    for db in target_dbs:
        job_id = await scheduler.enqueue(db, triggered_by=triggered_by)
        job = await job_store.get(job_id)
        status = job["status"] if job else "queued"
        jobs.append(JobRef(job_id=job_id, database=db.name, status=status))

    return BackupResponse(jobs=jobs)


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request) -> JobResponse:
    """Return the current state of a backup job. Returns 404 if purged or unknown."""
    job_store = request.app.state.job_store
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found or has been purged (TTL: 24h)",
        )
    return JobResponse(**job)


# ---------------------------------------------------------------------------
# POST /restore
# ---------------------------------------------------------------------------

@router.post("/restore", response_model=RestoreResponse)
async def post_restore(
    body: RestoreRequest,
    request: Request,
) -> RestoreResponse:
    """
    Restore a database from a backup file.

    Pipeline (rule #6):
        storage.read(file) → storage.read(file.sha256) → verify_checksum()
        → decrypt() → provider.restore()

    Checksum verification occurs before decryption and before touching the DB.
    Missing .sha256 sidecar aborts immediately (404).
    Checksum mismatch aborts immediately (400).
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="'confirm: true' is required to execute a restore",
        )

    start_time = time.monotonic()
    config: AppConfig = request.app.state.config

    # Determine target database
    if body.target_database:
        db = _find_db(config, body.target_database)
        if db is None:
            raise HTTPException(
                status_code=404,
                detail=f"Database '{body.target_database}' not found in config",
            )
    else:
        parsed_fn = _parse_filename(body.filename)
        if parsed_fn is None:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot parse database name from filename '{body.filename}'",
            )
        db = _find_db(config, parsed_fn["db_name"])
        if db is None:
            raise HTTPException(
                status_code=404,
                detail=f"Database '{parsed_fn['db_name']}' (inferred from filename) not found in config",
            )

    storage = get_storage(config.storage_backends[db.storage])
    enc = EncryptionService(config.encryption)
    loop = asyncio.get_running_loop()

    log.info(
        "restore_started",
        f"Restore started: {body.filename}",
        database=db.name,
        filename=body.filename,
        restore_strategy=db.restore_strategy,
    )
    tmpdir = tempfile.mkdtemp(prefix="archon_restore_")
    tmp_enc = Path(tmpdir) / "restore.enc"
    tmp_raw = Path(tmpdir) / "restore.raw"

    try:
        # Step 1: Stream-download backup file to disk (no full-file RAM load)
        try:
            await loop.run_in_executor(None, storage.read_stream, body.filename, tmp_enc)
        except Exception:
            raise HTTPException(
                status_code=404,
                detail=f"Backup file '{body.filename}' not found in storage",
            )

        # Step 2: Read .sha256 sidecar  abort if missing (tiny file, in-memory fine)
        sidecar = f"{body.filename}.sha256"
        try:
            checksum_bytes = storage.read(sidecar)
        except Exception:
            raise HTTPException(
                status_code=404,
                detail=f"SHA-256 sidecar '{sidecar}' is missing  restore aborted",
            )
        expected_hex = checksum_bytes.decode().strip()

        # Step 3: Verify checksum via streaming (before decryption, before touching DB)
        actual_hex = await loop.run_in_executor(
            None, EncryptionService.compute_checksum_stream, tmp_enc
        )
        if actual_hex != expected_hex:
            log.error(
                "integrity_failed",
                f"SHA-256 mismatch for '{body.filename}'",
                database=db.name,
                filename=body.filename,
            )
            raise HTTPException(
                status_code=400,
                detail="Integrity check failed: SHA-256 checksum mismatch",
            )

        # Step 4: Stream-decrypt enc → raw (disk-to-disk, constant RAM footprint)
        try:
            await loop.run_in_executor(None, enc.decrypt_stream, tmp_enc, tmp_raw)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Decryption failed: {e}")

        # Step 5: Provider restore from decrypted temp file
        provider = get_provider(db)
        await loop.run_in_executor(None, provider.restore, str(tmp_raw), True)

        log.info(
            "restore_completed",
            f"Restore complete: {body.filename}",
            database=db.name,
            filename=body.filename,
            restore_strategy=db.restore_strategy,
        )
        webhook_service: WebhookService = request.app.state.webhook_service
        await webhook_service.fire(
            "restore_completed",
            WebhookPayload(
                event="restore_completed",
                timestamp=datetime.now(timezone.utc).isoformat(),
                database=db.name,
                backup_filename=body.filename,
                duration_seconds=round(time.monotonic() - start_time, 2),
            ),
        )
        return RestoreResponse(
            status="restored",
            filename=body.filename,
            database=db.name,
            strategy=db.restore_strategy,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "restore_failed",
            f"Restore failed: {e}",
            database=db.name,
            error=str(e),
        )
        webhook_service: WebhookService = request.app.state.webhook_service
        await webhook_service.fire(
            "restore_failed",
            WebhookPayload(
                event="restore_failed",
                timestamp=datetime.now(timezone.utc).isoformat(),
                database=db.name,
                backup_filename=body.filename,
                error_message=str(e),
                duration_seconds=round(time.monotonic() - start_time, 2),
            ),
        )
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# GET /backups
# ---------------------------------------------------------------------------

@router.get("/backups", response_model=BackupsResponse)
async def get_backups(
    request: Request,
    database: Optional[str] = Query(default=None),
) -> BackupsResponse:
    """
    List all backup files across all configured storage backends.
    Optional ?database=<name> filter narrows results to one database.
    """
    config: AppConfig = request.app.state.config

    # Deduplicate storage backends  multiple databases may share one backend
    seen_backends: set[str] = set()
    backend_instances: dict[str, object] = {}
    for db in config.databases:
        if db.storage not in seen_backends:
            seen_backends.add(db.storage)
            backend_instances[db.storage] = get_storage(config.storage_backends[db.storage])

    # Build prefix list  include archon_ (current), raven_ and backops_ (migration window)
    if database:
        prefixes = [f"archon_{database}_", f"raven_{database}_", f"backops_{database}_"]
    else:
        prefixes = ["archon_", "raven_", "backops_"]

    backups: list[BackupMeta] = []
    seen_filenames: set[str] = set()
    for backend_name, storage in backend_instances.items():
        entries: list[dict] = []
        for prefix in prefixes:
            entries.extend(storage.list(prefix))
        for entry in entries:
            fn = entry["filename"]
            if fn.endswith(".sha256") or fn.endswith(".meta") or fn.endswith(".schema"):
                continue
            if fn in seen_filenames:
                continue
            seen_filenames.add(fn)
            parsed = _parse_filename(fn)
            if parsed is None:
                continue
            if database and parsed["db_name"] != database:
                continue

            # Read .meta sidecar for triggered_by; default to "unknown" if absent/invalid
            triggered_by = "unknown"
            try:
                meta_bytes = storage.read(f"{fn}.meta")
                meta = json.loads(meta_bytes.decode())
                triggered_by = meta.get("triggered_by", "unknown")
            except Exception:
                pass

            backups.append(BackupMeta(
                filename=fn,
                database=parsed["db_name"],
                timestamp=parsed["timestamp"],
                size_bytes=entry.get("size_bytes", 0),
                rotation_type=parsed["rotation"],
                storage_backend=backend_name,
                encrypted=parsed["encrypted"],
                file_exists=storage.exists(fn),
                triggered_by=triggered_by,
                sidecar_exists=storage.exists(f"{fn}.sha256"),
            ))

    backups.sort(key=lambda b: b.timestamp, reverse=True)
    return BackupsResponse(backups=backups)


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    """Per-database scheduler status including next run time and last job outcome."""
    config: AppConfig = request.app.state.config
    scheduler = request.app.state.scheduler
    job_store = request.app.state.job_store

    databases: list[DatabaseStatus] = []
    for db in config.databases:
        # Next scheduled run from APScheduler
        aps_job = scheduler._aps.get_job(f"backup_{db.name}")
        next_run: Optional[str] = None
        if aps_job and aps_job.next_run_time:
            next_run = aps_job.next_run_time.isoformat()

        # All jobs for this database
        db_jobs = await job_store.list_for_database(db.name)

        # Most recent completed or failed job
        finished = [
            j for j in db_jobs
            if j["status"] in ("completed", "failed") and j.get("completed_at")
        ]
        last_finished = max(finished, key=lambda j: j["completed_at"]) if finished else None

        databases.append(DatabaseStatus(
            database=db.name,
            last_run_time=last_finished["completed_at"] if last_finished else None,
            next_scheduled_run=next_run,
            last_status=last_finished["status"] if last_finished else None,
            currently_running=any(j["status"] == "running" for j in db_jobs),
        ))

    return StatusResponse(databases=databases)


# ---------------------------------------------------------------------------
# DELETE /backups/{filename}
# ---------------------------------------------------------------------------

@router.delete("/backups/{filename}", response_model=DeleteResponse)
async def delete_backup(filename: str, request: Request) -> DeleteResponse:
    """
    Delete a backup file and its .sha256 sidecar from storage.
    The storage backend is determined from the database name embedded in the filename.
    """
    config: AppConfig = request.app.state.config

    parsed = _parse_filename(filename)
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot parse database name from filename '{filename}'",
        )

    db = _find_db(config, parsed["db_name"])
    if db is None:
        raise HTTPException(
            status_code=404,
            detail=f"Database '{parsed['db_name']}' not found in config",
        )

    storage = get_storage(config.storage_backends[db.storage])

    if not storage.exists(filename):
        raise HTTPException(
            status_code=404,
            detail=f"Backup file '{filename}' not found in storage",
        )

    storage.delete(filename)
    storage.delete(f"{filename}.sha256")   # no-op if sidecar is already absent
    storage.delete(f"{filename}.meta")     # no-op if sidecar is already absent
    storage.delete(f"{filename}.schema")   # no-op if sidecar is already absent

    log.info(
        "backup_deleted",
        f"Backup deleted via API: {filename}",
        database=db.name,
        filename=filename,
    )
    return DeleteResponse(deleted=filename)


# ---------------------------------------------------------------------------
# POST /reload
# ---------------------------------------------------------------------------

@router.post("/reload", response_model=ReloadResponse)
async def post_reload(request: Request) -> ReloadResponse:
    """
    Re-read config.yaml from disk, validate it, and re-register all cron jobs.
    Returns 400 with the validation error if the new config is invalid —
    the existing schedule keeps running in that case.
    """
    try:
        new_config = ConfigLoader().load()
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Config reload failed: {e}")

    scheduler = request.app.state.scheduler
    scheduler.reload(new_config)
    request.app.state.config = new_config

    log.info(
        "config_reloaded",
        f"Config reloaded: {len(new_config.databases)} database(s) registered",
    )
    return ReloadResponse(
        status="reloaded",
        databases_registered=len(new_config.databases),
        errors=[],
    )


# ---------------------------------------------------------------------------
# GET /health   no auth required (Docker healthcheck + load balancers)
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float


_startup_time: float = time.monotonic()


@router.get("/health", response_model=HealthResponse, include_in_schema=True)
async def get_health() -> HealthResponse:
    """Liveness check. No X-API-Key required."""
    return HealthResponse(
        status="ok",
        version="2.0.0",
        uptime_seconds=round(time.monotonic() - _startup_time, 1),
    )


# ---------------------------------------------------------------------------
# GET /logs   Historical log entries from DB
# ---------------------------------------------------------------------------

class LogEntryResponse(BaseModel):
    timestamp: str
    level: str
    event: str
    database: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class LogsResponse(BaseModel):
    entries: list[LogEntryResponse]


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    level: Optional[str] = Query(default=None),
) -> LogsResponse:
    """
    Return the most recent log entries from the log_events table.
    Optional ?level=INFO|WARNING|ERROR filter.
    No-op (returns empty list) if persistence is not configured.
    """
    if not hasattr(request.app.state, "config"):
        return LogsResponse(entries=[])
    return LogsResponse(entries=[])


# ---------------------------------------------------------------------------
# GET /logs/stream   Server-Sent Events (live log tail)
# ---------------------------------------------------------------------------

@router.get("/logs/stream")
async def get_logs_stream(
    request: Request,
    level: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """
    Server-Sent Events stream of structured log entries.
    Optional filter: ?level=INFO|WARNING|ERROR

    Auth: X-API-Key header OR ?api_key= query param (EventSource cannot set headers).
    The middleware already enforced the header; the query-param path is validated here.
    """
    # EventSource cannot set custom headers  allow ?api_key= as fallback
    if "api_key" in request.query_params:
        qp_key = request.query_params["api_key"]
        expected = request.app.state.config.api.api_key
        if qp_key != expected:
            raise HTTPException(status_code=401, detail="Unauthorized: invalid api_key param")

    async def _event_generator() -> AsyncGenerator[str, None]:
        q = log_broadcaster.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Send keep-alive comment to prevent proxy timeouts
                    yield ": keep-alive\n\n"
                    continue

                # Apply optional level filter
                if level and entry.get("level") != level.upper():
                    continue

                yield f"data: {json.dumps(entry)}\n\n"
        finally:
            log_broadcaster.unsubscribe(q)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering for SSE
        },
    )

