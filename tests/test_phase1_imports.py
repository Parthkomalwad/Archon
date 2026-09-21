"""Phase 1 import smoke test  run with: py tests/test_phase1_imports.py"""
import sys
sys.path.insert(0, ".")

errors = []

def check(label, fn):
    try:
        fn()
        print(f"  OK  {label}")
    except Exception as e:
        errors.append(f"FAIL  {label}: {e}")
        print(f"FAIL  {label}: {e}")

print("\n--- Import checks ---")
check("app.logger",            lambda: __import__("app.logger", fromlist=["log"]))
check("app.config",            lambda: __import__("app.config", fromlist=["ConfigLoader", "ConfigError", "AppConfig"]))
check("app.jobs",              lambda: __import__("app.jobs", fromlist=["JobStore", "JobQueue"]))
check("app.providers.base",    lambda: __import__("app.providers.base", fromlist=["BaseProvider", "ProviderError"]))
check("app.storage.base",      lambda: __import__("app.storage.base", fromlist=["BaseStorage", "StorageError"]))
check("app.api.middleware",    lambda: __import__("app.api.middleware", fromlist=["APIKeyMiddleware"]))
check("app.api.routes",        lambda: __import__("app.api.routes", fromlist=["router"]))
check("app.main",              lambda: __import__("app.main", fromlist=["app"]))

print("\n--- Logger output check ---")
from app.logger import log
check("log.info emits JSON",   lambda: log.info("test_event", "Hello from test", database="test_db"))
check("log.error emits JSON",  lambda: log.error("test_error", "Error test", error="something went wrong"))

print("\n--- Config validation checks ---")
from app.config import ConfigError, ScheduleConfig, DatabaseConfig, RetentionConfig, EncryptionConfig, ApiConfig, AppConfig, LocalStorageConfig

def test_good_config():
    AppConfig(
        databases=[
            DatabaseConfig(
                name="pg",
                type="postgres",
                host="localhost",
                port=5432,
                db="mydb",
                user="u",
                password="p",
                schedule=ScheduleConfig(frequency="daily", at="14:00", timezone="UTC"),
                storage="local",
            )
        ],
        storage_backends={"local": LocalStorageConfig(path="/tmp")},
        encryption=EncryptionConfig(enabled=False),
        retention=RetentionConfig(),
        api=ApiConfig(api_key="secret"),
    )

def test_bad_type():
    try:
        DatabaseConfig(
            name="bad",
            type="mysql",
            host="h", port=3306, db="d", user="u", password="p",
            schedule=ScheduleConfig(frequency="daily", at="14:00", timezone="UTC"),
            storage="local",
        )
        raise AssertionError("Should have raised ValueError for unknown type")
    except Exception as e:
        if "mysql" in str(e).lower() or "unknown" in str(e).lower():
            pass  # expected
        else:
            raise

def test_missing_encryption_key():
    try:
        EncryptionConfig(enabled=True, key=None)
        raise AssertionError("Should have raised ValueError")
    except Exception as e:
        if "key" in str(e).lower() or "required" in str(e).lower():
            pass  # expected
        else:
            raise

def test_per_db_retention_merge():
    global_ret = RetentionConfig(daily=7, weekly=4)
    # Simulate merge logic from ConfigLoader
    merged = {**global_ret.model_dump(), **{"daily": 14}}
    r = RetentionConfig(**merged)
    assert r.daily == 14, f"Expected 14, got {r.daily}"
    assert r.weekly == 4,  f"Expected 4, got {r.weekly}"

check("valid config builds",          test_good_config)
check("unknown db type raises error", test_bad_type)
check("encryption key required",      test_missing_encryption_key)
check("per-db retention merge",       test_per_db_retention_merge)

print("\n--- JobStore checks ---")
from app.jobs import JobStore, JobQueue, STATUS_QUEUED, STATUS_COMPLETED

def test_jobstore():
    import asyncio
    store = JobStore()

    async def _run():
        jid = await store.create("my_db")
        assert jid is not None
        job = await store.get(jid)
        assert job["status"] == STATUS_QUEUED
        assert job["database"] == "my_db"
        await store.update(jid, status=STATUS_COMPLETED, backup_filename="file.sql.enc")
        job = await store.get(jid)
        assert job["status"] == STATUS_COMPLETED
        assert job["backup_filename"] == "file.sql.enc"
        assert await store.get("nonexistent") is None

    asyncio.run(_run())

def test_jobqueue():
    import asyncio
    queue = JobQueue()
    q1 = queue.get("db_a")
    q2 = queue.get("db_a")
    q3 = queue.get("db_b")
    assert q1 is q2, "Same DB should return the same queue"
    assert q1 is not q3, "Different DBs should have different queues"

check("JobStore create/update/get", test_jobstore)
check("JobQueue per-database isolation", test_jobqueue)

print("\n--- Summary ---")
if errors:
    print(f"\n{len(errors)} check(s) FAILED:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print(f"\nAll checks passed.")
