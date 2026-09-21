"""
app/granular.py  Granular (row-level) restore engine.

Provides:
  - SQL dump parser  (MySQL + PostgreSQL)
  - In-memory session store with 30-minute TTL
  - FK dependency resolver
  - Restore SQL generator (skip / replace / merge)
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.logger import log


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class FKConstraint:
    """A single FOREIGN KEY constraint on a column."""
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    """In-memory representation of a parsed table from a SQL dump."""
    name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    fk_constraints: list[FKConstraint] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class GranularSession:
    """A parsed backup session held in memory for interactive granular restore."""
    session_id: str
    backup_filename: str
    db_name: str
    db_type: str
    tables: dict[str, TableInfo]
    created_at: float
    last_accessed: float

    TTL: int = field(default=1800, init=False, repr=False)  # 30 minutes

    def touch(self) -> None:
        self.last_accessed = time.time()

    def is_expired(self) -> bool:
        return time.time() - self.last_accessed > self.TTL


# ─── Session store ─────────────────────────────────────────────────────────────

_SESSION_TTL_SECONDS = 1800  # 30 minutes


class GranularSessionStore:
    """
    Store for active granular restore sessions.

    - pool provided  → sessions persisted to PostgreSQL (survive restarts).
    - pool = None    → in-memory fallback (lost on restart, 30-min TTL).

    The parsed table rows are always kept in-memory for fast access; the DB
    stores the metadata row in `granular_sessions` and the per-table rows in
    `granular_session_rows` so a session can be rehydrated after restart.
    """

    def __init__(self, pool=None) -> None:
        self._pool = pool
        self._sessions: dict[str, GranularSession] = {}  # in-memory cache

    def set_pool(self, pool) -> None:
        """Inject DB pool after init_db()  called from main.py."""
        self._pool = pool

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        backup_filename: str,
        db_name: str,
        db_type: str,
        tables: dict[str, TableInfo],
    ) -> GranularSession:
        session_id = str(uuid.uuid4())[:8]
        now = time.time()
        session = GranularSession(
            session_id=session_id,
            backup_filename=backup_filename,
            db_name=db_name,
            db_type=db_type,
            tables=tables,
            created_at=now,
            last_accessed=now,
        )
        self._sessions[session_id] = session

        if self._pool:
            await self._persist_session(session)

        log.info(
            "granular_session_created",
            f"Session {session_id}  {len(tables)} tables parsed",
            database=db_name,
        )
        return session

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    async def get(self, session_id: str) -> Optional[GranularSession]:
        # Check in-memory cache first
        session = self._sessions.get(session_id)
        if session is not None:
            if session.is_expired():
                del self._sessions[session_id]
                await self._mark_db_expired(session_id)
                log.info("granular_session_expired", f"Session {session_id} expired and removed")
                return None
            session.touch()
            await self._update_last_accessed(session_id)
            return session

        # Not in memory  try to rehydrate from DB
        if self._pool:
            session = await self._load_from_db(session_id)
            if session is not None:
                if session.is_expired():
                    await self._mark_db_expired(session_id)
                    log.info("granular_session_expired", f"Session {session_id} expired (reloaded from DB)")
                    return None
                session.touch()
                self._sessions[session_id] = session
                await self._update_last_accessed(session_id)
                return session

        return None

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, session_id: str) -> bool:
        found = session_id in self._sessions
        if found:
            del self._sessions[session_id]
        if self._pool:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM granular_sessions WHERE id = $1",
                    _session_uuid(session_id),
                )
            found = found or (result != "DELETE 0")
        return found

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_expired(self) -> int:
        # In-memory cleanup
        expired_ids = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired_ids:
            del self._sessions[sid]

        # DB cleanup
        db_deleted = 0
        if self._pool:
            now = datetime.now(timezone.utc)
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM granular_sessions WHERE expires_at < $1 OR status = 'expired'",
                    now,
                )
            db_deleted = int(result.split()[-1])

        total = len(expired_ids) + db_deleted
        if total:
            log.info("granular_sessions_cleanup", f"Removed {total} expired granular sessions")
        return total

    @property
    def count(self) -> int:
        return len(self._sessions)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _persist_session(self, session: GranularSession) -> None:
        """Write session metadata + all table rows to DB."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=_SESSION_TTL_SECONDS)
        sid = _session_uuid(session.session_id)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO granular_sessions
                        (id, backup_filename, database_name, db_type,
                         created_at, last_accessed, expires_at, status)
                    VALUES ($1, $2, $3, $4, $5, $5, $6, 'active')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    sid,
                    session.backup_filename,
                    session.db_name,
                    session.db_type,
                    now,
                    expires_at,
                )
                # Persist each table's rows
                for table_name, table_info in session.tables.items():
                    await conn.execute(
                        """
                        INSERT INTO granular_session_rows
                            (session_id, table_name, columns, rows, fk_constraints)
                        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb)
                        ON CONFLICT DO NOTHING
                        """,
                        sid,
                        table_name,
                        json.dumps(table_info.columns),
                        json.dumps(table_info.rows),
                        json.dumps([
                            {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
                            for fk in table_info.fk_constraints
                        ]),
                    )
        except Exception as e:
            log.warning("granular_session_created", f"Could not persist granular session to DB: {e}")

    async def _load_from_db(self, session_id: str) -> Optional[GranularSession]:
        """Rehydrate a session from DB rows into a GranularSession object."""
        sid = _session_uuid(session_id)
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM granular_sessions WHERE id = $1 AND status = 'active'",
                    sid,
                )
                if row is None:
                    return None
                table_rows = await conn.fetch(
                    "SELECT * FROM granular_session_rows WHERE session_id = $1",
                    sid,
                )
        except Exception:
            return None

        tables: dict[str, TableInfo] = {}
        for tr in table_rows:
            fk_list = [
                FKConstraint(
                    column=fk["column"],
                    ref_table=fk["ref_table"],
                    ref_column=fk["ref_column"],
                )
                for fk in (tr["fk_constraints"] or [])
            ]
            tables[tr["table_name"]] = TableInfo(
                name=tr["table_name"],
                columns=list(tr["columns"] or []),
                rows=list(tr["rows"] or []),
                fk_constraints=fk_list,
            )

        now = time.time()
        # Convert DB timestamps to unix epoch for GranularSession
        created_ts = row["created_at"].timestamp() if row["created_at"] else now
        accessed_ts = row["last_accessed"].timestamp() if row["last_accessed"] else now

        return GranularSession(
            session_id=session_id,
            backup_filename=row["backup_filename"],
            db_name=row["database_name"],
            db_type=row["db_type"],
            tables=tables,
            created_at=created_ts,
            last_accessed=accessed_ts,
        )

    async def _update_last_accessed(self, session_id: str) -> None:
        if not self._pool:
            return
        sid = _session_uuid(session_id)
        now = datetime.now(timezone.utc)
        new_expires = now + timedelta(seconds=_SESSION_TTL_SECONDS)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE granular_sessions SET last_accessed = $1, expires_at = $2 WHERE id = $3",
                    now, new_expires, sid,
                )
        except Exception:
            pass

    async def _mark_db_expired(self, session_id: str) -> None:
        if not self._pool:
            return
        sid = _session_uuid(session_id)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE granular_sessions SET status = 'expired' WHERE id = $1",
                    sid,
                )
        except Exception:
            pass


