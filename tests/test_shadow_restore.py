"""
Unit tests for the shadow restore strategy (Phase 11).

All subprocess calls are mocked  no real PostgreSQL server required.
"""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from app.config import ConfigError, DatabaseConfig, ScheduleConfig
from app.providers.base import ProviderError
from app.providers.postgres import PostgresProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pg_db(restore_strategy: str = "drop_recreate", db: str = "mydb") -> DatabaseConfig:
    return DatabaseConfig(
        name="testdb",
        type="postgres",
        host="localhost",
        port=5432,
        db=db,
        user="admin",
        password="secret",
        schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
        storage="local",
        restore_strategy=restore_strategy,
    )


@pytest.fixture
def pg_db_drop_recreate() -> DatabaseConfig:
    return _make_pg_db("drop_recreate")


@pytest.fixture
def pg_db_shadow() -> DatabaseConfig:
    return _make_pg_db("shadow", db="production")


@pytest.fixture
def backup_path(tmp_path) -> str:
    p = tmp_path / "backup.sql"
    p.write_bytes(b"-- sql dump")
    return str(p)


def _cpe(stderr: str = "db error") -> subprocess.CalledProcessError:
    """Create a CalledProcessError with a stderr message."""
    err = subprocess.CalledProcessError(1, "psql", stderr=stderr.encode())
    return err


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

class TestRestoreStrategyConfig:
    def test_drop_recreate_is_valid_for_postgres(self):
        db = _make_pg_db("drop_recreate")
        assert db.restore_strategy == "drop_recreate"

    def test_shadow_is_valid_for_postgres(self):
        db = _make_pg_db("shadow")
        assert db.restore_strategy == "shadow"

    def test_shadow_on_sqlite_raises_value_error(self):
        with pytest.raises(ValueError, match="shadow.*only supported for postgres"):
            DatabaseConfig(
                name="bad",
                type="sqlite",
                path="/tmp/x.db",
                schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
                storage="local",
                restore_strategy="shadow",
            )

    def test_shadow_on_mongodb_raises_value_error(self):
        with pytest.raises(ValueError, match="shadow.*only supported for postgres"):
            DatabaseConfig(
                name="bad",
                type="mongodb",
                host="localhost", port=27017, db="d", user="u", password="p",
                schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
                storage="local",
                restore_strategy="shadow",
            )

    def test_invalid_strategy_raises_value_error(self):
        with pytest.raises(ValueError, match="invalid restore_strategy"):
            DatabaseConfig(
                name="bad",
                type="postgres",
                host="localhost", port=5432, db="d", user="u", password="p",
                schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
                storage="local",
                restore_strategy="blue_green",
            )

    def test_default_strategy_is_drop_recreate(self):
        db = DatabaseConfig(
            name="pg",
            type="postgres",
            host="localhost", port=5432, db="d", user="u", password="p",
            schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
            storage="local",
        )
        assert db.restore_strategy == "drop_recreate"


# ---------------------------------------------------------------------------
# Drop-recreate still works (restore_strategy: drop_recreate)
# ---------------------------------------------------------------------------

class TestDropRecreateDispatch:
    def test_drop_recreate_calls_old_pipeline(self, pg_db_drop_recreate, backup_path):
        """With drop_recreate, restore() must use the 3-step DROP/CREATE/restore pipeline."""
        provider = PostgresProvider(pg_db_drop_recreate)

        with patch("app.providers.postgres.subprocess.run") as mock_run:
            provider.restore(backup_path, confirm=True)

        assert mock_run.call_count == 3
        cmds = [mock_run.call_args_list[i][0][0] for i in range(3)]
        assert "DROP DATABASE IF EXISTS" in " ".join(cmds[0])
        assert "CREATE DATABASE" in " ".join(cmds[1])
        assert backup_path in cmds[2]

    def test_drop_recreate_does_not_call_shadow_logic(self, pg_db_drop_recreate, backup_path):
        provider = PostgresProvider(pg_db_drop_recreate)

        with patch.object(provider, "restore_shadow") as mock_shadow, \
             patch("app.providers.postgres.subprocess.run"):
            provider.restore(backup_path, confirm=True)

        mock_shadow.assert_not_called()


# ---------------------------------------------------------------------------
# Shadow restore  happy path
# ---------------------------------------------------------------------------

