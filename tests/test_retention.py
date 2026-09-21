"""
Unit tests for RetentionManager (Phase 6).

Uses LocalStorage with a real temp directory so tests verify
actual file creation and deletion without mocking.
"""
import pytest

from app.config import LocalStorageConfig, RetentionConfig
from app.retention import RetentionManager
from app.storage.local import LocalStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_storage(tmp_path) -> LocalStorage:
    return LocalStorage(LocalStorageConfig(path=str(tmp_path / "backups")))


def _write_backup(storage: LocalStorage, db: str, ts: str, rotation: str, ext: str = "sql") -> str:
    """Write a fake backup file + its .sha256 sidecar; returns the backup filename."""
    filename = f"raven_{db}_{ts}_{rotation}.{ext}"
    storage.write(filename, b"backup data")
    storage.write(f"{filename}.sha256", b"abc123")
    return filename


def _retention(daily=7, weekly=4, monthly=12, hourly=24) -> RetentionConfig:
    return RetentionConfig(daily=daily, weekly=weekly, monthly=monthly, hourly=hourly)


# ---------------------------------------------------------------------------
# Daily limit
# ---------------------------------------------------------------------------

class TestDailyRetention:
    def test_8_daily_with_limit_7_deletes_oldest_1(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 9)  # 8 daily backups
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(daily=7))

        assert deleted == 1
        assert not storage.exists(files[0])           # oldest deleted
        assert not storage.exists(f"{files[0]}.sha256")  # sidecar deleted
        for fn in files[1:]:
            assert storage.exists(fn)                 # rest kept

    def test_exactly_at_limit_nothing_deleted(self, tmp_path):
        storage = _make_storage(tmp_path)
        for d in range(1, 8):  # 7 == limit
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
        rm = RetentionManager()
        assert rm.enforce("pg", storage, _retention(daily=7)) == 0

    def test_below_limit_nothing_deleted(self, tmp_path):
        storage = _make_storage(tmp_path)
        for d in range(1, 4):  # 3 < limit 7
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
        rm = RetentionManager()
        assert rm.enforce("pg", storage, _retention(daily=7)) == 0

    def test_10_daily_with_limit_7_deletes_oldest_3(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 11)  # 10 files
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(daily=7))
        assert deleted == 3
        for fn in files[:3]:
            assert not storage.exists(fn)
        for fn in files[3:]:
            assert storage.exists(fn)


# ---------------------------------------------------------------------------
# Weekly limit (independent of daily)
# ---------------------------------------------------------------------------

class TestWeeklyRetention:
    def test_5_weekly_with_limit_4_deletes_oldest_1(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-0{m}-01T00-00-00", "weekly")
            for m in range(1, 6)  # 5 weekly backups
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(weekly=4))
        assert deleted == 1
        assert not storage.exists(files[0])
        assert not storage.exists(f"{files[0]}.sha256")
        for fn in files[1:]:
            assert storage.exists(fn)

    def test_weekly_and_daily_limits_are_independent(self, tmp_path):
        storage = _make_storage(tmp_path)
        # 3 daily (under limit 7) + 5 weekly (over limit 4)
        for d in range(1, 4):
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
        weekly_files = [
            _write_backup(storage, "pg", f"2025-0{m}-01T00-00-00", "weekly")
            for m in range(1, 6)
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(daily=7, weekly=4))
        assert deleted == 1  # only 1 weekly over limit; 0 daily over limit
        assert not storage.exists(weekly_files[0])


# ---------------------------------------------------------------------------
# Monthly limit
# ---------------------------------------------------------------------------

class TestMonthlyRetention:
    def test_monthly_limit_enforced_independently(self, tmp_path):
        storage = _make_storage(tmp_path)
        # 15 monthly backups across 2025-2026, timestamps sort lexicographically
        timestamps = [
            "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01",
            "2025-05-01", "2025-06-01", "2025-07-01", "2025-08-01",
            "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01",
            "2026-01-01", "2026-02-01", "2026-03-01",
        ]
        files = [
            _write_backup(storage, "pg", f"{ts}T00-00-00", "monthly")
            for ts in timestamps
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(monthly=12))
        assert deleted == 3
        for fn in files[:3]:   # oldest 3 deleted
            assert not storage.exists(fn)
        for fn in files[3:]:   # newest 12 kept
            assert storage.exists(fn)


# ---------------------------------------------------------------------------
# Hourly limit
# ---------------------------------------------------------------------------

class TestHourlyRetention:
    def test_hourly_limit_enforced_independently(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-01T{h:02d}-00-00", "hourly")
            for h in range(0, 26)  # 26 hourly, limit 24
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(hourly=24))
        assert deleted == 2
        for fn in files[:2]:
            assert not storage.exists(fn)
        for fn in files[2:]:
            assert storage.exists(fn)


