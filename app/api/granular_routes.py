"""
app/api/granular_routes.py  Granular (row-level / table-level) restore API.

Endpoints:
  POST   /granular/session                               parse backup → session
  GET    /granular/session/{id}/tables                   list tables + row counts
  GET    /granular/session/{id}/table/{table}/rows       paginated row browser
  POST   /granular/session/{id}/resolve                  FK dependency walk
  POST   /granular/session/{id}/restore                  apply rows to live DB
  DELETE /granular/session/{id}                          clean up session
"""

import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import AppConfig, DatabaseConfig
from app.encryption import EncryptionService
from app.granular import (
    GranularSessionStore,
    generate_restore_sql,
    parse_sql_dump,
    resolve_dependencies,
)
from app.logger import log
from app.storage import get_storage

granular_router = APIRouter(prefix="/granular", tags=["granular"])


# ─── Filename parser (mirrors routes.py  kept local to avoid circular import) ─

_FILENAME_RE = re.compile(
    r"^(?:archon|raven|backops)_(?P<db_name>.+)_(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})"
    r"_(?P<rotation>hourly|daily|weekly|monthly)\.(?P<ext>sql|archive|db)(?P<enc>\.enc)?$"
)


def _parse_filename(filename: str) -> Optional[dict]:
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
    for db in config.databases:
        if db.name == db_name:
            return db
    return None


def _get_store(request: Request) -> GranularSessionStore:
    return request.app.state.granular_store


# ─── Request / Response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    filename: str


class TableSummary(BaseModel):
    name: str
    row_count: int
    columns: list[str]
    fk_count: int


class CreateSessionResponse(BaseModel):
    session_id: str
    db_name: str
    db_type: str
    tables: list[TableSummary]


class RowsResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class FKDep(BaseModel):
    table: str
    row_count: int
    rows: list[dict[str, Any]]


class ResolveRequest(BaseModel):
    table: str
    row_indices: list[int]


class ResolveResponse(BaseModel):
    total_rows: int
    dependencies: list[FKDep]


class GranularRestoreRequest(BaseModel):
    table: str
    row_indices: list[int]
    strategy: str = "skip"   # "skip" | "replace" | "merge"
    confirm: bool = False


class GranularRestoreResponse(BaseModel):
    status: str
    rows_applied: int
    tables_affected: list[str]


# ─── Multi-table models ────────────────────────────────────────────────────────

class MultiTableEntry(BaseModel):
    """One table + the row indices selected from it."""
    table: str
    row_indices: list[int]


class MultiResolveRequest(BaseModel):
    tables: list[MultiTableEntry]


class MultiRestoreRequest(BaseModel):
    tables: list[MultiTableEntry]
    strategy: str = "skip"
    confirm: bool = False


# ─── POST /granular/session ────────────────────────────────────────────────────