def _session_uuid(session_id: str):
    """Convert short session_id string to UUID for DB storage."""
    import uuid as _uuid
    # Short IDs (8 hex chars) are padded to valid UUID format
    padded = session_id.ljust(32, "0")
    try:
        return _uuid.UUID(padded)
    except ValueError:
        # Already a full UUID string
        try:
            return _uuid.UUID(session_id)
        except ValueError:
            return _uuid.uuid5(_uuid.NAMESPACE_DNS, session_id)


# ─── SQL Value tokenizer ───────────────────────────────────────────────────────

def _tokenize_row(s: str) -> list[str]:
    """
    Split a comma-separated SQL values string into individual value tokens,
    respecting quoted strings and nested parentheses.
    Input:  "1, 'John\\'s', NULL, 3.14"
    Output: ["1", "'John\\'s'", "NULL", "3.14"]
    """
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    in_str = False
    str_char = ""
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\" and i + 1 < len(s):
                current.append(c)
                i += 1
                current.append(s[i])
            elif c == str_char:
                in_str = False
                current.append(c)
            else:
                current.append(c)
        else:
            if c in ("'", '"'):
                in_str = True
                str_char = c
                current.append(c)
            elif c == "(":
                depth += 1
                current.append(c)
            elif c == ")":
                depth -= 1
                current.append(c)
            elif c == "," and depth == 0:
                tokens.append("".join(current).strip())
                current = []
            else:
                current.append(c)
        i += 1
    if current:
        tokens.append("".join(current).strip())
    return tokens


