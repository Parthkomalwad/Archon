import asyncio
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator


from fastapi import FastAPI

from app.api.middleware import APIKeyMiddleware
from app.api.routes import router
from app.api.granular_routes import granular_router
from app.config import AppConfig, ConfigError, ConfigLoader, DatabaseConfig
from app.granular import GranularSessionStore
from app.jobs import JobStore, JobQueue
from app.logger import log
from app.scheduler import Scheduler
from app.semaphore import JobSemaphore
from app.webhook import WebhookService


# ---------------------------------------------------------------------------
# Startup DB connection check
# ---------------------------------------------------------------------------

def _check_db_connection(db: DatabaseConfig) -> bool:
    """
    Verify a database is reachable before serving traffic.

    - postgres / mongodb : TCP socket connect to host:port (5s timeout)
    - sqlite             : parent directory of the path must exist
    """
    if db.type == "sqlite":
        parent = Path(db.path).parent
        if parent.exists():
            log.info("db_connection_ok", f"SQLite path accessible: {db.path}", database=db.name)
            return True
        log.error(
            "db_connection_failed",
            f"SQLite parent directory does not exist: {parent}",
            database=db.name,
            error=str(parent),
        )
        return False

    # postgres / mongodb  TCP reachability check
    try:
        with socket.create_connection((db.host, db.port), timeout=5):
            pass
        log.info(
            "db_connection_ok",
            f"Reachable at {db.host}:{db.port}",
            database=db.name,
        )
        return True
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        log.error(
            "db_connection_failed",
            f"Cannot reach {db.host}:{db.port}",
            database=db.name,
            error=str(e),
        )
        return False


# ---------------------------------------------------------------------------
# Lifespan  startup and shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # ── Step 1: Load and validate config ────────────────────────────────────
    try:
        loader = ConfigLoader()
        config: AppConfig = loader.load()
    except ConfigError as e:
        log.error("startup_failed", f"Config error: {e}", error=str(e))
        sys.exit(1)

    # ── Step 2: Connection-check every configured database ──────────────────
    failed_dbs = [db.name for db in config.databases if not _check_db_connection(db)]
    if failed_dbs:
        log.error(
            "startup_failed",
            f"Cannot reach database(s): {failed_dbs}. Exiting.",
            error=f"Unreachable: {', '.join(failed_dbs)}",
        )
        sys.exit(1)

    # ── Step 3: Initialise JobStore and JobQueue ──────────────────────────
    db_pool = None
    job_store = JobStore(pool=db_pool)
    job_queue = JobQueue()

    # ── Step 4: Initialise global concurrency semaphore ─────────────────────
    job_semaphore = JobSemaphore(config.max_parallel)

    # ── Step 5: Initialise WebhookService ────────────────────────────────────
    webhook_service = WebhookService(config.webhooks)

    # ── Step 6: Attach everything to app.state ───────────────────────────────
    app.state.config = config
    app.state.db_pool = db_pool
    app.state.job_store = job_store
    app.state.job_queue = job_queue
    app.state.job_semaphore = job_semaphore
    app.state.webhook_service = webhook_service

    # ── Step 6b: Initialise GranularSessionStore ─────────────────────────────
    granular_store = GranularSessionStore()
    app.state.granular_store = granular_store

    # ── Step 7: Background job-purge task (runs every hour) ─────────────────────
    async def _purge_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            purged = await job_store.purge_old()
            if purged:
                log.info("job_purged", f"Purged {purged} expired job(s) from JobStore")
            await app.state.granular_store.cleanup_expired()

    purge_task = asyncio.create_task(_purge_loop())

    # ── Step 8: Start Scheduler ──────────────────────────────────────────────
    scheduler = Scheduler(config, job_store, job_queue, job_semaphore, webhook_service, pool=db_pool)
    await scheduler.start()
    app.state.scheduler = scheduler

    parallel_label = str(config.max_parallel) if config.max_parallel else "unlimited"
    log.info(
        "startup_ok",
        f"Archon started. {len(config.databases)} database(s) configured. max_parallel={parallel_label}",
        max_parallel=parallel_label,
    )
    for db in config.databases:
        log.info(
            "startup_ok",
            f"Database '{db.name}': type={db.type}, restore_strategy={db.restore_strategy}",
            database=db.name,
            restore_strategy=db.restore_strategy,
        )

    yield  # ── Server is live ────────────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────────
    scheduler.shutdown()
    purge_task.cancel()
    log.info("startup_ok", "Archon shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Archon",
    version="2.0.0",
    description="Plug-and-play database backup & restore sidecar",
    lifespan=lifespan,
)

app.add_middleware(APIKeyMiddleware)
app.include_router(router)
app.include_router(granular_router)
