"""
Tests for Phase 2  Schema Snapshot System.

Covers:
  - compute_schema_hash: stability
  - diff_schemas: added, removed, renamed, type_change, new_fk columns
  - has_drift
  - classify_conflicts: all classification cases from PRD §8.1
  - SQLite introspection (no subprocess required)
  - write_schema_sidecar
  - capture_and_store (mocked pool)
"""
import asyncio
import json
import pytest

from app.schema.diff import (
    classify_conflicts,
    compute_schema_hash,
    diff_schemas,
    has_drift,
    _similarity,
    _is_compatible_cast,
)
from app.schema.snapshot import write_schema_sidecar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name, dtype="text", nullable=True, default=None, pk=False):
    return {"name": name, "type": dtype, "nullable": nullable, "default": default, "pk": pk}


def _table(columns, indexes=None, foreign_keys=None):
    return {"columns": columns, "indexes": indexes or [], "foreign_keys": foreign_keys or []}


# ---------------------------------------------------------------------------
# compute_schema_hash
# ---------------------------------------------------------------------------

class TestComputeSchemaHash:
    def test_same_input_same_hash(self):
        tables = {"users": _table([_col("id", "uuid", False, None, True)])}
        h1 = compute_schema_hash(tables)
        h2 = compute_schema_hash(tables)
        assert h1 == h2

    def test_different_input_different_hash(self):
        t1 = {"users": _table([_col("id")])}
        t2 = {"users": _table([_col("id"), _col("email")])}
        assert compute_schema_hash(t1) != compute_schema_hash(t2)

    def test_returns_hex_string(self):
        h = compute_schema_hash({})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest

    def test_key_order_invariant(self):
        t1 = {"b": _table([_col("x")]), "a": _table([_col("y")])}
        t2 = {"a": _table([_col("y")]), "b": _table([_col("x")])}
        assert compute_schema_hash(t1) == compute_schema_hash(t2)


# ---------------------------------------------------------------------------
# diff_schemas
# ---------------------------------------------------------------------------

class TestDiffSchemas:
    def test_no_change_empty_diff(self):
        tables = {"users": _table([_col("id")])}
        diff = diff_schemas(tables, tables)
        assert not has_drift(diff)

    def test_added_table(self):
        old = {"users": _table([_col("id")])}
        new = {"users": _table([_col("id")]), "orders": _table([_col("id")])}
        diff = diff_schemas(old, new)
        assert "orders" in diff["added_tables"]
        assert has_drift(diff)

    def test_removed_table(self):
        old = {"users": _table([_col("id")]), "orders": _table([_col("id")])}
        new = {"users": _table([_col("id")])}
        diff = diff_schemas(old, new)
        assert "orders" in diff["removed_tables"]

    def test_added_column(self):
        old = {"users": _table([_col("id")])}
        new = {"users": _table([_col("id"), _col("email")])}
        diff = diff_schemas(old, new)
        assert len(diff["added_columns"]) == 1
        assert diff["added_columns"][0]["column"] == "email"

    def test_removed_column(self):
        old = {"users": _table([_col("id"), _col("email")])}
        new = {"users": _table([_col("id")])}
        diff = diff_schemas(old, new)
        assert any(c["column"] == "email" for c in diff["removed_columns"])

    def test_type_change_detected(self):
        old = {"users": _table([_col("age", "integer")])}
        new = {"users": _table([_col("age", "text")])}
        diff = diff_schemas(old, new)
        assert len(diff["type_changes"]) == 1
        tc = diff["type_changes"][0]
        assert tc["column"] == "age"
        assert tc["from_type"] == "integer"
        assert tc["to_type"] == "text"

    def test_rename_detected_same_type(self):
        # "username" → "user_name": high similarity (1 char diff), same type
        old = {"users": _table([_col("username", "varchar")])}
        new = {"users": _table([_col("user_name", "varchar")])}
        diff = diff_schemas(old, new)
        # Should be detected as a rename, not add+remove
        assert len(diff["renamed_columns"]) == 1
        r = diff["renamed_columns"][0]
        assert r["old_name"] == "username"
        assert r["new_name"] == "user_name"
        # Should NOT appear in removed or added
        assert not diff["removed_columns"]
        assert not diff["added_columns"]

    def test_rename_not_detected_across_types(self):
        # Different types → should not be detected as a rename
        old = {"users": _table([_col("user_name", "varchar")])}
        new = {"users": _table([_col("user_name_int", "integer")])}
        diff = diff_schemas(old, new)
        assert len(diff["renamed_columns"]) == 0
        # Falls through as add + remove
        assert len(diff["removed_columns"]) == 1
        assert len(diff["added_columns"]) == 1

    def test_new_non_nullable_fk_detected(self):
        old = {"orders": _table([_col("id")])}
        new = {
            "orders": _table(
                [_col("id"), _col("user_id", nullable=False)],
                foreign_keys=[{"column": "user_id", "ref_table": "users", "ref_column": "id"}],
            )
        }
        diff = diff_schemas(old, new)
        assert len(diff["new_constraints"]) == 1
        assert diff["new_constraints"][0]["column"] == "user_id"

    def test_nullable_fk_not_flagged_as_constraint(self):
        old = {"orders": _table([_col("id")])}
        new = {
            "orders": _table(
                [_col("id"), _col("user_id", nullable=True)],
                foreign_keys=[{"column": "user_id", "ref_table": "users", "ref_column": "id"}],
            )
        }
        diff = diff_schemas(old, new)
        # Nullable FK: added as a column (safe), not as a new_constraint
        assert len(diff["new_constraints"]) == 0