class TestShadowRestoreHappyPath:
    def test_all_six_steps_run_in_order(self, pg_db_shadow, backup_path):
        """
        All 6 subprocess calls must fire in the correct order:
        1. CREATE shadow
        2. psql -f to shadow
        3. pg_terminate_backend (terminate conns)
        4. ALTER DATABASE production → production_raven_old_...
        5. ALTER DATABASE production_raven_shadow_... → production
        6. DROP DATABASE IF EXISTS production_raven_old_...
        """
        provider = PostgresProvider(pg_db_shadow)

        with patch("app.providers.postgres.subprocess.run") as mock_run:
            provider.restore_shadow(backup_path, "production", confirm=True)

        assert mock_run.call_count == 6, f"Expected 6 calls, got {mock_run.call_count}"

        all_cmds = [" ".join(mock_run.call_args_list[i][0][0])
                    for i in range(6)]

        assert "CREATE DATABASE" in all_cmds[0]
        assert "raven_shadow_" in all_cmds[0]

        assert backup_path in all_cmds[1]
        assert "raven_shadow_" in all_cmds[1]

        assert "pg_terminate_backend" in all_cmds[2]
        assert "production" in all_cmds[2]

        assert "ALTER DATABASE" in all_cmds[3]
        assert "raven_old_" in all_cmds[3]

        assert "ALTER DATABASE" in all_cmds[4]
        assert "raven_shadow_" in all_cmds[4]

        assert "DROP DATABASE IF EXISTS" in all_cmds[5]
        assert "raven_old_" in all_cmds[5]

    def test_restore_via_dispatch_uses_shadow(self, pg_db_shadow, backup_path):
        """restore() with strategy=shadow must call restore_shadow(), not old pipeline."""
        provider = PostgresProvider(pg_db_shadow)

        with patch.object(provider, "restore_shadow") as mock_shadow:
            provider.restore(backup_path, confirm=True)

        mock_shadow.assert_called_once_with(backup_path, pg_db_shadow.db, True)

    def test_confirm_false_raises_before_any_subprocess(self, pg_db_shadow, backup_path):
        provider = PostgresProvider(pg_db_shadow)

        with patch("app.providers.postgres.subprocess.run") as mock_run:
            with pytest.raises(ValueError, match="confirm=True"):
                provider.restore(backup_path, confirm=False)

        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Shadow restore  step failure and rollback
# ---------------------------------------------------------------------------

