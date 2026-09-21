"""
Unit tests for DB provider classes (Phase 2).

All subprocess calls are mocked  no real DB connections required.
"""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from app.config import DatabaseConfig, ScheduleConfig
from app.providers import get_provider
from app.providers.base import ProviderError
from app.providers.postgres import PostgresProvider
from app.providers.mongodb import MongoProvider
from app.providers.sqlite import SQLiteProvider


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_db(type_: str, **kwargs) -> DatabaseConfig:
    defaults = dict(
        name="testdb",
        type=type_,
        host="localhost",
        port=5432,
        db="mydb",
        user="admin",
        password="secret",
        schedule=ScheduleConfig(frequency="daily", at="02:00", timezone="UTC"),
        storage="local",
    )
    defaults.update(kwargs)
    return DatabaseConfig(**defaults)


@pytest.fixture
def pg_db():
    return _make_db("postgres", port=5432)


@pytest.fixture
def mongo_db():
    return _make_db("mongodb", port=27017)


@pytest.fixture
def mongo_db_custom_authdb():
    return _make_db("mongodb", port=27017, authdb="myauthdb")


@pytest.fixture
def sqlite_db(tmp_path):
    # Create a real (but empty) SQLite file for source tests
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return _make_db("sqlite", path=str(db_file), host="", port=0, db="", user="", password="")


# ---------------------------------------------------------------------------
# ProviderFactory
# ---------------------------------------------------------------------------

class TestProviderFactory:
    def test_returns_postgres_provider(self, pg_db):
        provider = get_provider(pg_db)
        assert isinstance(provider, PostgresProvider)

    def test_returns_mongo_provider(self, mongo_db):
        provider = get_provider(mongo_db)
        assert isinstance(provider, MongoProvider)

    def test_returns_sqlite_provider(self, sqlite_db):
        provider = get_provider(sqlite_db)
        assert isinstance(provider, SQLiteProvider)

    def test_unknown_type_raises_provider_error(self):
        # Bypass Pydantic validation to create an invalid-type config
        db = _make_db("postgres")
        object.__setattr__(db, "type", "mysql")
        with pytest.raises(ProviderError, match="mysql"):
            get_provider(db)


# ---------------------------------------------------------------------------
# PostgresProvider
# ---------------------------------------------------------------------------

class TestPostgresProvider:
    def test_backup_calls_pg_dump_with_correct_args(self, pg_db, tmp_path):
        output = str(tmp_path / "backup.sql")
        provider = PostgresProvider(pg_db)

        with patch("app.providers.postgres.subprocess.run") as mock_run:
            # Make pg_dump create the output file so stat() works
            Path(output).write_bytes(b"-- sql dump")
            provider.backup(output)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "pg_dump"
        assert "-h" in cmd and "localhost" in cmd
        assert "-p" in cmd and "5432" in cmd
        assert "-U" in cmd and "admin" in cmd
        assert "-d" in cmd and "mydb" in cmd
        assert "-f" in cmd and output in cmd

    def test_backup_injects_pgpassword(self, pg_db, tmp_path):
        output = str(tmp_path / "backup.sql")
        Path(output).write_bytes(b"-- sql dump")
        provider = PostgresProvider(pg_db)

        with patch("app.providers.postgres.subprocess.run") as mock_run:
            provider.backup(output)

        env = mock_run.call_args[1]["env"]
        assert env["PGPASSWORD"] == "secret"

    def test_backup_raises_provider_error_on_failure(self, pg_db, tmp_path):
        import subprocess
        output = str(tmp_path / "backup.sql")
        provider = PostgresProvider(pg_db)

        err = subprocess.CalledProcessError(1, "pg_dump", stderr=b"connection refused")
        with patch("app.providers.postgres.subprocess.run", side_effect=err):
            with pytest.raises(ProviderError, match="pg_dump failed"):
                provider.backup(output)

    def test_restore_requires_confirm_true(self, pg_db):
        provider = PostgresProvider(pg_db)
        with pytest.raises(ValueError, match="confirm=True"):
            provider.restore("backup.sql", confirm=False)

    def test_restore_calls_drop_create_and_psql(self, pg_db, tmp_path):
        backup = str(tmp_path / "backup.sql")
        Path(backup).write_bytes(b"-- sql")
        provider = PostgresProvider(pg_db)

        with patch("app.providers.postgres.subprocess.run") as mock_run:
            provider.restore(backup, confirm=True)

        assert mock_run.call_count == 3
        cmds = [mock_run.call_args_list[i][0][0] for i in range(3)]

        # Step 1: DROP DATABASE
        assert "DROP DATABASE IF EXISTS" in " ".join(cmds[0])
        # Step 2: CREATE DATABASE
        assert "CREATE DATABASE" in " ".join(cmds[1])
        # Step 3: restore SQL file
        assert backup in cmds[2]

    def test_restore_raises_provider_error_on_failure(self, pg_db, tmp_path):
        import subprocess
        backup = str(tmp_path / "backup.sql")
        provider = PostgresProvider(pg_db)

        err = subprocess.CalledProcessError(1, "psql", stderr=b"role does not exist")
        with patch("app.providers.postgres.subprocess.run", side_effect=err):
            with pytest.raises(ProviderError, match="PostgreSQL restore failed"):
                provider.restore(backup, confirm=True)


