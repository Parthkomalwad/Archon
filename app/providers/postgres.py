import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.config import DatabaseConfig
from app.logger import log
from app.providers.base import BaseProvider, ProviderError


class PostgresProvider(BaseProvider):
    """
    PostgreSQL backup and restore using pg_dump / psql.

    Backup:  pg_dump --format=plain  → .sql text file
    Restore: dispatches to drop_recreate or shadow based on db.restore_strategy.

    Drop-recreate: DROP DATABASE → CREATE DATABASE → psql -f backup.sql
    Shadow:        CREATE shadow_db → psql -f backup.sql (to shadow) → terminate conns
                   → RENAME target→old → RENAME shadow→target → DROP old
    """

    def __init__(self, db: DatabaseConfig) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _env(self) -> dict:
        """Return a copy of the OS environment with PGPASSWORD injected."""
        env = os.environ.copy()
        env["PGPASSWORD"] = self.db.password
        return env

    def _conn_args(self) -> list[str]:
        """Common connection flags shared by pg_dump and psql."""
        return ["-h", self.db.host, "-p", str(self.db.port), "-U", self.db.user]

    def _exec_sql(self, conn_db: str, sql: str) -> None:
        """Execute a single SQL statement via psql. Raises CalledProcessError on failure."""
        subprocess.run(
            ["psql", *self._conn_args(), "-d", conn_db, "-c", sql],
            check=True,
            capture_output=True,
            env=self._env(),
        )

    def _cleanup_sql(self, conn_db: str, sql: str) -> None:
        """Execute cleanup SQL; silently suppress failures (used only in rollback paths)."""
        try:
            self._exec_sql(conn_db, sql)
        except subprocess.CalledProcessError:
            pass

    # ------------------------------------------------------------------
    # backup()
    # ------------------------------------------------------------------

    def backup(self, output_path: str) -> None:
        log.info("backup_started", "Starting pg_dump", database=self.db.name)
        try:
            subprocess.run(
                ["pg_dump", *self._conn_args(), "-d", self.db.db, "-f", output_path],
                check=True,
                capture_output=True,
                env=self._env(),
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("backup_failed", "pg_dump exited non-zero", database=self.db.name, error=err)
            raise ProviderError(f"pg_dump failed: {err}")

        size = Path(output_path).stat().st_size
        log.info(
            "backup_completed",
            f"pg_dump complete ({size} bytes)",
            database=self.db.name,
            size_bytes=size,
        )

    # ------------------------------------------------------------------
    # restore()  dispatches to drop_recreate or shadow
    # ------------------------------------------------------------------

    def restore(self, backup_path: str, confirm: bool) -> None:
        if not confirm:
            raise ValueError("restore() requires confirm=True to prevent accidental data loss")

        if self.db.restore_strategy == "shadow":
            self.restore_shadow(backup_path, self.db.db, confirm)
        else:
            self._restore_drop_recreate(backup_path, confirm)

    # ------------------------------------------------------------------
    # Drop-and-recreate restore (original strategy)
    # ------------------------------------------------------------------

    def _restore_drop_recreate(self, backup_path: str, confirm: bool) -> None:
        log.info(
            "restore_started",
            "Starting PostgreSQL restore (drop-and-recreate)",
            database=self.db.name,
        )

        conn = self._conn_args()
        env = self._env()
        db_name = self.db.db

        try:
            # Step 1: DROP DATABASE (connect to postgres maintenance DB)
            subprocess.run(
                [
                    "psql", *conn, "-d", "postgres",
                    "-c", f'DROP DATABASE IF EXISTS "{db_name}"',
                ],
                check=True,
                capture_output=True,
                env=env,
            )

            # Step 2: CREATE DATABASE
            subprocess.run(
                [
                    "psql", *conn, "-d", "postgres",
                    "-c", f'CREATE DATABASE "{db_name}"',
                ],
                check=True,
                capture_output=True,
                env=env,
            )

            # Step 3: Restore from SQL dump
            subprocess.run(
                ["psql", *conn, "-d", db_name, "-f", backup_path],
                check=True,
                capture_output=True,
                env=env,
            )

        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("restore_failed", "PostgreSQL restore failed", database=self.db.name, error=err)
            raise ProviderError(f"PostgreSQL restore failed: {err}")

        log.info("restore_completed", "PostgreSQL restore complete", database=self.db.name)

    # ------------------------------------------------------------------
    # Shadow restore (safe atomic rename strategy)
    # ------------------------------------------------------------------

    def restore_shadow(self, backup_path: str, target_db: str, confirm: bool) -> None:
        """
        Restore a PostgreSQL database using the shadow strategy.

        The original database remains live and queryable until milliseconds before
        the final RENAME. Recovery at each step:

        Step 1  CREATE shadow       : fails → raise ProviderError (original untouched)
        Step 2  RESTORE to shadow   : fails → DROP shadow, raise ProviderError
        Step 3  TERMINATE conns     : fails → DROP shadow, raise ProviderError (original untouched)
        Step 4  RENAME target→old   : fails → DROP shadow, raise ProviderError (original keeps its name)
        Step 5  RENAME shadow→target: fails → RENAME old→target, DROP shadow, raise ProviderError
        Step 6  DROP old            : fails → log warning only (restore already succeeded)
        """
        ts = int(datetime.now(timezone.utc).timestamp())
        shadow_name = f"{target_db}_archon_shadow_{ts}"
        old_name = f"{target_db}_archon_old_{ts}"

        log.info(
            "shadow_restore_started",
            f"Shadow restore started for '{target_db}'",
            database=self.db.name,
            target_db=target_db,
            shadow_db=shadow_name,
        )

        try:
            # ── Step 1: Create shadow DB ─────────────────────────────────────
            try:
                self._exec_sql("postgres", f'CREATE DATABASE "{shadow_name}"')
            except subprocess.CalledProcessError as e:
                raise ProviderError(
                    f"Shadow restore step 1 (create shadow '{shadow_name}') failed: "
                    f"{e.stderr.decode(errors='replace')}"
                )

            # ── Step 2: Restore backup into shadow DB ────────────────────────
            try:
                subprocess.run(
                    ["psql", *self._conn_args(), "-d", shadow_name, "-f", backup_path],
                    check=True,
                    capture_output=True,
                    env=self._env(),
                )
            except subprocess.CalledProcessError as e:
                self._cleanup_sql("postgres", f'DROP DATABASE IF EXISTS "{shadow_name}"')
                raise ProviderError(
                    f"Shadow restore step 2 (restore to shadow '{shadow_name}') failed: "
                    f"{e.stderr.decode(errors='replace')}"
                )

            # ── Step 3: Terminate connections to target DB ───────────────────
            try:
                self._exec_sql(
                    "postgres",
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{target_db}'",
                )
            except subprocess.CalledProcessError as e:
                self._cleanup_sql("postgres", f'DROP DATABASE IF EXISTS "{shadow_name}"')
                raise ProviderError(
                    f"Shadow restore step 3 (terminate connections to '{target_db}') failed: "
                    f"{e.stderr.decode(errors='replace')}"
                )

            # ── Step 4: Rename target → old ──────────────────────────────────
            try:
                self._exec_sql("postgres", f'ALTER DATABASE "{target_db}" RENAME TO "{old_name}"')
            except subprocess.CalledProcessError as e:
                self._cleanup_sql("postgres", f'DROP DATABASE IF EXISTS "{shadow_name}"')
                raise ProviderError(
                    f"Shadow restore step 4 (rename '{target_db}' → '{old_name}') failed: "
                    f"{e.stderr.decode(errors='replace')}"
                )

            # ── Step 5: Rename shadow → target ───────────────────────────────
            try:
                self._exec_sql("postgres", f'ALTER DATABASE "{shadow_name}" RENAME TO "{target_db}"')
            except subprocess.CalledProcessError as e:
                # Rollback: restore original name before giving up
                self._cleanup_sql("postgres", f'ALTER DATABASE "{old_name}" RENAME TO "{target_db}"')
                self._cleanup_sql("postgres", f'DROP DATABASE IF EXISTS "{shadow_name}"')
                raise ProviderError(
                    f"Shadow restore step 5 (rename shadow → '{target_db}') failed: "
                    f"{e.stderr.decode(errors='replace')}"
                )

            # ── Step 6: Drop old (non-critical) ─────────────────────────────
            try:
                self._exec_sql("postgres", f'DROP DATABASE IF EXISTS "{old_name}"')
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode(errors="replace")
                log.warning(
                    "shadow_restore_failed",
                    f"Step 6: failed to drop old DB '{old_name}' after successful restore  "
                    f"manual cleanup required",
                    database=self.db.name,
                    old_db=old_name,
                    error=err,
                )
                # Do NOT raise  the restore itself succeeded

            log.info(
                "shadow_restore_completed",
                f"Shadow restore complete for '{target_db}'",
                database=self.db.name,
                target_db=target_db,
            )

        except ProviderError:
            log.error(
                "shadow_restore_failed",
                f"Shadow restore failed for '{target_db}'",
                database=self.db.name,
                target_db=target_db,
            )
            raise
