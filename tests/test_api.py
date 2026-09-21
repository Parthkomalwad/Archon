"""
Phase 7 REST API tests.

All 7 endpoints are tested against a fully wired FastAPI app with:
  - real middleware (X-API-Key enforcement)
  - mocked Scheduler (no APScheduler, no real DB)
  - mocked storage (in-memory)
  - real JobStore / JobQueue
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import (
    AppConfig, ApiConfig, DatabaseConfig, EncryptionConfig,
    LocalStorageConfig, RetentionConfig, ScheduleConfig,
)
from app.encryption import EncryptionService
from app.jobs import JobStore, JobQueue, STATUS_QUEUED, STATUS_COMPLETED, STATUS_FAILED, STATUS_RUNNING
from app.main import app
from app.semaphore import JobSemaphore
from app.webhook import WebhookService


# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-api-key-9876"

_DB_PG = DatabaseConfig(
    name="primary_postgres",
    type="postgres",
    host="localhost", port=5432,
    db="testdb", user="u", password="p",
    schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
    storage="local",
)

_DB_SQLITE = DatabaseConfig(
    name="cache_sqlite",
    type="sqlite",
    path="/data/cache.db",
    schedule=ScheduleConfig(frequency="daily", at="03:00", timezone="UTC"),
    storage="local",
)

_CONFIG = AppConfig(
    databases=[_DB_PG, _DB_SQLITE],
    storage_backends={"local": LocalStorageConfig(path="/tmp/backups")},
    encryption=EncryptionConfig(enabled=False),
    retention=RetentionConfig(),
    api=ApiConfig(api_key=TEST_API_KEY),
)

# A valid backup filename for the postgres database
_PG_FILENAME = "raven_primary_postgres_2025-06-15T14-00-01_daily.sql"
_PG_FILENAME_ENC = "raven_primary_postgres_2025-06-15T14-00-01_daily.sql.enc"
_SQLITE_FILENAME = "raven_cache_sqlite_2025-07-01T00-00-00_monthly.db"

HDR = {"X-API-Key": TEST_API_KEY}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _MockStorage:
    """In-memory storage backend for testing."""

    def __init__(self):
        self._data: dict[str, bytes] = {}

    def write(self, filename: str, data: bytes) -> None:
        self._data[filename] = data

    def read(self, filename: str) -> bytes:
        if filename not in self._data:
            from app.storage.base import StorageError
            raise StorageError(f"Not found: {filename}")
        return self._data[filename]

    def list(self, prefix: str) -> list[dict]:
        return [
            {"filename": fn, "size_bytes": len(data)}
            for fn, data in self._data.items()
            if fn.startswith(prefix)
        ]

    def delete(self, filename: str) -> None:
        self._data.pop(filename, None)

    def exists(self, filename: str) -> bool:
        return filename in self._data

    def write_stream(self, filename: str, source_path) -> None:
        with open(source_path, "rb") as f:
            self._data[filename] = f.read()

    def read_stream(self, filename: str, dest_path) -> None:
        if filename not in self._data:
            from app.storage.base import StorageError
            raise StorageError(f"Not found: {filename}")
        with open(dest_path, "wb") as f:
            f.write(self._data[filename])


def _run(coro):
    """Run a coroutine synchronously  used in sync test methods."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_client():
    """Build a TestClient with mocked app state (no real DB, no APScheduler)."""
    job_store = JobStore()
    job_queue = JobQueue()

    # Mock scheduler: enqueue creates a real job in job_store and returns the id
    mock_scheduler = MagicMock()

    async def _fake_enqueue(db, triggered_by="manual"):
        return await job_store.create(db.name, triggered_by=triggered_by)

    mock_scheduler.enqueue = AsyncMock(side_effect=_fake_enqueue)

    # APScheduler job mock  next_run_time = None by default
    mock_aps_job = MagicMock()
    mock_aps_job.next_run_time = None
    mock_scheduler._aps = MagicMock()
    mock_scheduler._aps.get_job.return_value = mock_aps_job

    app.state.config = _CONFIG
    app.state.job_store = job_store
    app.state.job_queue = job_queue
    app.state.job_semaphore = JobSemaphore(None)  # unlimited for API tests
    app.state.webhook_service = WebhookService([])  # no webhooks in API tests
    app.state.scheduler = mock_scheduler

    storage = _MockStorage()
    app.state._test_storage = storage  # stash for direct inspection in tests

    return TestClient(app, raise_server_exceptions=True), job_store, mock_scheduler, storage