@granular_router.post("/session", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    request: Request,
) -> CreateSessionResponse:
    """
    Decrypt and parse a backup file into an in-memory session.
    The session holds the full parsed table data for interactive row browsing.
    Expires after 30 minutes of inactivity.
    """
    config: AppConfig = request.app.state.config
    store: GranularSessionStore = _get_store(request)
    loop = asyncio.get_running_loop()

    meta = _parse_filename(body.filename)
    if not meta:
        raise HTTPException(status_code=400, detail=f"Cannot parse filename: {body.filename}")

    db_config = _find_db(config, meta["db_name"])
    if not db_config:
        raise HTTPException(
            status_code=404,
            detail=f"Database '{meta['db_name']}' not found in config",
        )

    if db_config.type not in ("mysql", "postgres"):
        raise HTTPException(
            status_code=400,
            detail=f"Granular restore is supported for mysql and postgres only, got '{db_config.type}'",
        )

    storage = get_storage(config.storage_backends[db_config.storage])
    enc = EncryptionService(config.encryption)

    # Download the backup file
    tmpdir = tempfile.mkdtemp(prefix="archon_granular_")
    tmp_enc = Path(tmpdir) / "backup.enc"
    tmp_raw = Path(tmpdir) / "backup.sql"

    try:
        # Download (stream to disk)
        try:
            await loop.run_in_executor(None, storage.read_stream, body.filename, tmp_enc)
        except Exception:
            raise HTTPException(
                status_code=404,
                detail=f"Backup file '{body.filename}' not found in storage",
            )

        # Decrypt if needed
        if meta["encrypted"]:
            try:
                await loop.run_in_executor(None, enc.decrypt_stream, tmp_enc, tmp_raw)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Decryption failed: {e}")
        else:
            tmp_raw = tmp_enc

        # Parse the SQL dump
        sql_content = tmp_raw.read_text(errors="replace")
        try:
            tables = await loop.run_in_executor(
                None, parse_sql_dump, sql_content, db_config.type
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse SQL dump: {e}")

    finally:
        # Cleanup temp files
        for f in Path(tmpdir).iterdir():
            f.unlink(missing_ok=True)
        Path(tmpdir).rmdir()

    session = await store.create(body.filename, db_config.name, db_config.type, tables)

    return CreateSessionResponse(
        session_id=session.session_id,
        db_name=db_config.name,
        db_type=db_config.type,
        tables=sorted(
            [
                TableSummary(
                    name=t.name,
                    row_count=t.row_count,
                    columns=t.columns,
                    fk_count=len(t.fk_constraints),
                )
                for t in tables.values()
            ],
            key=lambda x: x.name,
        ),
    )


# ─── GET /granular/session/{id}/tables ───────────────────────────────────────

@granular_router.get("/session/{session_id}/tables", response_model=list[TableSummary])
async def list_tables(
    session_id: str,
    request: Request,
) -> list[TableSummary]:
    """Return all tables in the parsed session with row counts."""
    store = _get_store(request)
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    return sorted(
        [
            TableSummary(
                name=t.name,
                row_count=t.row_count,
                columns=t.columns,
                fk_count=len(t.fk_constraints),
            )
            for t in session.tables.values()
        ],
        key=lambda x: x.name,
    )


# ─── GET /granular/session/{id}/table/{table}/rows ────────────────────────────

@granular_router.get(
    "/session/{session_id}/table/{table}/rows",
    response_model=RowsResponse,
)
async def get_rows(
    session_id: str,
    table: str,
    request: Request,
    filter_col: Optional[str] = Query(default=None),
    filter_val: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> RowsResponse:
    """
    Return paginated rows from a table in the session.
    Optionally filter by a single column (case-insensitive substring match).
    Each row gets an extra _idx field (original index) for restore selection.
    """
    store = _get_store(request)
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    table_info = session.tables.get(table)
    if not table_info:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found")

    rows = table_info.rows

    # Apply substring filter
    if filter_col and filter_val is not None and filter_col in table_info.columns:
        fv = filter_val.lower()
        rows = [r for r in rows if fv in str(r.get(filter_col, "")).lower()]

    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]

    # Attach original index so the UI can pass it back for restore
    indexed = [{**r, "_idx": start + i} for i, r in enumerate(page_rows)]

    return RowsResponse(
        columns=table_info.columns,
        rows=indexed,
        total=total,
        page=page,
        page_size=page_size,
    )


# ─── POST /granular/session/{id}/resolve ─────────────────────────────────────

@granular_router.post("/session/{session_id}/resolve", response_model=ResolveResponse)
async def resolve_deps(
    session_id: str,
    body: ResolveRequest,
    request: Request,
) -> ResolveResponse:
    """
    Walk the FK constraint graph from the selected rows outward.
    Returns the full set of rows (target + all referenced/parent rows)
    that would be applied during a restore.
    """
    store = _get_store(request)
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    resolved = resolve_dependencies(session.tables, body.table, body.row_indices)
    if not resolved:
        raise HTTPException(
            status_code=400,
            detail="No rows resolved. Check table name and row indices.",
        )

    deps = [
        FKDep(table=tname, row_count=len(rows), rows=rows)
        for tname, rows in resolved.items()
    ]
    return ResolveResponse(
        total_rows=sum(d.row_count for d in deps),
        dependencies=deps,
    )


# ─── POST /granular/session/{id}/restore ─────────────────────────────────────

@granular_router.post("/session/{session_id}/restore", response_model=GranularRestoreResponse)
async def granular_restore(
    session_id: str,
    body: GranularRestoreRequest,
    request: Request,
) -> GranularRestoreResponse:
    """
    Apply the selected rows (+ FK dependencies) directly into the live database.

    Pipeline:
      resolve_dependencies() → generate_restore_sql() → execute against live DB

    Requires confirm=True. Does NOT drop the database  it only inserts/updates
    the specific rows using the chosen conflict strategy.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm=true is required")

    if body.strategy not in ("skip", "replace", "merge"):
        raise HTTPException(
            status_code=400,
            detail="strategy must be 'skip', 'replace', or 'merge'",
        )

    store = _get_store(request)
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    config: AppConfig = request.app.state.config
    db_config = _find_db(config, session.db_name)
    if not db_config:
        raise HTTPException(
            status_code=404,
            detail=f"Database '{session.db_name}' not found in config",
        )

    resolved = resolve_dependencies(session.tables, body.table, body.row_indices)
    if not resolved:
        raise HTTPException(status_code=400, detail="No rows selected")

    sql = generate_restore_sql(resolved, body.strategy, session.db_type)

    log.info(
        "granular_restore_started",
        f"Applying {sum(len(r) for r in resolved.values())} rows "
        f"across {len(resolved)} tables (strategy={body.strategy})",
        database=session.db_name,
    )

    try:
        await _execute_sql(db_config, sql, session.db_type)
    except Exception as e:
        log.error("granular_restore_failed", str(e), database=session.db_name)
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")

    rows_applied = sum(len(rows) for rows in resolved.values())
    tables_affected = list(resolved.keys())

    log.info(
        "granular_restore_completed",
        f"Applied {rows_applied} rows across {tables_affected}",
        database=session.db_name,
    )

    return GranularRestoreResponse(
        status="completed",
        rows_applied=rows_applied,
        tables_affected=tables_affected,
    )


# ─── POST /granular/session/{id}/resolve-multi ───────────────────────────────

@granular_router.post("/session/{session_id}/resolve-multi", response_model=ResolveResponse)
async def resolve_deps_multi(
    session_id: str,
    body: MultiResolveRequest,
    request: Request,
) -> ResolveResponse:
    """
    Resolve FK dependencies for multiple tables at once.
    Results are merged and deduplicated  if two target tables share a common
    FK-referenced parent, its rows appear only once in the output.
    """
    if not body.tables:
        raise HTTPException(status_code=400, detail="tables list is empty")

    store = _get_store(request)
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # merged[table] = deduplicated list of row dicts
    merged: dict[str, list[dict]] = {}
    seen_fps: dict[str, set] = {}  # table -> set of row fingerprints

    for entry in body.tables:
        resolved = resolve_dependencies(session.tables, entry.table, entry.row_indices)
        for tname, rows in resolved.items():
            if tname not in merged:
                merged[tname] = []
                seen_fps[tname] = set()
            for row in rows:
                fp = tuple(sorted((k, str(v)) for k, v in row.items()))
                if fp not in seen_fps[tname]:
                    seen_fps[tname].add(fp)
                    merged[tname].append(row)

    if not merged:
        raise HTTPException(status_code=400, detail="No rows resolved")

    deps = [
        FKDep(table=tname, row_count=len(rows), rows=rows)
        for tname, rows in merged.items()
    ]
    return ResolveResponse(
        total_rows=sum(d.row_count for d in deps),
        dependencies=deps,
    )


# ─── POST /granular/session/{id}/restore-multi ────────────────────────────────

@granular_router.post("/session/{session_id}/restore-multi", response_model=GranularRestoreResponse)
async def granular_restore_multi(
    session_id: str,
    body: MultiRestoreRequest,
    request: Request,
) -> GranularRestoreResponse:
    """
    Apply rows from multiple tables in one operation.
    FK deps are resolved for all tables, merged, then inserted in a single SQL
    batch using the chosen conflict strategy.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm=true is required")

    if body.strategy not in ("skip", "replace", "merge"):
        raise HTTPException(
            status_code=400,
            detail="strategy must be 'skip', 'replace', or 'merge'",
        )

    if not body.tables:
        raise HTTPException(status_code=400, detail="tables list is empty")

    store = _get_store(request)
    session = await store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    config: AppConfig = request.app.state.config
    db_config = _find_db(config, session.db_name)
    if not db_config:
        raise HTTPException(
            status_code=404,
            detail=f"Database '{session.db_name}' not found in config",
        )

    # Resolve + merge
    merged: dict[str, list[dict]] = {}
    seen_fps: dict[str, set] = {}

    for entry in body.tables:
        resolved = resolve_dependencies(session.tables, entry.table, entry.row_indices)
        for tname, rows in resolved.items():
            if tname not in merged:
                merged[tname] = []
                seen_fps[tname] = set()
            for row in rows:
                fp = tuple(sorted((k, str(v)) for k, v in row.items()))
                if fp not in seen_fps[tname]:
                    seen_fps[tname].add(fp)
                    merged[tname].append(row)

    if not merged:
        raise HTTPException(status_code=400, detail="No rows selected")

    sql = generate_restore_sql(merged, body.strategy, session.db_type)

    rows_applied = sum(len(rows) for rows in merged.values())
    tables_affected = list(merged.keys())

    log.info(
        "granular_restore_started",
        f"Multi-table: applying {rows_applied} rows across {tables_affected} (strategy={body.strategy})",
        database=session.db_name,
    )

    try:
        await _execute_sql(db_config, sql, session.db_type)
    except Exception as e:
        log.error("granular_restore_failed", str(e), database=session.db_name)
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")

    log.info(
        "granular_restore_completed",
        f"Applied {rows_applied} rows across {tables_affected}",
        database=session.db_name,
    )

    return GranularRestoreResponse(
        status="completed",
        rows_applied=rows_applied,
        tables_affected=tables_affected,
    )


# ─── DELETE /granular/session/{id} ───────────────────────────────────────────

@granular_router.delete("/session/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict:
    """Manually clean up a session before the 30-minute TTL expires."""
    store = _get_store(request)
    if not await store.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": session_id}


# ─── SQL execution helper ─────────────────────────────────────────────────────

async def _execute_sql(db_config: DatabaseConfig, sql: str, db_type: str) -> None:
    """Run generated SQL against the live database using the native CLI tool."""
    env = os.environ.copy()

    if db_type == "mysql":
        env["MYSQL_PWD"] = db_config.password
        proc = await asyncio.create_subprocess_exec(
            "mysql",
            "--host", db_config.host,
            "--port", str(db_config.port),
            "--user", db_config.user,
            db_config.db,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await proc.communicate(input=sql.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"mysql: {stderr.decode(errors='replace')}")

    elif db_type == "postgres":
        env["PGPASSWORD"] = db_config.password
        proc = await asyncio.create_subprocess_exec(
            "psql",
            "-h", db_config.host,
            "-p", str(db_config.port),
            "-U", db_config.user,
            "-d", db_config.db,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await proc.communicate(input=sql.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"psql: {stderr.decode(errors='replace')}")

    else:
        raise RuntimeError(
            f"Granular restore is not supported for db type '{db_type}'"
        )