# ---------------------------------------------------------------------------
# Overlap rule: weekly + monthly → kept under monthly window
# ---------------------------------------------------------------------------

class TestOverlapRule:
    def test_monthly_tagged_file_not_threatened_by_weekly_limit(self, tmp_path):
        """
        Overlap scenario: a backup taken on a Sunday that is also the 1st of the
        month is tagged 'monthly' by the Scheduler (monthly > weekly priority).
        RetentionManager groups it in the monthly bucket only  not the weekly
        bucket  so it is never deleted by the weekly limit (4).
        """
        storage = _make_storage(tmp_path)

        # 5 weekly backups → weekly limit is 4 → oldest 1 should be deleted
        weekly_files = [
            _write_backup(storage, "pg", f"2025-0{m}-07T00-00-00", "weekly")
            for m in range(1, 6)
        ]

        # 1 monthly backup (was also a Sunday  tagged 'monthly' by scheduler)
        monthly_file = _write_backup(storage, "pg", "2025-06-01T00-00-00", "monthly")

        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(weekly=4, monthly=12))

        # Weekly: 5 files, limit 4 → oldest 1 weekly deleted
        assert deleted == 1
        assert not storage.exists(weekly_files[0])

        # Monthly file untouched (monthly limit 12, only 1 monthly file)
        assert storage.exists(monthly_file)
        assert storage.exists(f"{monthly_file}.sha256")

    def test_monthly_window_larger_than_weekly(self, tmp_path):
        """Monthly (12) > weekly (4): monthly-tagged files survive longer."""
        storage = _make_storage(tmp_path)
        # Create 5 monthly backups (limit 12  none should be deleted)
        monthly_files = [
            _write_backup(storage, "pg", f"202{y}-01-01T00-00-00", "monthly")
            for y in range(1, 6)
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(weekly=4, monthly=12))
        assert deleted == 0
        for fn in monthly_files:
            assert storage.exists(fn)


# ---------------------------------------------------------------------------
# Per-database retention override
# ---------------------------------------------------------------------------

class TestPerDatabaseOverride:
    def test_db_with_daily_14_keeps_14_not_global_7(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 17)  # 16 daily files
        ]
        per_db_retention = _retention(daily=14)  # override: keep 14
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, per_db_retention)
        assert deleted == 2  # 16 - 14 = 2 oldest deleted
        for fn in files[:2]:
            assert not storage.exists(fn)
        for fn in files[2:]:
            assert storage.exists(fn)

    def test_global_fallback_applies_when_no_override(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 9)  # 8 daily files
        ]
        global_retention = _retention(daily=7)  # global: keep 7
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, global_retention)
        assert deleted == 1  # 8 - 7 = 1 oldest
        assert not storage.exists(files[0])


# ---------------------------------------------------------------------------
# .sha256 sidecar deletion
# ---------------------------------------------------------------------------

class TestSidecarDeletion:
    def test_sidecar_deleted_with_backup(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 9)  # 8 files, limit 7
        ]
        rm = RetentionManager()
        rm.enforce("pg", storage, _retention(daily=7))

        # Backup deleted
        assert not storage.exists(files[0])
        # Sidecar also deleted
        assert not storage.exists(f"{files[0]}.sha256")

    def test_sidecar_kept_when_backup_kept(self, tmp_path):
        storage = _make_storage(tmp_path)
        files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 8)  # 7 files == limit
        ]
        rm = RetentionManager()
        rm.enforce("pg", storage, _retention(daily=7))

        for fn in files:
            assert storage.exists(fn)
            assert storage.exists(f"{fn}.sha256")

    def test_sidecars_not_counted_toward_retention_limit(self, tmp_path):
        """
        .sha256 files must be filtered out before grouping —
        they should never be treated as backup files.
        """
        storage = _make_storage(tmp_path)
        for d in range(1, 8):
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")

        # Total file count = 14 (7 backups + 7 sidecars), but only 7 backups
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(daily=7))
        assert deleted == 0  # exactly at limit, nothing should be deleted


# ---------------------------------------------------------------------------
# Cross-database isolation
# ---------------------------------------------------------------------------

class TestCrossDbIsolation:
    def test_retention_only_affects_target_database(self, tmp_path):
        storage = _make_storage(tmp_path)
        # 8 backups for "pg" (over limit 7)
        pg_files = [
            _write_backup(storage, "pg", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 9)
        ]
        # 3 backups for "mongo" (under limit 7)
        mongo_files = [
            _write_backup(storage, "mongo", f"2025-01-{d:02d}T00-00-00", "daily")
            for d in range(1, 4)
        ]
        rm = RetentionManager()
        deleted = rm.enforce("pg", storage, _retention(daily=7))

        assert deleted == 1
        assert not storage.exists(pg_files[0])
        # mongo files untouched
        for fn in mongo_files:
            assert storage.exists(fn)
            assert storage.exists(f"{fn}.sha256")
