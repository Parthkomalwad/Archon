"""
Phase 1 API checkpoint test.
Tests /status endpoint auth and response shape without touching a real database.
Run with: py tests/test_phase1_api.py
"""
import sys
sys.path.insert(0, ".")

from unittest.mock import patch
from fastapi.testclient import TestClient

# Build a minimal AppConfig in memory so we never hit a real DB
from app.config import (
    AppConfig, ApiConfig, DatabaseConfig, EncryptionConfig,
    LocalStorageConfig, RetentionConfig, ScheduleConfig,
)
from unittest.mock import MagicMock

from app.jobs import JobStore, JobQueue

TEST_API_KEY = "test-secret-key-12345"

_config = AppConfig(
    databases=[
        DatabaseConfig(
            name="test_pg",
            type="postgres",
            host="localhost", port=5432,
            db="testdb", user="u", password="p",
            schedule=ScheduleConfig(frequency="daily", at="14:00", timezone="UTC"),
            storage="local",
        )
    ],
    storage_backends={"local": LocalStorageConfig(path="/tmp/backups")},
    encryption=EncryptionConfig(enabled=False),
    retention=RetentionConfig(),
    api=ApiConfig(api_key=TEST_API_KEY),
)

# Patch out the lifespan (startup checks) so we control app state directly
from app.main import app

# Manually inject state as lifespan would
app.state.config = _config
app.state.job_store = JobStore()
app.state.job_queue = JobQueue()

# Mock scheduler  get_status uses scheduler._aps.get_job(...)
_mock_aps = MagicMock()
_mock_aps.get_job.return_value = None
_mock_scheduler = MagicMock()
_mock_scheduler._aps = _mock_aps
app.state.scheduler = _mock_scheduler

client = TestClient(app, raise_server_exceptions=True)


def _run_checks():
    errors = []

    def check(label, fn):
        try:
            fn()
            print(f"  OK  {label}")
        except Exception as e:
            errors.append(f"FAIL  {label}: {e}")
            print(f"FAIL  {label}: {e}")

    print("\n--- API: GET /status ---")

    def test_status_no_key():
        r = client.get("/status")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"

    def test_status_wrong_key():
        r = client.get("/status", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"

    def test_status_correct_key():
        r = client.get("/status", headers={"X-API-Key": TEST_API_KEY})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "databases" in body, f"Missing 'databases' key: {body}"
        assert len(body["databases"]) == 1
        db = body["databases"][0]
        assert db["database"] == "test_pg"
        assert db["currently_running"] is False
        assert db["last_run_time"] is None

    def test_status_response_shape():
        r = client.get("/status", headers={"X-API-Key": TEST_API_KEY})
        db = r.json()["databases"][0]
        required_fields = {"database", "last_run_time", "next_scheduled_run", "last_status", "currently_running"}
        missing = required_fields - set(db.keys())
        assert not missing, f"Response missing fields: {missing}"

    check("401 without X-API-Key",       test_status_no_key)
    check("401 with wrong key",          test_status_wrong_key)
    check("200 with correct key",        test_status_correct_key)
    check("response has all fields",     test_status_response_shape)

    print("\n--- Summary ---")
    if errors:
        print(f"\n{len(errors)} check(s) FAILED:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("\nAll API checks passed.")


if __name__ == "__main__":
    _run_checks()