# ---------------------------------------------------------------------------
# MongoProvider
# ---------------------------------------------------------------------------

class TestMongoProvider:
    def test_backup_calls_mongodump_with_correct_args(self, mongo_db, tmp_path):
        output = str(tmp_path / "backup.archive")
        Path(output).write_bytes(b"\x00binary")
        provider = MongoProvider(mongo_db)

        with patch("app.providers.mongodb.subprocess.run") as mock_run:
            provider.backup(output)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "mongodump"
        assert "--host" in cmd and "localhost" in cmd
        assert "--port" in cmd and "27017" in cmd
        assert "--username" in cmd and "admin" in cmd
        assert "--password" in cmd and "secret" in cmd
        assert "--db" in cmd and "mydb" in cmd
        assert f"--archive={output}" in cmd

    def test_backup_uses_default_authdb_admin(self, mongo_db, tmp_path):
        output = str(tmp_path / "backup.archive")
        Path(output).write_bytes(b"\x00binary")
        provider = MongoProvider(mongo_db)

        with patch("app.providers.mongodb.subprocess.run") as mock_run:
            provider.backup(output)

        cmd = mock_run.call_args[0][0]
        assert "--authenticationDatabase" in cmd
        idx = cmd.index("--authenticationDatabase")
        assert cmd[idx + 1] == "admin"

    def test_backup_uses_custom_authdb(self, mongo_db_custom_authdb, tmp_path):
        output = str(tmp_path / "backup.archive")
        Path(output).write_bytes(b"\x00binary")
        provider = MongoProvider(mongo_db_custom_authdb)

        with patch("app.providers.mongodb.subprocess.run") as mock_run:
            provider.backup(output)

        cmd = mock_run.call_args[0][0]
        idx = cmd.index("--authenticationDatabase")
        assert cmd[idx + 1] == "myauthdb"

    def test_backup_raises_provider_error_on_failure(self, mongo_db, tmp_path):
        import subprocess
        output = str(tmp_path / "backup.archive")
        provider = MongoProvider(mongo_db)

        err = subprocess.CalledProcessError(1, "mongodump", stderr=b"auth failed")
        with patch("app.providers.mongodb.subprocess.run", side_effect=err):
            with pytest.raises(ProviderError, match="mongodump failed"):
                provider.backup(output)

    def test_restore_requires_confirm_true(self, mongo_db):
        provider = MongoProvider(mongo_db)
        with pytest.raises(ValueError, match="confirm=True"):
            provider.restore("backup.archive", confirm=False)

    def test_restore_calls_mongorestore_with_drop(self, mongo_db, tmp_path):
        backup = str(tmp_path / "backup.archive")
        Path(backup).write_bytes(b"\x00binary")
        provider = MongoProvider(mongo_db)

        with patch("app.providers.mongodb.subprocess.run") as mock_run:
            provider.restore(backup, confirm=True)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "mongorestore"
        assert "--drop" in cmd
        assert f"--archive={backup}" in cmd
        assert "--authenticationDatabase" in cmd

    def test_restore_raises_provider_error_on_failure(self, mongo_db, tmp_path):
        import subprocess
        backup = str(tmp_path / "backup.archive")
        provider = MongoProvider(mongo_db)

        err = subprocess.CalledProcessError(1, "mongorestore", stderr=b"ns not found")
        with patch("app.providers.mongodb.subprocess.run", side_effect=err):
            with pytest.raises(ProviderError, match="mongorestore failed"):
                provider.restore(backup, confirm=True)


