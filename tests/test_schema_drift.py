"""
Phase 4  Schema drift resolution tests.

Covers:
- classify_conflicts: all 5 conflict types + correct classification levels
- classify_diff: database_name injection
- apply_resolution: all 6 resolution strategies produce correct SQL
- save_resolution: correct upsert SQL called
- load_saved_resolutions: maps rows to conflict_id keys
- _parse_sql_statements: handles COPY blocks and plain statements
- _apply_resolutions_to_sql: prefixes ALTER stmts, skips safe auto-resolutions
- _collect_table_stats: counts tables and rows
"""
from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schema.diff import classify_conflicts, diff_schemas, has_drift, _make_conflict
from app.drift.classify import classify_diff
from app.drift.resolve import apply_resolution, load_saved_resolutions, save_resolution
from app.drift.preview import (
    _parse_sql_statements,
    _apply_resolutions_to_sql,
    _collect_table_stats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conflict_id(table: str, column: str, conflict_type: str) -> str:
    return hashlib.sha256(f"{table}|{column}|{conflict_type}".encode()).hexdigest()[:16]


def _make_pool_with_rows(rows):
    """Return a mock pool whose conn.fetch() returns `rows`."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.execute = AsyncMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ---------------------------------------------------------------------------
# classify_conflicts  added_col (safe: nullable)
# ---------------------------------------------------------------------------

def test_added_col_nullable_is_safe():
    diff = {
        "added_columns": [{"table": "users", "column": "bio", "type": "text", "nullable": True, "has_default": False}],
        "removed_columns": [], "renamed_columns": [], "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["conflict_type"] == "added_col"
    assert c["classification"] == "safe"
    assert c["auto_resolution"] == {"resolution_type": "auto_null"}


def test_added_col_with_default_is_safe():
    diff = {
        "added_columns": [{"table": "orders", "column": "flag", "type": "boolean", "nullable": False, "has_default": True}],
        "removed_columns": [], "renamed_columns": [], "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["classification"] == "safe"
    assert c["auto_resolution"] == {"resolution_type": "use_default"}


def test_added_col_not_null_no_default_is_needs_input():
    diff = {
        "added_columns": [{"table": "users", "column": "age", "type": "integer", "nullable": False, "has_default": False}],
        "removed_columns": [], "renamed_columns": [], "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["classification"] == "needs_input"
    assert c["auto_resolution"] is None


# ---------------------------------------------------------------------------
# classify_conflicts  removed_col
# ---------------------------------------------------------------------------

def test_removed_col_is_needs_input():
    diff = {
        "added_columns": [],
        "removed_columns": [{"table": "users", "column": "old_field"}],
        "renamed_columns": [], "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["conflict_type"] == "removed_col"
    assert c["classification"] == "needs_input"


# ---------------------------------------------------------------------------
# classify_conflicts  renamed_col
# ---------------------------------------------------------------------------

def test_renamed_col_high_confidence_is_needs_input():
    diff = {
        "added_columns": [], "removed_columns": [],
        "renamed_columns": [{"table": "users", "old_name": "firstname", "new_name": "first_name", "confidence": 0.9}],
        "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["conflict_type"] == "renamed"
    assert c["classification"] == "needs_input"  # confidence >= 0.8


def test_renamed_col_low_confidence_is_blocking():
    diff = {
        "added_columns": [], "removed_columns": [],
        "renamed_columns": [{"table": "users", "old_name": "foo", "new_name": "completely_different", "confidence": 0.5}],
        "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["classification"] == "blocking"


# ---------------------------------------------------------------------------
# classify_conflicts  type_change
# ---------------------------------------------------------------------------

def test_type_change_compatible_is_needs_input():
    diff = {
        "added_columns": [], "removed_columns": [], "renamed_columns": [],
        "type_changes": [{"table": "products", "column": "price", "from_type": "integer", "to_type": "bigint"}],
        "new_constraints": [], "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["conflict_type"] == "type_change"
    assert c["classification"] == "needs_input"


def test_type_change_incompatible_is_blocking():
    diff = {
        "added_columns": [], "removed_columns": [], "renamed_columns": [],
        "type_changes": [{"table": "products", "column": "uid", "from_type": "integer", "to_type": "uuid"}],
        "new_constraints": [], "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["classification"] == "blocking"


# ---------------------------------------------------------------------------
# classify_conflicts  new_fk
# ---------------------------------------------------------------------------

def test_new_fk_is_needs_input():
    diff = {
        "added_columns": [], "removed_columns": [], "renamed_columns": [], "type_changes": [],
        "new_constraints": [{"table": "orders", "column": "user_id", "constraint_type": "FOREIGN KEY NOT NULL", "ref_table": "users", "ref_column": "id"}],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_conflicts(diff)
    c = conflicts[0]
    assert c["conflict_type"] == "new_fk"
    assert c["classification"] == "needs_input"


# ---------------------------------------------------------------------------
# classify_diff  database_name injection
# ---------------------------------------------------------------------------

def test_classify_diff_injects_database_name():
    diff = {
        "added_columns": [{"table": "users", "column": "bio", "type": "text", "nullable": True, "has_default": False}],
        "removed_columns": [], "renamed_columns": [], "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_diff(diff, database_name="mydb")
    assert all(c["database_name"] == "mydb" for c in conflicts)


def test_classify_diff_empty_database_name():
    diff = {
        "added_columns": [{"table": "t", "column": "c", "type": "text", "nullable": True, "has_default": False}],
        "removed_columns": [], "renamed_columns": [], "type_changes": [], "new_constraints": [],
        "added_tables": [], "removed_tables": [],
    }
    conflicts = classify_diff(diff)
    assert conflicts[0]["database_name"] == ""


# ---------------------------------------------------------------------------
# apply_resolution  all 6 strategies
# ---------------------------------------------------------------------------

def _added_conflict(table="users", column="bio", col_type="text"):
    return {
        "table_name": table,
        "column_name": column,
        "conflict_type": "added_col",
        "classification": "safe",
        "details": {"type": col_type, "nullable": True, "has_default": False},
        "auto_resolution": {"resolution_type": "auto_null"},
    }


def test_apply_resolution_auto_null():
    sql = apply_resolution(_added_conflict(), {"resolution_type": "auto_null"})
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "DEFAULT NULL" in sql
    assert '"bio"' in sql
    assert '"users"' in sql


def test_apply_resolution_use_default():
    sql = apply_resolution(_added_conflict(), {"resolution_type": "use_default"})
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "DEFAULT NULL" not in sql
    assert "text" in sql


def test_apply_resolution_default_value_string():
    sql = apply_resolution(_added_conflict(), {"resolution_type": "default_value", "resolution_value": {"value": "unknown"}})
    assert "DEFAULT 'unknown'" in sql


def test_apply_resolution_default_value_numeric():
    sql = apply_resolution(
        _added_conflict(col_type="integer"),
        {"resolution_type": "default_value", "resolution_value": {"value": 0}},
    )
    assert "DEFAULT 0" in sql


def test_apply_resolution_manual_map():
    conflict = {
        "table_name": "users",
        "column_name": "firstname",
        "conflict_type": "renamed",
        "details": {"old_name": "firstname", "new_name": "first_name"},
    }
    sql = apply_resolution(conflict, {"resolution_type": "manual_map", "resolution_value": {"new_name": "first_name"}})
    assert "RENAME COLUMN" in sql
    assert '"firstname"' in sql
    assert '"first_name"' in sql


def test_apply_resolution_type_cast():
    conflict = {
        "table_name": "orders",
        "column_name": "amount",
        "conflict_type": "type_change",
        "details": {"from_type": "integer", "to_type": "bigint"},
    }
    sql = apply_resolution(conflict, {"resolution_type": "type_cast", "resolution_value": {"new_type": "bigint"}})
    assert "ALTER COLUMN" in sql
    assert "TYPE bigint" in sql
    assert "USING" in sql


def test_apply_resolution_skip_returns_empty():
    conflict = _added_conflict()
    sql = apply_resolution(conflict, {"resolution_type": "skip"})
    assert sql == ""


def test_apply_resolution_unknown_type_returns_comment():
    conflict = _added_conflict()
    sql = apply_resolution(conflict, {"resolution_type": "unknown_xyz"})
    assert sql.startswith("--")


# ---------------------------------------------------------------------------
# save_resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_resolution_calls_execute():
    pool, conn = _make_pool_with_rows([])
    await save_resolution(
        pool,
        database_name="mydb",
        table_name="users",
        column_name="bio",
        conflict_type="added_col",
        resolution_type="auto_null",
        resolution_value=None,
    )
    assert conn.execute.called
    call_sql = conn.execute.call_args[0][0]
    assert "INSERT INTO schema_conflict_resolutions" in call_sql
    assert "ON CONFLICT" in call_sql


@pytest.mark.asyncio
async def test_save_resolution_passes_json_value():
    pool, conn = _make_pool_with_rows([])
    await save_resolution(
        pool,
        database_name="mydb",
        table_name="t",
        column_name="c",
        conflict_type="type_change",
        resolution_type="type_cast",
        resolution_value={"new_type": "bigint"},
    )
    # resolution_value is passed as JSON string (5th positional arg after SQL)
    call_args = conn.execute.call_args[0]
    import json
    json_arg = call_args[-1]
    parsed = json.loads(json_arg)
    assert parsed == {"new_type": "bigint"}


# ---------------------------------------------------------------------------
# load_saved_resolutions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_saved_resolutions_maps_to_conflict_id():
    cid = _conflict_id("users", "bio", "added_col")
    conflicts = [{
        "conflict_id": cid,
        "table_name": "users",
        "column_name": "bio",
        "conflict_type": "added_col",
    }]
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "table_name": "users",
        "column_name": "bio",
        "conflict_type": "added_col",
        "resolution_type": "auto_null",
        "resolution_value": None,
    }[k]

    pool, conn = _make_pool_with_rows([row])
    result = await load_saved_resolutions(pool, "mydb", conflicts)
    assert cid in result
    assert result[cid]["resolution_type"] == "auto_null"


@pytest.mark.asyncio
async def test_load_saved_resolutions_returns_empty_for_no_match():
    cid = _conflict_id("users", "bio", "added_col")
    conflicts = [{
        "conflict_id": cid,
        "table_name": "users",
        "column_name": "bio",
        "conflict_type": "added_col",
    }]
    # Row has a different column  won't match any conflict
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "table_name": "orders",
        "column_name": "total",
        "conflict_type": "added_col",
        "resolution_type": "auto_null",
        "resolution_value": None,
    }[k]

    pool, conn = _make_pool_with_rows([row])
    result = await load_saved_resolutions(pool, "mydb", conflicts)
    assert result == {}


@pytest.mark.asyncio
async def test_load_saved_resolutions_returns_empty_if_no_pool():
    result = await load_saved_resolutions(None, "mydb", [])
    assert result == {}


# ---------------------------------------------------------------------------
# _parse_sql_statements
# ---------------------------------------------------------------------------

def test_parse_sql_statements_simple():
    sql = "SELECT 1;\nSELECT 2;\n"
    stmts = _parse_sql_statements(sql)
    assert len(stmts) == 2


def test_parse_sql_statements_copy_block():
    sql = (
        "CREATE TABLE users (id INT);\n"
        "COPY users FROM stdin;\n"
        "1\tAlice\n"
        "2\tBob\n"
        "\\.\n"
        "SELECT 3;\n"
    )
    stmts = _parse_sql_statements(sql)
    # 3 statements: CREATE, COPY block, SELECT
    assert len(stmts) == 3
    copy_stmt = next(s for s in stmts if "COPY" in s)
    assert "\\." in copy_stmt


def test_parse_sql_statements_empty_input():
    assert _parse_sql_statements("") == []


# ---------------------------------------------------------------------------
# _apply_resolutions_to_sql
# ---------------------------------------------------------------------------

def test_apply_resolutions_to_sql_prepends_alters():
    conflict = _added_conflict()
    conflict["conflict_id"] = _conflict_id("users", "bio", "added_col")
    resolutions = {conflict["conflict_id"]: {"resolution_type": "auto_null"}}
    result_sql, warnings = _apply_resolutions_to_sql("SELECT 1;", [conflict], resolutions)
    assert "ALTER TABLE" in result_sql
    assert "SELECT 1;" in result_sql
    assert result_sql.index("ALTER TABLE") < result_sql.index("SELECT 1;")
    assert warnings == []


def test_apply_resolutions_to_sql_uses_auto_resolution_for_safe():
    conflict = _added_conflict()
    conflict["conflict_id"] = _conflict_id("users", "bio", "added_col")
    # No explicit resolution passed  auto_resolution should be used
    result_sql, warnings = _apply_resolutions_to_sql("SELECT 1;", [conflict], {})
    assert "ALTER TABLE" in result_sql
    assert warnings == []


def test_apply_resolutions_to_sql_warns_on_unresolved_blocking():
    conflict = {
        "conflict_id": _conflict_id("users", "age", "added_col"),
        "conflict_type": "added_col",
        "table_name": "users",
        "column_name": "age",
        "classification": "blocking",
        "details": {"type": "integer", "nullable": False, "has_default": False},
        "auto_resolution": None,
    }
    _, warnings = _apply_resolutions_to_sql("SELECT 1;", [conflict], {})
    assert len(warnings) == 1
    assert "users.age" in warnings[0]


def test_apply_resolutions_to_sql_skip_produces_no_alter():
    conflict = _added_conflict()
    conflict["conflict_id"] = _conflict_id("users", "bio", "added_col")
    # Override auto_resolution with skip
    resolutions = {conflict["conflict_id"]: {"resolution_type": "skip"}}
    result_sql, warnings = _apply_resolutions_to_sql("SELECT 1;", [conflict], resolutions)
    assert "ALTER TABLE" not in result_sql


# ---------------------------------------------------------------------------
# _collect_table_stats
# ---------------------------------------------------------------------------

def test_collect_table_stats_finds_create_and_insert():
    sql = (
        'CREATE TABLE "users" (id INT);\n'
        'INSERT INTO "orders" VALUES (1);\n'
        'INSERT INTO orders VALUES (2);\n'
    )
    tables, rows = _collect_table_stats(sql)
    assert "users" in tables
    assert "orders" in tables
    assert rows == 2  # 2 INSERT lines


def test_collect_table_stats_finds_copy_rows():
    sql = (
        "COPY users FROM stdin;\n"
        "1\tAlice\n"
        "2\tBob\n"
        "\\.\n"
    )
    tables, rows = _collect_table_stats(sql)
    assert "users" in tables
    # tab-separated data lines counted as rows
    assert rows == 2


def test_collect_table_stats_empty():
    tables, rows = _collect_table_stats("")
    assert tables == []
    assert rows == 0