# ---------------------------------------------------------------------------
# Auth middleware (all endpoints must enforce X-API-Key)
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    def setup_method(self):
        self.client, _, _, _ = _make_client()

    def test_status_401_no_key(self):
        r = self.client.get("/status")
        assert r.status_code == 401

    def test_status_401_wrong_key(self):
        r = self.client.get("/status", headers={"X-API-Key": "wrong"})
        assert r.status_code == 401

    def test_backup_401_no_key(self):
        r = self.client.post("/backup")
        assert r.status_code == 401

    def test_jobs_401_no_key(self):
        r = self.client.get("/jobs/some-id")
        assert r.status_code == 401

    def test_restore_401_no_key(self):
        r = self.client.post("/restore", json={"filename": "x", "confirm": True})
        assert r.status_code == 401

    def test_backups_401_no_key(self):
        r = self.client.get("/backups")
        assert r.status_code == 401

    def test_delete_401_no_key(self):
        r = self.client.delete(f"/backups/{_PG_FILENAME}")
        assert r.status_code == 401

    def test_reload_401_no_key(self):
        r = self.client.post("/reload")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /backup
# ---------------------------------------------------------------------------

class TestPostBackup:
    def setup_method(self):
        self.client, self.job_store, self.scheduler, self.storage = _make_client()

    def test_backup_all_returns_202(self):
        r = self.client.post("/backup", headers=HDR)
        assert r.status_code == 202

    def test_backup_all_enqueues_all_databases(self):
        r = self.client.post("/backup", headers=HDR)
        body = r.json()
        assert "jobs" in body
        assert len(body["jobs"]) == 2

    def test_backup_all_returns_job_ids(self):
        r = self.client.post("/backup", headers=HDR)
        jobs = r.json()["jobs"]
        for job in jobs:
            assert "job_id" in job
            assert len(job["job_id"]) == 36  # UUID format

    def test_backup_all_returns_correct_databases(self):
        r = self.client.post("/backup", headers=HDR)
        db_names = {j["database"] for j in r.json()["jobs"]}
        assert db_names == {"primary_postgres", "cache_sqlite"}

    def test_backup_all_status_is_queued(self):
        r = self.client.post("/backup", headers=HDR)
        for job in r.json()["jobs"]:
            assert job["status"] == STATUS_QUEUED

    def test_backup_specific_database(self):
        r = self.client.post("/backup", json={"database": "primary_postgres"}, headers=HDR)
        assert r.status_code == 202
        body = r.json()
        assert len(body["jobs"]) == 1
        assert body["jobs"][0]["database"] == "primary_postgres"

    def test_backup_unknown_database_returns_404(self):
        r = self.client.post("/backup", json={"database": "nonexistent_db"}, headers=HDR)
        assert r.status_code == 404

    def test_backup_job_appears_in_job_store(self):
        r = self.client.post("/backup", json={"database": "primary_postgres"}, headers=HDR)
        job_id = r.json()["jobs"][0]["job_id"]
        job = _run(self.job_store.get(job_id))
        assert job is not None
        assert job["database"] == "primary_postgres"

    def test_backup_no_body_enqueues_all(self):
        """POST /backup with no JSON body should enqueue all databases."""
        r = self.client.post("/backup", headers=HDR)
        assert len(r.json()["jobs"]) == 2


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------