def _parse_sql_value(v: str) -> Any:
    """Convert a raw SQL token string to a Python-native value."""
    v = v.strip()
    if v.upper() == "NULL":
        return None
    # Quoted string
    if len(v) >= 2 and v[0] in ("'", '"') and v[-1] == v[0]:
        inner = v[1:-1]
        inner = (
            inner.replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )
        return inner
    # Backtick-quoted identifier
    if len(v) >= 2 and v[0] == "`" and v[-1] == "`":
        return v[1:-1]
    # Numeric
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _extract_row_tuples(values_block: str) -> list[list[Any]]:
    """
    Parse  (v1,v2,...),(v3,v4,...) into [[v1,v2,...],[v3,v4,...]]
    """
    rows: list[list[Any]] = []
    current: list[str] = []
    depth = 0
    in_str = False
    str_char = ""
    i = 0
    while i < len(values_block):
        c = values_block[i]
        if in_str:
            if c == "\\" and i + 1 < len(values_block):
                current.append(c)
                i += 1
                current.append(values_block[i])
            elif c == str_char:
                in_str = False
                current.append(c)
            else:
                current.append(c)
        else:
            if c in ("'", '"'):
                in_str = True
                str_char = c
                current.append(c)
            elif c == "(":
                if depth == 0:
                    current = []
                else:
                    current.append(c)
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    tokens = _tokenize_row("".join(current))
                    rows.append([_parse_sql_value(t) for t in tokens])
                    current = []
                else:
                    current.append(c)
            else:
                if depth > 0:
                    current.append(c)
        i += 1
    return rows


# ─── CREATE TABLE parser ──────────────────────────────────────────────────────

def _extract_columns(create_sql: str) -> list[str]:
    """Extract column names from a CREATE TABLE statement body."""
    paren_start = create_sql.index("(")
    depth = 0
    paren_end = paren_start
    for i in range(paren_start, len(create_sql)):
        if create_sql[i] == "(":
            depth += 1
        elif create_sql[i] == ")":
            depth -= 1
            if depth == 0:
                paren_end = i
                break

    body = create_sql[paren_start + 1 : paren_end]

    # Split by commas at depth 0
    lines: list[str] = []
    cur: list[str] = []
    d = 0
    in_s = False
    sc = ""
    for c in body:
        if in_s:
            if c == sc:
                in_s = False
            cur.append(c)
        else:
            if c in ('"', "'", "`"):
                in_s = True
                sc = c
                cur.append(c)
            elif c == "(":
                d += 1
                cur.append(c)
            elif c == ")":
                d -= 1
                cur.append(c)
            elif c == "," and d == 0:
                lines.append("".join(cur).strip())
                cur = []
            else:
                cur.append(c)
    if cur:
        lines.append("".join(cur).strip())

    columns: list[str] = []
    _CONSTRAINT_KW = (
        "PRIMARY", "UNIQUE", "KEY", "INDEX", "CONSTRAINT", "CHECK", "FOREIGN", "FULLTEXT",
    )
    for line in lines:
        line = line.strip()
        if not line:
            continue
        upper = line.upper().lstrip()
        if any(upper.startswith(kw) for kw in _CONSTRAINT_KW):
            continue
        m = re.match(r'^[`"\[]?(\w+)[`"\]]?', line)
        if m:
            columns.append(m.group(1))

    return columns