class TestShadowRestoreStepFailures:
    """Each test simulates one step failing and verifies the correct rollback."""

    def _side_effects(self, *items) -> list:
        """Build a side_effect list from MagicMock (success) or exception (failure)."""
        effects = []
        for item in items:
            if isinstance(item, Exception):
                effects.append(item)
            else:
                effects.append(MagicMock())
        return effects

    def test_step1_failure_raises_provider_error_no_cleanup(self, pg_db_shadow, backup_path):
        """
        Step 1 (CREATE shadow) fails → ProviderError raised, no cleanup needed
        (shadow was never created).
        """
        provider = PostgresProvider(pg_db_shadow)

        with patch("app.providers.postgres.subprocess.run",
                   side_effect=self._side_effects(_cpe("create failed"))):
            with pytest.raises(ProviderError, match="step 1"):
                provider.restore_shadow(backup_path, "production", confirm=True)

    def test_step2_failure_drops_shadow(self, pg_db_shadow, backup_path):
        """
        Step 2 (RESTORE to shadow) fails → shadow DB is dropped, ProviderError raised.
        Expected calls: CREATE shadow, RESTORE (fail), DROP shadow.
        """
        provider = PostgresProvider(pg_db_shadow)

        effects = self._side_effects(
            None,                # step 1: CREATE shadow succeeds
            _cpe("restore fail"),  # step 2: RESTORE fails
            None,                # cleanup: DROP shadow
        )

        with patch("app.providers.postgres.subprocess.run", side_effect=effects) as mock_run:
            with pytest.raises(ProviderError, match="step 2"):
                provider.restore_shadow(backup_path, "production", confirm=True)

        # 3 calls: CREATE, RESTORE(fail), DROP(cleanup)
        assert mock_run.call_count == 3
        cleanup_cmd = " ".join(mock_run.call_args_list[2][0][0])
        assert "DROP DATABASE IF EXISTS" in cleanup_cmd
        assert "raven_shadow_" in cleanup_cmd

    def test_step3_failure_drops_shadow_original_untouched(self, pg_db_shadow, backup_path):
        """
        Step 3 (TERMINATE) fails → shadow dropped, ProviderError raised.
        Original is untouched (no rename happened).
        """
        provider = PostgresProvider(pg_db_shadow)

        effects = self._side_effects(
            None,              # step 1: CREATE shadow
            None,              # step 2: RESTORE to shadow
            _cpe("terminate fail"),  # step 3: TERMINATE fails
            None,              # cleanup: DROP shadow
        )

        with patch("app.providers.postgres.subprocess.run", side_effect=effects) as mock_run:
            with pytest.raises(ProviderError, match="step 3"):
                provider.restore_shadow(backup_path, "production", confirm=True)

        assert mock_run.call_count == 4
        cleanup_cmd = " ".join(mock_run.call_args_list[3][0][0])
        assert "DROP DATABASE IF EXISTS" in cleanup_cmd
        assert "raven_shadow_" in cleanup_cmd

    def test_step4_failure_drops_shadow_original_keeps_name(self, pg_db_shadow, backup_path):
        """
        Step 4 (RENAME target→old) fails → shadow dropped, ProviderError raised.
        Original DB still has its original name 'production'.
        """
        provider = PostgresProvider(pg_db_shadow)

        effects = self._side_effects(
            None,               # step 1: CREATE shadow
            None,               # step 2: RESTORE to shadow
            None,               # step 3: TERMINATE conns
            _cpe("rename fail"),  # step 4: RENAME target→old fails
            None,               # cleanup: DROP shadow
        )

        with patch("app.providers.postgres.subprocess.run", side_effect=effects) as mock_run:
            with pytest.raises(ProviderError, match="step 4"):
                provider.restore_shadow(backup_path, "production", confirm=True)

        assert mock_run.call_count == 5
        # Step 4 failed before any rename  original DB name is untouched
        # Cleanup is only DROP shadow (no RENAME needed for rollback)
        cleanup_cmd = " ".join(mock_run.call_args_list[4][0][0])
        assert "DROP DATABASE IF EXISTS" in cleanup_cmd
        assert "raven_shadow_" in cleanup_cmd

    def test_step5_failure_renames_old_back_and_drops_shadow(self, pg_db_shadow, backup_path):
        """
        Step 5 (RENAME shadow→target) fails → original name restored, shadow dropped.
        Rollback: ALTER old→target + DROP shadow.
        """
        provider = PostgresProvider(pg_db_shadow)

        effects = self._side_effects(
            None,                  # step 1: CREATE shadow
            None,                  # step 2: RESTORE to shadow
            None,                  # step 3: TERMINATE conns
            None,                  # step 4: RENAME target→old (succeeds)
            _cpe("rename shadow fail"),  # step 5: RENAME shadow→target fails
            None,                  # rollback: RENAME old→target
            None,                  # rollback: DROP shadow
        )

        with patch("app.providers.postgres.subprocess.run", side_effect=effects) as mock_run:
            with pytest.raises(ProviderError, match="step 5"):
                provider.restore_shadow(backup_path, "production", confirm=True)

        assert mock_run.call_count == 7

        rollback1 = " ".join(mock_run.call_args_list[5][0][0])
        rollback2 = " ".join(mock_run.call_args_list[6][0][0])

        # First rollback: rename old → production
        assert "ALTER DATABASE" in rollback1
        assert "raven_old_" in rollback1
        assert "production" in rollback1

        # Second rollback: drop shadow
        assert "DROP DATABASE IF EXISTS" in rollback2
        assert "raven_shadow_" in rollback2

    def test_step6_failure_logs_warning_but_returns_success(self, pg_db_shadow, backup_path):
        """
        Step 6 (DROP old) fails → warning is logged, no exception raised.
        The restore itself is considered complete.
        """
        provider = PostgresProvider(pg_db_shadow)

        effects = self._side_effects(
            None,   # step 1: CREATE shadow
            None,   # step 2: RESTORE to shadow
            None,   # step 3: TERMINATE conns
            None,   # step 4: RENAME target→old
            None,   # step 5: RENAME shadow→target
            _cpe("drop old fail"),  # step 6: DROP old fails
        )

        with patch("app.providers.postgres.subprocess.run", side_effect=effects), \
             patch("app.providers.postgres.log") as mock_log:
            # Must NOT raise  step 6 failure is non-critical
            provider.restore_shadow(backup_path, "production", confirm=True)

        # Warning must be logged
        warning_calls = [
            c for c in mock_log.warning.call_args_list
            if "step 6" in str(c).lower() or "manual cleanup" in str(c).lower()
        ]
        assert warning_calls, "Expected a warning log for step 6 failure"

        # shadow_restore_completed must still be logged
        completed_calls = [
            c for c in mock_log.info.call_args_list
            if "shadow_restore_completed" in str(c)
        ]
        assert completed_calls, "Expected shadow_restore_completed log event after step 6 failure"
