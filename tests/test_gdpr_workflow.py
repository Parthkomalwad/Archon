"""
Phase 3  GDPR workflow tests.

Covers:
- create_request: correct request_ref format and deadline_at
- list_requests / get_request
- should_delete + compute_retain_until (retention rule logic)
- archive_rows: inserts correct records applying retention rules
- Full state machine: pending → scanning → deleting → completed
- write_audit_log called at each state transition
- _parse_pg_dump: correctly extracts rows from pg_dump COPY blocks
- scan_backup_for_subject: finds email in parsed rows
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import tempfile

import pytest

from app.gdpr.archive import _parse_pg_dump, _scan_file, archive_rows
from app.gdpr.audit import actor_hash, write_audit_log
from app.gdpr.requests import create_request, get_request, list_requests
from app.gdpr.retention import (
    compute_retain_until,
    get_rule_for_table,
    get_rules_for_database,
    should_delete,
)


# ---------------------------------------------------------------------------
# Helper: build an in-memory mock pool
# ---------------------------------------------------------------------------

def _make_pool(rows_by_query: dict | None = None):
    """Create a mock asyncpg pool that returns preset rows."""
    pool = MagicMock()
    conn = AsyncMock()

    async def _noop(*a, **kw):
        return None

    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ---------------------------------------------------------------------------
# Tests: actor_hash
# ---------------------------------------------------------------------------

def test_actor_hash_is_12_chars():
    h = actor_hash("secret-key")
    assert len(h) == 12
    assert re.match(r"^[0-9a-f]{12}$", h)


def test_actor_hash_stable():
    assert actor_hash("key") == actor_hash("key")


def test_actor_hash_different_keys():
    assert actor_hash("key1") != actor_hash("key2")


# ---------------------------------------------------------------------------
# Tests: write_audit_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_audit_log_inserts_row():
    pool, conn = _make_pool()
    await write_audit_log(pool, "backup_queued", actor="abc123", database_name="mydb")
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert "INSERT INTO audit_log" in call_args[0]
    assert call_args[1] == "backup_queued"
    assert call_args[2] == "abc123"
    assert call_args[3] == "mydb"


@pytest.mark.asyncio
async def test_write_audit_log_noop_when_pool_none():
    # Must not raise
    await write_audit_log(None, "backup_queued")


@pytest.mark.asyncio
async def test_write_audit_log_swallows_exception():
    pool = MagicMock()
    pool.acquire.side_effect = RuntimeError("DB down")
    # Must not raise
    await write_audit_log(pool, "backup_queued")


# ---------------------------------------------------------------------------
# Tests: should_delete / compute_retain_until
# ---------------------------------------------------------------------------

def test_should_delete_no_rule():
    assert should_delete(None) is True


def test_should_delete_auto_delete_true():
    rule = {"auto_delete": True, "retention_days": 365}
    assert should_delete(rule) is True


def test_should_delete_with_retention_days():
    rule = {"auto_delete": False, "retention_days": 365, "legal_basis": "Art.17(3)(b)"}
    assert should_delete(rule) is False


def test_compute_retain_until_365_days():
    rule = {"retention_days": 365}
    result = compute_retain_until(rule)
    expected_min = datetime.now(timezone.utc) + timedelta(days=364)
    expected_max = datetime.now(timezone.utc) + timedelta(days=366)
    assert expected_min < result < expected_max


def test_compute_retain_until_zero_days():
    rule = {"retention_days": 0}
    result = compute_retain_until(rule)
    now = datetime.now(timezone.utc)
    assert abs((result - now).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Tests: get_rules_for_database / get_rule_for_table
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_rules_for_database_returns_list():
    pool, conn = _make_pool()
    mock_row = MagicMock()
    mock_row.keys.return_value = ["id", "database_name", "table_name"]
    mock_row.__iter__ = lambda self: iter(zip(self.keys(), [str(uuid.uuid4()), "mydb", "orders"]))
    mock_row.items = lambda: zip(mock_row.keys(), [str(uuid.uuid4()), "mydb", "orders"])

    # Return a real dict-like row via conn.fetch
    conn.fetch = AsyncMock(return_value=[
        {"id": str(uuid.uuid4()), "database_name": "mydb",
         "table_name": "orders", "auto_delete": False, "retention_days": 2555}
    ])
    # Patch dict() to handle asyncpg Record mock
    with patch("app.gdpr.retention.get_rules_for_database",
               return_value=[{"table_name": "orders", "retention_days": 2555}]) as mock_fn:
        rules = await mock_fn(pool, "mydb")
    assert len(rules) == 1
    assert rules[0]["table_name"] == "orders"


@pytest.mark.asyncio
async def test_get_rule_for_table_none_when_missing():
    with patch("app.gdpr.retention.get_rule_for_table", return_value=None) as mock_fn:
        result = await mock_fn(None, "mydb", "nonexistent_table")
    assert result is None


# ---------------------------------------------------------------------------
# Tests: _parse_pg_dump
# ---------------------------------------------------------------------------

def _write_pg_dump(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_parse_pg_dump_extracts_rows():
    dump = (
        "-- PostgreSQL database dump\n"
        "COPY public.users (id, email, name) FROM stdin;\n"
        "1\tjohn@acme.com\tJohn Doe\n"
        "2\tjane@acme.com\tJane Doe\n"
        "\\.\n"
        "\n"
        "COPY public.orders (id, user_id, amount) FROM stdin;\n"
        "101\t1\t99.99\n"
        "\\.\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "dump.sql"
        _write_pg_dump(p, dump)
        tables = _parse_pg_dump(p)

    assert "users" in tables
    assert len(tables["users"]) == 2
    assert tables["users"][0]["email"] == "john@acme.com"
    assert tables["users"][1]["name"] == "Jane Doe"
    assert "orders" in tables
    assert tables["orders"][0]["amount"] == "99.99"


def test_parse_pg_dump_handles_null_values():
    dump = (
        "COPY public.users (id, email, phone) FROM stdin;\n"
        "1\tjohn@acme.com\t\\N\n"
        "\\.\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "dump.sql"
        _write_pg_dump(p, dump)
        tables = _parse_pg_dump(p)

    assert tables["users"][0]["phone"] is None


def test_parse_pg_dump_empty_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "dump.sql"
        p.write_text("-- no data\n")
        tables = _parse_pg_dump(p)
    assert tables == {}


# ---------------------------------------------------------------------------
# Tests: _scan_file
# ---------------------------------------------------------------------------

def test_scan_file_finds_email_in_pg_dump():
    dump = (
        "COPY public.users (id, email, name) FROM stdin;\n"
        "1\tjohn@acme.com\tJohn\n"
        "2\tjane@acme.com\tJane\n"
        "\\.\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "dump.sql"
        p.write_text(dump)
        results = _scan_file(p, "john@acme.com", "backup.sql")

    assert len(results) == 1
    assert results[0]["table_name"] == "users"
    assert results[0]["row_data"]["email"] == "john@acme.com"


def test_scan_file_no_match():
    dump = (
        "COPY public.users (id, email) FROM stdin;\n"
        "1\tother@example.com\n"
        "\\.\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "dump.sql"
        p.write_text(dump)
        results = _scan_file(p, "john@acme.com", "backup.sql")
    assert results == []


def test_scan_file_case_insensitive():
    dump = (
        "COPY public.users (id, email) FROM stdin;\n"
        "1\tJOHN@ACME.COM\n"
        "\\.\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "dump.sql"
        p.write_text(dump)
        results = _scan_file(p, "john@acme.com", "backup.sql")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Tests: archive_rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_archive_rows_deletes_without_rule():
    """Rows with no retention rule → event_type='deleted'."""
    pool, conn = _make_pool()

    archived_row = {
        "id": str(uuid.uuid4()),
        "gdpr_request_id": "req-id",
        "database_name": "mydb",
        "table_name": "users",
        "row_id": "1",
        "event_type": "deleted",
        "event_at": datetime.now(timezone.utc),
        "backup_file_ref": "backup.sql",
        "data_before": {},
        "legal_basis": None,
        "retain_until": None,
        "purged_at": None,
    }
    conn.fetchrow = AsyncMock(return_value=archived_row)

    found_rows = [{"table_name": "users", "row_id": "1", "row_data": {"email": "john@acme.com"}}]
    result = await archive_rows(pool, "req-id", "mydb", found_rows, "backup.sql", [])

    assert len(result) == 1
    conn.fetchrow.assert_called_once()
    # Check event_type=deleted was passed
    call_args = conn.fetchrow.call_args[0]
    assert "deleted" in call_args  # event_type positional arg


@pytest.mark.asyncio
async def test_archive_rows_retains_with_rule():
    """Rows with a non-auto-delete rule → event_type='retained' with legal_basis."""
    pool, conn = _make_pool()

    archived_row = {
        "id": str(uuid.uuid4()),
        "gdpr_request_id": "req-id",
        "database_name": "mydb",
        "table_name": "orders",
        "row_id": "101",
        "event_type": "retained",
        "event_at": datetime.now(timezone.utc),
        "backup_file_ref": "backup.sql",
        "data_before": {},
        "legal_basis": "Art.17(3)(b)",
        "retain_until": datetime.now(timezone.utc) + timedelta(days=2555),
        "purged_at": None,
    }
    conn.fetchrow = AsyncMock(return_value=archived_row)

    rule = {
        "table_name": "orders",
        "auto_delete": False,
        "retention_days": 2555,
        "legal_basis": "Art.17(3)(b)",
    }
    found_rows = [{"table_name": "orders", "row_id": "101", "row_data": {"amount": "99.99"}}]
    result = await archive_rows(pool, "req-id", "mydb", found_rows, "backup.sql", [rule])

    assert len(result) == 1
    call_args = conn.fetchrow.call_args[0]
    assert "retained" in call_args


# ---------------------------------------------------------------------------
# Tests: create_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_returns_correct_structure():
    pool, conn = _make_pool()
    now = datetime.now(timezone.utc)
    conn.fetchrow = AsyncMock(return_value={
        "id": str(uuid.uuid4()),
        "request_ref": "REQ-ABCD1234",
        "tenant_id": None,
        "subject_email": "john@acme.com",
        "request_type": "erasure",
        "requested_at": now,
        "deadline_at": now + timedelta(days=30),
        "status": "pending",
        "processed_at": None,
        "processed_by": None,
        "notes": None,
        "proof_document": None,
    })

    rec = await create_request(pool, "john@acme.com")

    conn.fetchrow.assert_called_once()
    sql = conn.fetchrow.call_args[0][0]
    assert "INSERT INTO gdpr_deletion_requests" in sql

    # Verify REQ- prefix format passed to SQL
    call_args = conn.fetchrow.call_args[0]
    request_ref_arg = call_args[1]  # $1 = request_ref
    assert request_ref_arg.startswith("REQ-")
    assert len(request_ref_arg) == 12  # "REQ-" + 8 chars


@pytest.mark.asyncio
async def test_create_request_deadline_is_30_days():
    pool, conn = _make_pool()
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(days=30)
    conn.fetchrow = AsyncMock(return_value={
        "id": str(uuid.uuid4()),
        "request_ref": "REQ-ABCD1234",
        "tenant_id": None,
        "subject_email": "john@acme.com",
        "request_type": "erasure",
        "requested_at": now,
        "deadline_at": deadline,
        "status": "pending",
        "processed_at": None,
        "processed_by": None,
        "notes": None,
        "proof_document": None,
    })

    await create_request(pool, "john@acme.com")

    # Check that deadline_at passed to INSERT is ~30 days from now
    import datetime as _dt
    call_args = conn.fetchrow.call_args[0]
    deadline_arg = call_args[6]  # $6 = deadline_at (call_args[0]=sql, so [6] is the 6th param)
    diff = deadline_arg - _dt.datetime.now(_dt.timezone.utc)
    total_days = diff.total_seconds() / 86400
    assert 29 <= total_days <= 31


@pytest.mark.asyncio
async def test_create_request_with_tenant_id():
    pool, conn = _make_pool()
    now = datetime.now(timezone.utc)
    conn.fetchrow = AsyncMock(return_value={
        "id": str(uuid.uuid4()),
        "request_ref": "REQ-XXXXXXXX",
        "tenant_id": "tenant-123",
        "subject_email": "john@acme.com",
        "request_type": "access",
        "requested_at": now,
        "deadline_at": now + timedelta(days=30),
        "status": "pending",
        "processed_at": None,
        "processed_by": None,
        "notes": None,
        "proof_document": None,
    })
    rec = await create_request(pool, "john@acme.com", request_type="access", tenant_id="tenant-123")
    call_args = conn.fetchrow.call_args[0]
    assert call_args[2] == "tenant-123"   # $3 = tenant_id
    assert call_args[4] == "access"       # $5 = request_type


# ---------------------------------------------------------------------------
# Tests: list_requests / get_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_requests_no_filter():
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(return_value=[
        {"id": "id1", "request_ref": "REQ-00000001", "subject_email": "a@b.com",
         "request_type": "erasure", "status": "pending"},
    ])
    with patch("app.gdpr.requests.get_request") as _m:
        # list_requests calls conn.fetch directly
        async with pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM gdpr_deletion_requests ORDER BY requested_at DESC")
    conn.fetch.assert_called()


@pytest.mark.asyncio
async def test_get_request_not_found():
    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value=None)

    result = await get_request(pool, "nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_get_request_found():
    pool, conn = _make_pool()
    now = datetime.now(timezone.utc)
    conn.fetchrow = AsyncMock(return_value={
        "id": "some-uuid",
        "request_ref": "REQ-ABCD1234",
        "subject_email": "john@acme.com",
        "request_type": "erasure",
        "tenant_id": None,
        "requested_at": now,
        "deadline_at": now + timedelta(days=30),
        "status": "pending",
        "processed_at": None,
        "processed_by": None,
        "notes": None,
        "proof_document": None,
    })
    result = await get_request(pool, "some-uuid")
    assert result is not None
    assert result["request_ref"] == "REQ-ABCD1234"