def _extract_fk_constraints(create_sql: str) -> list[FKConstraint]:
    """Extract FOREIGN KEY constraints from a CREATE TABLE statement."""
    constraints: list[FKConstraint] = []
    pattern = re.compile(
        r"FOREIGN\s+KEY\s*\([`\"]?(\w+)[`\"]?\)\s*"
        r"REFERENCES\s*[`\"]?(\w+)[`\"]?\s*"
        r"\([`\"]?(\w+)[`\"]?\)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(create_sql):
        constraints.append(
            FKConstraint(column=m.group(1), ref_table=m.group(2), ref_column=m.group(3))
        )
    return constraints


# ─── Main dump parser ─────────────────────────────────────────────────────────

_SKIP_TABLE_PREFIXES = (
    "pg_", "information_schema", "sys", "performance_schema",
    "mysql", "innodb", "ndb_",
)


def parse_sql_dump(content: str, db_type: str) -> dict[str, TableInfo]:
    """
    Parse a full SQL dump (MySQL or PostgreSQL) into TableInfo objects.

    Handles:
      - CREATE TABLE statements  (columns + FK constraints)
      - INSERT INTO … VALUES     (MySQL style)
      - COPY … FROM stdin        (PostgreSQL COPY format)
    """
    tables: dict[str, TableInfo] = {}

    # ── Step 1: CREATE TABLE → schema ──────────────────────────────────────
    create_re = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\(",
        re.IGNORECASE,
    )
    for m in create_re.finditer(content):
        table_name = m.group(1)
        if any(table_name.lower().startswith(p) for p in _SKIP_TABLE_PREFIXES):
            continue
        # Walk forward to find the matching close paren
        depth = 0
        end = m.start()
        for i in range(m.start(), min(m.start() + 200_000, len(content))):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        create_sql = content[m.start() : end]
        try:
            columns = _extract_columns(create_sql)
            fks = _extract_fk_constraints(create_sql)
        except (ValueError, IndexError):
            columns = []
            fks = []
        tables[table_name] = TableInfo(
            name=table_name, columns=columns, rows=[], fk_constraints=fks
        )

    # ── Step 2: INSERT INTO … VALUES → rows ────────────────────────────────
    insert_re = re.compile(
        r"INSERT\s+INTO\s+[`\"]?(\w+)[`\"]?\s*"
        r"(?:\(([^)]+)\)\s*)?"
        r"VALUES\s*(.+?)(?=;|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    for m in insert_re.finditer(content):
        table_name = m.group(1)
        if any(table_name.lower().startswith(p) for p in _SKIP_TABLE_PREFIXES):
            continue
        col_list_str = m.group(2)
        values_block = m.group(3)

        if table_name not in tables:
            tables[table_name] = TableInfo(name=table_name, columns=[], rows=[])

        table = tables[table_name]
        insert_cols = (
            [c.strip().strip("`\"' ") for c in col_list_str.split(",")]
            if col_list_str
            else table.columns
        )
        if not table.columns and insert_cols:
            table.columns = insert_cols

        try:
            row_tuples = _extract_row_tuples(values_block)
        except Exception:
            continue

        for row_tuple in row_tuples:
            if insert_cols and len(row_tuple) == len(insert_cols):
                table.rows.append(dict(zip(insert_cols, row_tuple)))
            elif table.columns and len(row_tuple) == len(table.columns):
                table.rows.append(dict(zip(table.columns, row_tuple)))

    # ── Step 3: PostgreSQL COPY … FROM stdin → rows ────────────────────────
    if db_type == "postgres":
        copy_re = re.compile(
            r"COPY\s+(?:\w+\.)?(\w+)\s*\(([^)]+)\)\s*FROM\s+stdin;\n(.*?)\\\.",
            re.IGNORECASE | re.DOTALL,
        )
        for m in copy_re.finditer(content):
            table_name = m.group(1)
            if any(table_name.lower().startswith(p) for p in _SKIP_TABLE_PREFIXES):
                continue
            cols = [c.strip() for c in m.group(2).split(",")]
            if table_name not in tables:
                tables[table_name] = TableInfo(name=table_name, columns=cols, rows=[])
            table = tables[table_name]
            if not table.columns:
                table.columns = cols
            for line in m.group(3).strip().split("\n"):
                if not line:
                    continue
                values = line.split("\t")
                row = {
                    col: (None if val == "\\N" else val)
                    for col, val in zip(cols, values)
                }
                table.rows.append(row)

    # Drop system tables that slipped through
    return {
        k: v
        for k, v in tables.items()
        if not any(k.lower().startswith(p) for p in _SKIP_TABLE_PREFIXES)
    }


# ─── FK dependency resolver ───────────────────────────────────────────────────

def resolve_dependencies(
    tables: dict[str, TableInfo],
    target_table: str,
    selected_row_indices: list[int],
) -> dict[str, list[dict[str, Any]]]:
    """
    Given selected rows by index in target_table, recursively collect all rows
    from tables referenced via FOREIGN KEY constraints.

    Returns an ordered dict where the target table is first, followed by
    referenced (parent) tables  ready for INSERT in dependency order.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    visited: set[str] = set()

    def _collect(table_name: str, rows: list[dict[str, Any]]) -> None:
        if table_name in visited:
            return
        visited.add(table_name)

        # Merge rows (deduplicate)
        existing = result.get(table_name, [])
        for row in rows:
            if row not in existing:
                existing.append(row)
        result[table_name] = existing

        table = tables.get(table_name)
        if not table:
            return

        for fk in table.fk_constraints:
            ref_table = tables.get(fk.ref_table)
            if not ref_table:
                continue
            fk_values = {
                row.get(fk.column)
                for row in result[table_name]
                if row.get(fk.column) is not None
            }
            if not fk_values:
                continue
            ref_rows = [r for r in ref_table.rows if r.get(fk.ref_column) in fk_values]
            if ref_rows:
                _collect(fk.ref_table, ref_rows)

    target = tables.get(target_table)
    if not target:
        return {}

    all_rows = target.rows
    selected_rows = [all_rows[i] for i in selected_row_indices if 0 <= i < len(all_rows)]
    if not selected_rows:
        return {}

    _collect(target_table, selected_rows)
    return result


# ─── Restore SQL generator ────────────────────────────────────────────────────

def generate_restore_sql(
    resolved_data: dict[str, list[dict[str, Any]]],
    strategy: str,
    db_type: str,
) -> str:
    """
    Generate the SQL to apply resolved rows into the live production database.

    strategy:
      skip    → INSERT IGNORE (MySQL) / ON CONFLICT DO NOTHING (PG)
      replace → REPLACE INTO (MySQL) / ON CONFLICT DO UPDATE SET … (PG)
      merge   → alias for replace
    """

    def _escape(v: Any) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        return str(v)

    lines = [
        "-- Archon Granular Restore",
        f"-- Strategy: {strategy}",
        "",
    ]

    if db_type == "mysql":
        lines += ["SET FOREIGN_KEY_CHECKS=0;", ""]

    # Emit parent tables first (reverse insertion order so dependencies come first)
    ordered = list(resolved_data.items())
    # Target table is first in result dict  put it last so parents insert first
    if len(ordered) > 1:
        ordered = ordered[1:] + ordered[:1]

    for table_name, rows in ordered:
        if not rows:
            continue
        columns = list(rows[0].keys())
        if db_type == "mysql":
            col_list = ", ".join(f"`{c}`" for c in columns)
        else:
            col_list = ", ".join(f'"{c}"' for c in columns)

        lines.append(f"-- {table_name} ({len(rows)} row{'s' if len(rows) != 1 else ''})")

        for row in rows:
            values = ", ".join(_escape(row.get(c)) for c in columns)
            if db_type == "mysql":
                if strategy == "skip":
                    lines.append(
                        f"INSERT IGNORE INTO `{table_name}` ({col_list}) VALUES ({values});"
                    )
                else:  # replace / merge
                    lines.append(
                        f"REPLACE INTO `{table_name}` ({col_list}) VALUES ({values});"
                    )
            else:  # postgres
                if strategy == "skip":
                    lines.append(
                        f'INSERT INTO "{table_name}" ({col_list}) VALUES ({values}) ON CONFLICT DO NOTHING;'
                    )
                else:
                    pk = columns[0]
                    updates = ", ".join(
                        f'"{c}" = EXCLUDED."{c}"' for c in columns if c != pk
                    )
                    lines.append(
                        f'INSERT INTO "{table_name}" ({col_list}) VALUES ({values}) '
                        f'ON CONFLICT ("{pk}") DO UPDATE SET {updates};'
                    )
        lines.append("")

    if db_type == "mysql":
        lines.append("SET FOREIGN_KEY_CHECKS=1;")

    return "\n".join(lines)
