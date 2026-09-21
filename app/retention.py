import re

from app.config import RetentionConfig
from app.logger import log
from app.storage.base import BaseStorage


# ---------------------------------------------------------------------------
# Rotation type extraction
# ---------------------------------------------------------------------------

_ROTATION_RE = re.compile(r'_(hourly|daily|weekly|monthly)\.')


def _get_rotation_type(filename: str) -> str | None:
    """Extract rotation_type from a backup filename, or None if not found."""
    m = _ROTATION_RE.search(filename)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# RetentionManager
# ---------------------------------------------------------------------------

class RetentionManager:
    """
    Enforces per-type backup retention limits for a single database.

    After each backup:
    1. Lists all backup files for the database from its storage backend.
    2. Groups them by rotation type parsed from the filename.
    3. For each type, deletes the oldest files beyond the configured keep count.
    4. Deletes the .sha256 sidecar alongside every deleted backup.

    .-. -
    Overlap rule (built into the Scheduler, not this class):
        When a daily-frequency database runs on the 1st of a month that is also
        a Sunday, the Scheduler tags the file as "monthly" (longer window wins).
        RetentionManager simply groups by whatever is in the filename —
        "monthly"-tagged files are never counted against the weekly limit.
    """

    def enforce(
        self,
        database_name: str,
        storage: BaseStorage,
        retention: RetentionConfig,
    ) -> int:
        """
        Apply retention limits for `database_name` on `storage`.

        Returns the number of backup files deleted (sidecars not counted).
        """
        # List archon_ (current), raven_ and backops_ (migration window)
        all_entries = (
            storage.list(f"archon_{database_name}_")
            + storage.list(f"raven_{database_name}_")
            + storage.list(f"backops_{database_name}_")
        )

        # Separate backup files from their .sha256, .meta, and .schema sidecars
        backup_files = [
            e["filename"]
            for e in all_entries
            if not e["filename"].endswith(".sha256")
            and not e["filename"].endswith(".meta")
            and not e["filename"].endswith(".schema")
        ]

        # Group by rotation type
        by_type: dict[str, list[str]] = {
            "hourly": [],
            "daily": [],
            "weekly": [],
            "monthly": [],
        }
        for filename in backup_files:
            rt = _get_rotation_type(filename)
            if rt and rt in by_type:
                by_type[rt].append(filename)

        limits = {
            "hourly": retention.hourly,
            "daily": retention.daily,
            "weekly": retention.weekly,
            "monthly": retention.monthly,
        }

        deleted = 0
        for rt, filenames in by_type.items():
            limit = limits[rt]
            # Lexicographic sort == chronological sort for ISO timestamps in filenames
            sorted_files = sorted(filenames)  # oldest first
            to_delete = sorted_files[:-limit] if len(sorted_files) > limit else []

            for fn in to_delete:
                storage.delete(fn)
                storage.delete(f"{fn}.sha256")
                storage.delete(f"{fn}.meta")
                storage.delete(f"{fn}.schema")
                log.info(
                    "backup_deleted",
                    f"Retention purged: {fn}",
                    database=database_name,
                )
                deleted += 1

        log.info(
            "retention_run",
            f"Retention complete: {deleted} backup(s) deleted",
            database=database_name,
            deleted_count=deleted,
        )
        return deleted
