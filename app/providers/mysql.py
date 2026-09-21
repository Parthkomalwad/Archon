import os
import subprocess
from pathlib import Path

from app.config import DatabaseConfig
from app.logger import log
from app.providers.base import BaseProvider, ProviderError


class MySQLProvider(BaseProvider):
    """
    MySQL / MariaDB backup and restore using mysqldump / mysql CLI tools.

    Backup:  mysqldump --single-transaction --routines --triggers  → .sql text file
    Restore: DROP DATABASE → CREATE DATABASE → mysql < backup.sql  (drop-and-recreate)

    The --single-transaction flag ensures a consistent snapshot of InnoDB tables
    without acquiring a global read lock, making it safe for live databases.
    """

    def __init__(self, db: DatabaseConfig) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _env(self) -> dict:
        """Return env with MYSQL_PWD set so the password is never passed on the CLI."""
        env = os.environ.copy()
        env["MYSQL_PWD"] = self.db.password
        return env

    def _conn_args(self) -> list[str]:
        """Common connection flags shared by mysqldump and mysql."""
        return [
            "--host", self.db.host,
            "--port", str(self.db.port),
            "--user", self.db.user,
        ]

    def _exec_sql(self, sql: str) -> None:
        """Execute a single SQL statement via mysql admin connection."""
        subprocess.run(
            ["mysql", *self._conn_args(), "-e", sql],
            check=True,
            capture_output=True,
            env=self._env(),
        )

    # ------------------------------------------------------------------
    # backup()
    # ------------------------------------------------------------------

    def backup(self, output_path: str) -> None:
        log.info("backup_started", "Starting mysqldump", database=self.db.name)
        try:
            with open(output_path, "wb") as out_file:
                subprocess.run(
                    [
                        "mysqldump",
                        *self._conn_args(),
                        "--single-transaction",
                        "--routines",
                        "--triggers",
                        "--add-drop-database",
                        self.db.db,
                    ],
                    check=True,
                    stdout=out_file,
                    stderr=subprocess.PIPE,
                    env=self._env(),
                )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("backup_failed", "mysqldump exited non-zero", database=self.db.name, error=err)
            raise ProviderError(f"mysqldump failed: {err}")

        size = Path(output_path).stat().st_size
        log.info(
            "backup_completed",
            f"mysqldump complete ({size} bytes)",
            database=self.db.name,
            size_bytes=size,
        )

    # ------------------------------------------------------------------
    # restore()
    # ------------------------------------------------------------------

    def restore(self, backup_path: str, confirm: bool) -> None:
        if not confirm:
            raise ValueError("restore() requires confirm=True to prevent accidental data loss")

        log.info(
            "restore_started",
            "Starting MySQL restore (drop-and-recreate)",
            database=self.db.name,
        )

        # Step 1: Drop the target database if it exists
        try:
            self._exec_sql(f"DROP DATABASE IF EXISTS `{self.db.db}`;")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("restore_failed", "DROP DATABASE failed", database=self.db.name, error=err)
            raise ProviderError(f"DROP DATABASE failed: {err}")

        # Step 2: Recreate the target database
        try:
            self._exec_sql(f"CREATE DATABASE `{self.db.db}`;")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("restore_failed", "CREATE DATABASE failed", database=self.db.name, error=err)
            raise ProviderError(f"CREATE DATABASE failed: {err}")

        # Step 3: Restore the dump into the freshly created database
        try:
            with open(backup_path, "rb") as in_file:
                subprocess.run(
                    ["mysql", *self._conn_args(), self.db.db],
                    check=True,
                    stdin=in_file,
                    stderr=subprocess.PIPE,
                    env=self._env(),
                )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("restore_failed", "mysql restore failed", database=self.db.name, error=err)
            raise ProviderError(f"mysql restore failed: {err}")

        log.info("restore_completed", "MySQL restore complete", database=self.db.name)