# ---------------------------------------------------------------------------
# SQLiteProvider
# ---------------------------------------------------------------------------

class TestSQLiteProvider:
    def test_backup_uses_sqlite3_backup_api(self, sqlite_db, tmp_path):
        """Verify that sqlite3.Connection.backup() is called, not shutil.copy."""
        output = str(tmp_path / "backup.db")
        provider = SQLiteProvider(sqlite_db)

        # Use a real sqlite3.backup()  no subprocess involved
        with patch("app.providers.sqlite.sqlite3.connect") as mock_connect:
            mock_src = MagicMock()
            mock_dst = MagicMock()
            mock_connect.side_effect = [mock_src, mock_dst]
            # Make context manager work for dst_conn
            mock_dst.__enter__ = MagicMock(return_value=mock_dst)
            mock_dst.__exit__ = MagicMock(return_value=False)

            # Need the output file to exist for stat()
            Path(output).write_bytes(b"SQLite format 3")
            provider.backup(output)

        mock_src.backup.assert_called_once_with(mock_dst)
        mock_src.close.assert_called_once()

    def test_backup_raises_if_source_missing(self, tmp_path):
        """Backup should fail fast if source .db file does not exist."""
        db = _make_db("sqlite", path=str(tmp_path / "nonexistent.db"),
                      host="", port=0, db="", user="", password="")
        provider = SQLiteProvider(db)
        with pytest.raises(ProviderError, match="not found"):
            provider.backup(str(tmp_path / "out.db"))

    def test_backup_raises_provider_error_on_sqlite_exception(self, sqlite_db, tmp_path):
        output = str(tmp_path / "backup.db")
        provider = SQLiteProvider(sqlite_db)

        with patch("app.providers.sqlite.sqlite3.connect", side_effect=sqlite3.Error("disk full")):
            with pytest.raises(ProviderError, match="SQLite backup failed"):
                provider.backup(output)

    def test_restore_requires_confirm_true(self, sqlite_db):
        provider = SQLiteProvider(sqlite_db)
        with pytest.raises(ValueError, match="confirm=True"):
            provider.restore("backup.db", confirm=False)

    def test_restore_deletes_existing_and_copies(self, sqlite_db, tmp_path):
        """Restore should remove existing db file and copy backup in its place."""
        backup = str(tmp_path / "backup.db")
        Path(backup).write_bytes(b"SQLite format 3")

        provider = SQLiteProvider(sqlite_db)

        with patch("app.providers.sqlite.shutil.copy2") as mock_copy:
            provider.restore(backup, confirm=True)

        # Original file removed (it was a real file we created in fixture)
        assert not Path(sqlite_db.path).exists()
        mock_copy.assert_called_once_with(backup, sqlite_db.path)

    def test_restore_raises_provider_error_on_failure(self, sqlite_db, tmp_path):
        backup = str(tmp_path / "backup.db")
        provider = SQLiteProvider(sqlite_db)

        with patch("app.providers.sqlite.shutil.copy2", side_effect=OSError("permission denied")):
            with pytest.raises(ProviderError, match="SQLite restore failed"):
                provider.restore(backup, confirm=True)
