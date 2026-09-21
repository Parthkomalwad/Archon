import shutil
import sqlite3
from pathlib import Path

from app.config import DatabaseConfig
from app.logger import log
from app.providers.base import BaseProvider, ProviderError


class SQLiteProvider(BaseProvider):
    """
    SQLite backup and restore using the sqlite3 Python API.

    Backup:  sqlite3.Connection.backup()  safe hot-copy while the DB is active.
             This is the correct approach; a raw file copy would risk corruption
             if writes occur during the copy.

    Restore: Delete the existing .db file → copy backup file into place.
    """

    def __init__(self, db: DatabaseConfig) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # backup()
    # ------------------------------------------------------------------

    def backup(self, output_path: str) -> None:
        src = self.db.path

        if not Path(src).exists():
            raise ProviderError(
                f"SQLite database file not found: {src}. "
                "Cannot backup a file that does not exist."
            )

        log.info(
            "backup_started",
            f"Starting SQLite hot-copy from {src}",
            database=self.db.name,
        )
        try:
            src_conn = sqlite3.connect(src)
            with sqlite3.connect(output_path) as dst_conn:
                src_conn.backup(dst_conn)
            src_conn.close()
        except Exception as e:
            log.error("backup_failed", "SQLite backup failed", database=self.db.name, error=str(e))
            raise ProviderError(f"SQLite backup failed: {e}")

        size = Path(output_path).stat().st_size
        log.info(
            "backup_completed",
            f"SQLite hot-copy complete ({size} bytes)",
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
            f"Starting SQLite restore to {self.db.path}",
            database=self.db.name,
        )
        try:
            db_file = Path(self.db.path)
            if db_file.exists():
                db_file.unlink()
            shutil.copy2(backup_path, self.db.path)
        except Exception as e:
            log.error("restore_failed", "SQLite restore failed", database=self.db.name, error=str(e))
            raise ProviderError(f"SQLite restore failed: {e}")

        log.info("restore_completed", "SQLite restore complete", database=self.db.name)
