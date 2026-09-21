import subprocess
from pathlib import Path

from app.config import DatabaseConfig
from app.logger import log
from app.providers.base import BaseProvider, ProviderError


class MongoProvider(BaseProvider):
    """
    MongoDB backup and restore using mongodump / mongorestore.

    Backup:  mongodump --archive=<file>  → single binary archive file
    Restore: mongorestore --archive=<file> --drop  (drop-and-recreate semantics)

    The authdb field (default: 'admin') is passed as --authenticationDatabase
    to both mongodump and mongorestore.
    """

    def __init__(self, db: DatabaseConfig) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _common_args(self) -> list[str]:
        """Connection and auth flags shared by mongodump and mongorestore."""
        return [
            "--host", self.db.host,
            "--port", str(self.db.port),
            "--username", self.db.user,
            "--password", self.db.password,
            "--authenticationDatabase", self.db.authdb,
        ]

    # ------------------------------------------------------------------
    # backup()
    # ------------------------------------------------------------------

    def backup(self, output_path: str) -> None:
        log.info("backup_started", "Starting mongodump", database=self.db.name)
        try:
            subprocess.run(
                [
                    "mongodump",
                    *self._common_args(),
                    "--db", self.db.db,
                    f"--archive={output_path}",
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("backup_failed", "mongodump exited non-zero", database=self.db.name, error=err)
            raise ProviderError(f"mongodump failed: {err}")

        size = Path(output_path).stat().st_size
        log.info(
            "backup_completed",
            f"mongodump complete ({size} bytes)",
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
            "Starting MongoDB restore (--drop)",
            database=self.db.name,
        )
        try:
            subprocess.run(
                [
                    "mongorestore",
                    *self._common_args(),
                    "--db", self.db.db,
                    f"--archive={backup_path}",
                    "--drop",
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")
            log.error("restore_failed", "mongorestore failed", database=self.db.name, error=err)
            raise ProviderError(f"mongorestore failed: {err}")

        log.info("restore_completed", "MongoDB restore complete", database=self.db.name)