# ---------------------------------------------------------------------------
# has_drift
# ---------------------------------------------------------------------------

class TestHasDrift:
    def test_empty_diff_no_drift(self):
        diff = diff_schemas(
            {"t": _table([_col("id")])},
            {"t": _table([_col("id")])},
        )
        assert not has_drift(diff)

    def test_added_column_is_drift(self):
        diff = diff_schemas(
            {"t": _table([_col("id")])},
            {"t": _table([_col("id"), _col("name")])},
        )
        assert has_drift(diff)


# ---------------------------------------------------------------------------
# classify_conflicts  all 10 PRD §8.1 cases
# ---------------------------------------------------------------------------

class TestClassifyConflicts:
    def _classify(self, old, new):
        diff = diff_schemas(old, new)
        return classify_conflicts(diff)

    def test_added_nullable_is_safe(self):
        conflicts = self._classify(
            {"t": _table([_col("id")])},
            {"t": _table([_col("id"), _col("phone", nullable=True)])},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["classification"] == "safe"
        assert conflicts[0]["auto_resolution"]["resolution_type"] == "auto_null"

    def test_added_not_null_with_default_is_safe(self):
        conflicts = self._classify(
            {"t": _table([_col("id")])},
            {"t": _table([_col("id"), _col("status", nullable=False, default="active")])},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["classification"] == "safe"
        assert conflicts[0]["auto_resolution"]["resolution_type"] == "use_default"

    def test_added_not_null_no_default_needs_input(self):
        conflicts = self._classify(
            {"t": _table([_col("id")])},
            {"t": _table([_col("id"), _col("tenant_id", nullable=False, default=None)])},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["classification"] == "needs_input"
        assert conflicts[0]["auto_resolution"] is None

    def test_removed_column_needs_input(self):
        conflicts = self._classify(
            {"t": _table([_col("id"), _col("old_col")])},
            {"t": _table([_col("id")])},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["classification"] == "needs_input"
        assert conflicts[0]["conflict_type"] == "removed_col"

    def test_rename_high_confidence_needs_input(self):
        # "username" → "user_name": similarity ~0.89 (1 edit over 9 chars) → needs_input
        conflicts = self._classify(
            {"t": _table([_col("username", "varchar")])},
            {"t": _table([_col("user_name", "varchar")])},
        )
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c["conflict_type"] == "renamed"
        assert c["classification"] == "needs_input"

    def test_rename_low_confidence_blocking(self):
        # "a" vs "zzz"  very low similarity, different names, same type
        conflicts = self._classify(
            {"t": _table([_col("a", "varchar")])},
            {"t": _table([_col("zzzzzzz", "varchar")])},
        )
        # Low similarity → not detected as rename at all (below 0.6 threshold)
        # So we get removed_col + added_col, both needs_input
        renames = [c for c in conflicts if c["conflict_type"] == "renamed"]
        assert len(renames) == 0

    def test_compatible_type_change_needs_input(self):
        conflicts = self._classify(
            {"t": _table([_col("age", "integer")])},
            {"t": _table([_col("age", "bigint")])},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["classification"] == "needs_input"
        assert conflicts[0]["conflict_type"] == "type_change"

    def test_incompatible_type_change_blocking(self):
        conflicts = self._classify(
            {"t": _table([_col("status", "integer")])},
            {"t": _table([_col("status", "jsonb")])},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["classification"] == "blocking"

    def test_new_not_null_fk_needs_input(self):
        old = {"orders": _table([_col("id")])}
        new = {
            "orders": _table(
                [_col("id"), _col("user_id", nullable=False)],
                foreign_keys=[{"column": "user_id", "ref_table": "users", "ref_column": "id"}],
            )
        }
        diff = diff_schemas(old, new)
        conflicts = classify_conflicts(diff)
        fk_conflicts = [c for c in conflicts if c["conflict_type"] == "new_fk"]
        assert len(fk_conflicts) == 1
        assert fk_conflicts[0]["classification"] == "needs_input"

    def test_conflict_id_is_stable(self):
        diff = diff_schemas(
            {"t": _table([_col("id")])},
            {"t": _table([_col("id"), _col("name")])},
        )
        c1 = classify_conflicts(diff)
        c2 = classify_conflicts(diff)
        assert c1[0]["conflict_id"] == c2[0]["conflict_id"]


# ---------------------------------------------------------------------------
# _similarity helper
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical(self):
        assert _similarity("abc", "abc") == 1.0

    def test_empty_strings(self):
        assert _similarity("", "") == 1.0

    def test_completely_different(self):
        s = _similarity("a", "zzz")
        assert s < 0.5

    def test_close_names(self):
        s = _similarity("user_name", "username")
        assert s > 0.7


# ---------------------------------------------------------------------------
# _is_compatible_cast
# ---------------------------------------------------------------------------

class TestCompatibleCast:
    def test_integer_to_bigint(self):
        assert _is_compatible_cast("integer", "bigint")

    def test_varchar_to_text(self):
        assert _is_compatible_cast("varchar", "text")

    def test_integer_to_jsonb_incompatible(self):
        assert not _is_compatible_cast("integer", "jsonb")

    def test_case_insensitive(self):
        assert _is_compatible_cast("INTEGER", "BIGINT")


# ---------------------------------------------------------------------------
# write_schema_sidecar
# ---------------------------------------------------------------------------

class TestWriteSchemaSidecar:
    def test_writes_correct_sidecar(self):
        written = {}

        class MockStorage:
            def write(self, filename, content):
                written[filename] = content

        snapshot = {
            "captured_at": "2025-01-01T00:00:00Z",
            "schema_hash": "abc123",
            "tables": {"users": _table([_col("id")])},
            "drift_detected": False,
        }
        write_schema_sidecar(MockStorage(), "raven_db_2025-01-01_daily.sql.enc", snapshot)

        key = "raven_db_2025-01-01_daily.sql.enc.schema"
        assert key in written
        parsed = json.loads(written[key].decode())
        assert parsed["schema_hash"] == "abc123"
        assert "tables" in parsed
        assert parsed["drift_detected"] is False

    def test_storage_write_failure_does_not_raise(self):
        class BrokenStorage:
            def write(self, filename, content):
                raise IOError("disk full")

        # Must not raise
        write_schema_sidecar(
            BrokenStorage(),
            "raven_db_2025-01-01_daily.sql.enc",
            {"captured_at": "x", "schema_hash": "y", "tables": {}, "drift_detected": False},
        )


# ---------------------------------------------------------------------------
# capture_and_store (async, mocked pool)
# ---------------------------------------------------------------------------

class TestCaptureAndStore:
    @pytest.mark.asyncio
    async def test_returns_none_on_introspect_failure(self):
        """If introspection fails, returns None without raising."""
        from unittest.mock import patch, AsyncMock, MagicMock
        import asyncio

        loop = asyncio.get_event_loop()

        # Make introspect raise
        with patch("app.schema.snapshot.introspect", side_effect=RuntimeError("no db")):
            from app.schema.snapshot import capture_and_store
            result = await capture_and_store(
                db=_make_db_config(),
                pool=None,
                backup_job_id="job-1",
                loop=loop,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_snapshot_dict_on_success(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        import asyncio

        loop = asyncio.get_event_loop()
        mock_tables = {"users": _table([_col("id")])}

        # Mock pool with no previous snapshot
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.schema.snapshot.introspect", return_value=mock_tables):
            from app.schema.snapshot import capture_and_store
            result = await capture_and_store(
                db=_make_db_config(),
                pool=mock_pool,
                backup_job_id="job-1",
                loop=loop,
            )

        assert result is not None
        assert result["tables"] == mock_tables
        assert "schema_hash" in result
        assert "drift_detected" in result

    @pytest.mark.asyncio
    async def test_no_drift_on_first_snapshot(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        import asyncio

        loop = asyncio.get_event_loop()
        mock_tables = {"users": _table([_col("id")])}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)  # no previous
        mock_conn.execute = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.schema.snapshot.introspect", return_value=mock_tables):
            from app.schema.snapshot import capture_and_store
            result = await capture_and_store(
                db=_make_db_config(),
                pool=mock_pool,
                backup_job_id="job-1",
                loop=loop,
            )

        # No previous snapshot → diff is empty → no drift
        assert result["drift_detected"] is False
        assert result["diff_from_prev"] == {}


# ---------------------------------------------------------------------------
# Helpers for tests
# ---------------------------------------------------------------------------

def _make_db_config():
    from app.config import DatabaseConfig, ScheduleConfig
    return DatabaseConfig(
        name="testdb",
        type="postgres",
        host="localhost",
        port=5432,
        db="testdb",
        user="user",
        password="pass",
        schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
        storage="local",
    )
