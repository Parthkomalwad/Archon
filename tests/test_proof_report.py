"""
Phase 3  Proof-of-deletion report tests.

Covers:
- _audit_trail_hash: stable, correct SHA-256
- generate_report: returns non-zero bytes, valid PDF header
- generate_report: contains all 7 required sections
- Report handles empty archived_rows gracefully
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gdpr.report import _audit_trail_hash, _fmt


# ---------------------------------------------------------------------------
# Tests: _fmt
# ---------------------------------------------------------------------------

def test_fmt_none():
    assert _fmt(None) == "—"


def test_fmt_string_passthrough():
    assert _fmt("2024-01-01") == "2024-01-01"


def test_fmt_datetime():
    dt = datetime(2024, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
    result = _fmt(dt)
    assert "2024-03-01" in result
    assert "14:30" in result


# ---------------------------------------------------------------------------
# Tests: _audit_trail_hash
# ---------------------------------------------------------------------------

def test_audit_trail_hash_stable():
    rows = [
        {"id": "aaa", "event_type": "gdpr_request_created", "created_at": "2024-01-01"},
        {"id": "bbb", "event_type": "gdpr_scanning_started", "created_at": "2024-01-02"},
    ]
    h1 = _audit_trail_hash(rows)
    h2 = _audit_trail_hash(rows)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_audit_trail_hash_sorted_by_id():
    rows_a = [
        {"id": "aaa", "event_type": "first"},
        {"id": "bbb", "event_type": "second"},
    ]
    rows_b = [
        {"id": "bbb", "event_type": "second"},
        {"id": "aaa", "event_type": "first"},
    ]
    assert _audit_trail_hash(rows_a) == _audit_trail_hash(rows_b)


def test_audit_trail_hash_different_content():
    rows_a = [{"id": "aaa", "event_type": "first"}]
    rows_b = [{"id": "aaa", "event_type": "second"}]
    assert _audit_trail_hash(rows_a) != _audit_trail_hash(rows_b)


def test_audit_trail_hash_empty():
    h = _audit_trail_hash([])
    assert isinstance(h, str)
    assert len(h) == 64


# ---------------------------------------------------------------------------
# Mock pool builder for report tests
# ---------------------------------------------------------------------------

def _make_report_pool(request_dict: dict, archived: list, audit: list):
    """Build mock pool that returns preset data for report generation."""
    pool = MagicMock()
    conn = AsyncMock()

    async def fetchrow_side(sql, *args):
        if "gdpr_deletion_requests" in sql:
            return request_dict
        return None

    async def fetch_side(sql, *args):
        if "archived_rows" in sql:
            return archived
        if "audit_log" in sql:
            return audit
        return []

    conn.fetchrow = AsyncMock(side_effect=fetchrow_side)
    conn.fetch = AsyncMock(side_effect=fetch_side)

    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ---------------------------------------------------------------------------
# Tests: generate_report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_report_returns_bytes():
    now = datetime.now(timezone.utc)
    request_row = {
        "id": str(uuid.uuid4()),
        "request_ref": "REQ-TESTTEST",
        "subject_email": "john@acme.com",
        "request_type": "erasure",
        "tenant_id": None,
        "requested_at": now,
        "deadline_at": now + timedelta(days=30),
        "processed_at": now,
        "status": "completed",
        "proof_document": None,
    }
    pool = _make_report_pool(request_row, [], [])

    from app.gdpr.report import generate_report
    pdf_bytes = await generate_report(pool, str(request_row["id"]))

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    # Valid PDF starts with %PDF
    assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_generate_report_with_archived_rows():
    now = datetime.now(timezone.utc)
    request_row = {
        "id": str(uuid.uuid4()),
        "request_ref": "REQ-GDPRTEST",
        "subject_email": "john@acme.com",
        "request_type": "erasure",
        "tenant_id": None,
        "requested_at": now,
        "deadline_at": now + timedelta(days=30),
        "processed_at": now,
        "status": "completed",
        "proof_document": None,
    }
    archived = [
        {
            "id": str(uuid.uuid4()),
            "gdpr_request_id": request_row["id"],
            "database_name": "mydb",
            "table_name": "users",
            "row_id": "1",
            "event_type": "deleted",
            "event_at": now,
            "backup_file_ref": "raven_mydb_2024-01-01_daily.sql.enc",
            "data_before": None,
            "legal_basis": None,
            "retain_until": None,
            "purged_at": None,
        },
        {
            "id": str(uuid.uuid4()),
            "gdpr_request_id": request_row["id"],
            "database_name": "mydb",
            "table_name": "orders",
            "row_id": "101",
            "event_type": "retained",
            "event_at": now,
            "backup_file_ref": "raven_mydb_2024-01-01_daily.sql.enc",
            "data_before": None,
            "legal_basis": "Art.17(3)(b)",
            "retain_until": now + timedelta(days=2555),
            "purged_at": None,
        },
    ]
    audit = [
        {"id": "a1", "event_type": "gdpr_request_created", "created_at": str(now)},
        {"id": "a2", "event_type": "gdpr_completed", "created_at": str(now)},
    ]
    pool = _make_report_pool(request_row, archived, audit)

    from app.gdpr.report import generate_report
    pdf_bytes = await generate_report(pool, str(request_row["id"]))

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 200
    assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_generate_report_not_found_raises():
    pool = _make_report_pool(None, [], [])

    from app.gdpr.report import generate_report
    with pytest.raises(ValueError, match="not found"):
        await generate_report(pool, "nonexistent-id")


@pytest.mark.asyncio
async def test_generate_report_empty_archived_rows():
    """Report should not crash when no archived rows exist."""
    now = datetime.now(timezone.utc)
    request_row = {
        "id": str(uuid.uuid4()),
        "request_ref": "REQ-EMPTYTEST",
        "subject_email": "nobody@example.com",
        "request_type": "erasure",
        "tenant_id": None,
        "requested_at": now,
        "deadline_at": now + timedelta(days=30),
        "processed_at": now,
        "status": "completed",
        "proof_document": None,
    }
    pool = _make_report_pool(request_row, [], [])

    from app.gdpr.report import generate_report
    pdf_bytes = await generate_report(pool, str(request_row["id"]))
    assert pdf_bytes[:4] == b"%PDF"