class TestGetJob:
    def setup_method(self):
        self.client, self.job_store, _, _ = _make_client()

    def test_job_not_found_returns_404(self):
        r = self.client.get("/jobs/00000000-0000-0000-0000-000000000000", headers=HDR)
        assert r.status_code == 404

    def test_job_queued_returns_200(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        r = self.client.get(f"/jobs/{job_id}", headers=HDR)
        assert r.status_code == 200

    def test_job_response_schema(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        r = self.client.get(f"/jobs/{job_id}", headers=HDR)
        body = r.json()
        required = {"job_id", "database", "status", "queued_at", "started_at",
                    "completed_at", "backup_filename", "error_message"}
        assert required <= set(body.keys())

    def test_job_id_matches(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        r = self.client.get(f"/jobs/{job_id}", headers=HDR)
        assert r.json()["job_id"] == job_id

    def test_job_status_queued(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        r = self.client.get(f"/jobs/{job_id}", headers=HDR)
        assert r.json()["status"] == STATUS_QUEUED

    def test_job_status_completed(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        _run(self.job_store.update(job_id, status=STATUS_COMPLETED, backup_filename="file.sql"))
        r = self.client.get(f"/jobs/{job_id}", headers=HDR)
        assert r.json()["status"] == STATUS_COMPLETED
        assert r.json()["backup_filename"] == "file.sql"

    def test_job_status_failed(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        _run(self.job_store.update(job_id, status=STATUS_FAILED, error_message="pg_dump failed"))
        r = self.client.get(f"/jobs/{job_id}", headers=HDR)
        assert r.json()["status"] == STATUS_FAILED
        assert r.json()["error_message"] == "pg_dump failed"


# ---------------------------------------------------------------------------
# POST /restore
# ---------------------------------------------------------------------------

class TestPostRestore:
    def setup_method(self):
        self.client, self.job_store, _, self.storage = _make_client()
        # Pre-populate storage with a valid unencrypted backup
        self.data = b"SELECT 1;\nSELECT 2;\n"
        self.checksum = EncryptionService.compute_checksum(self.data)
        self.storage.write(_PG_FILENAME, self.data)
        self.storage.write(f"{_PG_FILENAME}.sha256", self.checksum.encode())

    def _patch_storage(self, test_fn):
        """Helper: patch get_storage to return our in-memory mock."""
        with patch("app.api.routes.get_storage", return_value=self.storage):
            with patch("app.api.routes.get_provider") as mock_provider_factory:
                mock_provider = MagicMock()
                mock_provider.restore = MagicMock()
                mock_provider_factory.return_value = mock_provider
                test_fn(mock_provider)

    def test_restore_without_confirm_returns_400(self):
        r = self.client.post(
            "/restore",
            json={"filename": _PG_FILENAME, "confirm": False},
            headers=HDR,
        )
        assert r.status_code == 400
        assert "confirm" in r.json()["detail"].lower()

    def test_restore_missing_confirm_field_returns_400(self):
        """confirm defaults to False  missing is same as false."""
        r = self.client.post(
            "/restore",
            json={"filename": _PG_FILENAME},
            headers=HDR,
        )
        assert r.status_code == 400

    def test_restore_unknown_target_database_returns_404(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.post(
                "/restore",
                json={"filename": _PG_FILENAME, "confirm": True, "target_database": "nonexistent"},
                headers=HDR,
            )
        assert r.status_code == 404

    def test_restore_missing_file_returns_404(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.post(
                "/restore",
                json={"filename": "raven_primary_postgres_2099-01-01T00-00-00_daily.sql", "confirm": True},
                headers=HDR,
            )
        assert r.status_code == 404

    def test_restore_missing_sidecar_returns_404(self):
        self.storage.write("raven_primary_postgres_2099-02-01T00-00-00_daily.sql", b"data")
        # No .sha256 sidecar written
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.post(
                "/restore",
                json={"filename": "raven_primary_postgres_2099-02-01T00-00-00_daily.sql", "confirm": True},
                headers=HDR,
            )
        assert r.status_code == 404
        assert "sidecar" in r.json()["detail"].lower() or "sha256" in r.json()["detail"].lower()

    def test_restore_checksum_mismatch_returns_400(self):
        tampered = self.data + b"TAMPERED"
        self.storage.write(_PG_FILENAME, tampered)  # overwrite with bad data
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.post(
                "/restore",
                json={"filename": _PG_FILENAME, "confirm": True},
                headers=HDR,
            )
        assert r.status_code == 400
        assert "integrity" in r.json()["detail"].lower() or "checksum" in r.json()["detail"].lower()

    def test_restore_success_returns_200(self):
        def run(mock_provider):
            r = self.client.post(
                "/restore",
                json={"filename": _PG_FILENAME, "confirm": True},
                headers=HDR,
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "restored"
            assert body["filename"] == _PG_FILENAME
            assert body["database"] == "primary_postgres"

        self._patch_storage(run)

    def test_restore_success_calls_provider_restore(self):
        def run(mock_provider):
            self.client.post(
                "/restore",
                json={"filename": _PG_FILENAME, "confirm": True},
                headers=HDR,
            )
            mock_provider.restore.assert_called_once()
            args = mock_provider.restore.call_args
            assert args[0][1] is True  # confirm=True passed

        self._patch_storage(run)

    def test_restore_infers_database_from_filename(self):
        """target_database omitted  db_name parsed from filename."""
        def run(mock_provider):
            r = self.client.post(
                "/restore",
                json={"filename": _PG_FILENAME, "confirm": True},
                headers=HDR,
            )
            assert r.status_code == 200
            assert r.json()["database"] == "primary_postgres"

        self._patch_storage(run)

    def test_restore_with_explicit_target_database(self):
        def run(mock_provider):
            r = self.client.post(
                "/restore",
                json={
                    "filename": _PG_FILENAME,
                    "confirm": True,
                    "target_database": "primary_postgres",
                },
                headers=HDR,
            )
            assert r.status_code == 200

        self._patch_storage(run)


# ---------------------------------------------------------------------------
# GET /backups
# ---------------------------------------------------------------------------

class TestGetBackups:
    def setup_method(self):
        self.client, self.job_store, _, self.storage = _make_client()
        # Seed storage with two backup files + sidecars
        for fn in (_PG_FILENAME, _SQLITE_FILENAME):
            self.storage.write(fn, b"backup data")
            self.storage.write(f"{fn}.sha256", b"abc123")

    def test_backups_returns_200(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        assert r.status_code == 200

    def test_backups_response_has_backups_key(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        assert "backups" in r.json()

    def test_backups_excludes_sidecar_files(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        filenames = [b["filename"] for b in r.json()["backups"]]
        assert not any(fn.endswith(".sha256") for fn in filenames)

    def test_backups_returns_both_databases(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        db_names = {b["database"] for b in r.json()["backups"]}
        assert "primary_postgres" in db_names
        assert "cache_sqlite" in db_names

    def test_backups_metadata_fields(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        item = r.json()["backups"][0]
        for field in ("filename", "database", "timestamp", "size_bytes",
                      "rotation_type", "storage_backend", "encrypted", "file_exists"):
            assert field in item, f"Missing field: {field}"

    def test_backups_file_exists_true(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        for item in r.json()["backups"]:
            assert item["file_exists"] is True

    def test_backups_encrypted_flag_false_for_no_enc(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        pg_items = [b for b in r.json()["backups"] if b["database"] == "primary_postgres"]
        assert pg_items[0]["encrypted"] is False

    def test_backups_encrypted_flag_true_for_enc_file(self):
        self.storage.write(_PG_FILENAME_ENC, b"enc data")
        self.storage.write(f"{_PG_FILENAME_ENC}.sha256", b"xxx")
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        enc_items = [b for b in r.json()["backups"] if b["filename"] == _PG_FILENAME_ENC]
        assert enc_items[0]["encrypted"] is True

    def test_backups_filter_by_database(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups?database=primary_postgres", headers=HDR)
        items = r.json()["backups"]
        assert all(b["database"] == "primary_postgres" for b in items)
        assert len(items) >= 1

    def test_backups_filter_excludes_other_database(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups?database=primary_postgres", headers=HDR)
        db_names = {b["database"] for b in r.json()["backups"]}
        assert "cache_sqlite" not in db_names

    def test_backups_rotation_type_parsed(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.get("/backups", headers=HDR)
        pg_items = [b for b in r.json()["backups"] if b["database"] == "primary_postgres"]
        assert pg_items[0]["rotation_type"] == "daily"


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def setup_method(self):
        self.client, self.job_store, self.scheduler, _ = _make_client()

    def test_status_returns_200(self):
        r = self.client.get("/status", headers=HDR)
        assert r.status_code == 200

    def test_status_response_schema(self):
        r = self.client.get("/status", headers=HDR)
        body = r.json()
        assert "databases" in body
        assert len(body["databases"]) == 2

    def test_status_all_fields_present(self):
        r = self.client.get("/status", headers=HDR)
        for db in r.json()["databases"]:
            for field in ("database", "last_run_time", "next_scheduled_run",
                          "last_status", "currently_running"):
                assert field in db

    def test_status_no_jobs_run_yet(self):
        r = self.client.get("/status", headers=HDR)
        for db in r.json()["databases"]:
            assert db["last_run_time"] is None
            assert db["last_status"] is None
            assert db["currently_running"] is False

    def test_status_shows_next_run_time_when_set(self):
        self.scheduler._aps.get_job.return_value.next_run_time = MagicMock()
        self.scheduler._aps.get_job.return_value.next_run_time.isoformat.return_value = "2025-06-15T14:00:00+00:00"
        r = self.client.get("/status", headers=HDR)
        pg = next(d for d in r.json()["databases"] if d["database"] == "primary_postgres")
        assert pg["next_scheduled_run"] == "2025-06-15T14:00:00+00:00"

    def test_status_currently_running_when_job_is_running(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        _run(self.job_store.update(job_id, status=STATUS_RUNNING))
        r = self.client.get("/status", headers=HDR)
        pg = next(d for d in r.json()["databases"] if d["database"] == "primary_postgres")
        assert pg["currently_running"] is True

    def test_status_last_status_reflects_completed_job(self):
        job_id = _run(self.job_store.create("primary_postgres"))
        _run(self.job_store.update(
            job_id, status=STATUS_COMPLETED,
            completed_at="2025-06-15T14:00:01Z",
            backup_filename=_PG_FILENAME,
        ))
        r = self.client.get("/status", headers=HDR)
        pg = next(d for d in r.json()["databases"] if d["database"] == "primary_postgres")
        assert pg["last_status"] == STATUS_COMPLETED
        assert pg["last_run_time"] == "2025-06-15T14:00:01Z"


# ---------------------------------------------------------------------------
# DELETE /backups/{filename}
# ---------------------------------------------------------------------------

class TestDeleteBackup:
    def setup_method(self):
        self.client, self.job_store, _, self.storage = _make_client()
        self.storage.write(_PG_FILENAME, b"backup bytes")
        self.storage.write(f"{_PG_FILENAME}.sha256", b"deadbeef")

    def test_delete_returns_200(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.delete(f"/backups/{_PG_FILENAME}", headers=HDR)
        assert r.status_code == 200

    def test_delete_returns_deleted_filename(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.delete(f"/backups/{_PG_FILENAME}", headers=HDR)
        assert r.json()["deleted"] == _PG_FILENAME

    def test_delete_removes_file_from_storage(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            self.client.delete(f"/backups/{_PG_FILENAME}", headers=HDR)
        assert not self.storage.exists(_PG_FILENAME)

    def test_delete_removes_sidecar(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            self.client.delete(f"/backups/{_PG_FILENAME}", headers=HDR)
        assert not self.storage.exists(f"{_PG_FILENAME}.sha256")

    def test_delete_missing_file_returns_404(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.delete(
                "/backups/raven_primary_postgres_2099-01-01T00-00-00_daily.sql",
                headers=HDR,
            )
        assert r.status_code == 404

    def test_delete_invalid_filename_returns_400(self):
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.delete("/backups/not_a_valid_backup_filename.txt", headers=HDR)
        assert r.status_code == 400

    def test_delete_unknown_database_in_filename_returns_404(self):
        # Valid format but db_name not in config
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.delete(
                "/backups/raven_unknown_db_2025-01-01T00-00-00_daily.sql",
                headers=HDR,
            )
        assert r.status_code == 404

    def test_delete_does_not_error_when_sidecar_missing(self):
        """Sidecar may already be gone; delete should still succeed."""
        self.storage.delete(f"{_PG_FILENAME}.sha256")
        with patch("app.api.routes.get_storage", return_value=self.storage):
            r = self.client.delete(f"/backups/{_PG_FILENAME}", headers=HDR)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /reload
# ---------------------------------------------------------------------------

class TestPostReload:
    def setup_method(self):
        self.client, self.job_store, self.scheduler, _ = _make_client()

    def test_reload_with_valid_config_returns_200(self):
        with patch("app.api.routes.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.return_value = _CONFIG
            r = self.client.post("/reload", headers=HDR)
        assert r.status_code == 200

    def test_reload_response_schema(self):
        with patch("app.api.routes.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.return_value = _CONFIG
            r = self.client.post("/reload", headers=HDR)
        body = r.json()
        assert body["status"] == "reloaded"
        assert body["databases_registered"] == 2
        assert body["errors"] == []

    def test_reload_calls_scheduler_reload(self):
        with patch("app.api.routes.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.return_value = _CONFIG
            self.client.post("/reload", headers=HDR)
        self.scheduler.reload.assert_called_once_with(_CONFIG)

    def test_reload_updates_app_state_config(self):
        new_config = _CONFIG  # same config is fine for this test
        with patch("app.api.routes.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.return_value = new_config
            self.client.post("/reload", headers=HDR)
        assert app.state.config is new_config

    def test_reload_with_invalid_config_returns_400(self):
        from app.config import ConfigError
        with patch("app.api.routes.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.side_effect = ConfigError("bad yaml")
            r = self.client.post("/reload", headers=HDR)
        assert r.status_code == 400
        assert "bad yaml" in r.json()["detail"]

    def test_reload_invalid_config_does_not_update_scheduler(self):
        from app.config import ConfigError
        with patch("app.api.routes.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.side_effect = ConfigError("bad yaml")
            self.client.post("/reload", headers=HDR)
        self.scheduler.reload.assert_not_called()
