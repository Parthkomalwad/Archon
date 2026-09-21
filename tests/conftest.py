"""
Shared pytest fixtures for Archon tests.
Phases 2-7 will add fixtures specific to providers, storage backends,
encryption, and API testing. This file wires up the core config fixtures
used across all phases.
"""
import pytest

from app.config import (
    ApiConfig,
    AppConfig,
    AzureStorageConfig,
    DatabaseConfig,
    EncryptionConfig,
    LocalStorageConfig,
    RetentionConfig,
    S3StorageConfig,
    ScheduleConfig,
)


# ---------------------------------------------------------------------------
# Schedule fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def daily_schedule() -> ScheduleConfig:
    return ScheduleConfig(frequency="daily", at="14:00", timezone="UTC")


@pytest.fixture
def weekly_schedule() -> ScheduleConfig:
    return ScheduleConfig(frequency="weekly", on="sunday", at="03:00", timezone="UTC")


@pytest.fixture
def monthly_schedule() -> ScheduleConfig:
    return ScheduleConfig(frequency="monthly", on=1, at="00:00", timezone="UTC")


@pytest.fixture
def hourly_schedule() -> ScheduleConfig:
    return ScheduleConfig(frequency="hourly", timezone="UTC")


# ---------------------------------------------------------------------------
# Database config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def postgres_db_config(daily_schedule) -> DatabaseConfig:
    return DatabaseConfig(
        name="test_postgres",
        type="postgres",
        host="localhost",
        port=5432,
        db="testdb",
        user="user",
        password="pass",
        schedule=daily_schedule,
        storage="local",
    )


@pytest.fixture
def mongo_db_config(weekly_schedule) -> DatabaseConfig:
    return DatabaseConfig(
        name="test_mongo",
        type="mongodb",
        host="localhost",
        port=27017,
        db="analytics",
        user="mongouser",
        password="mongopass",
        authdb="admin",
        schedule=weekly_schedule,
        storage="local",
    )


@pytest.fixture
def sqlite_db_config(monthly_schedule, tmp_path) -> DatabaseConfig:
    db_path = str(tmp_path / "cache.db")
    return DatabaseConfig(
        name="test_sqlite",
        type="sqlite",
        path=db_path,
        schedule=monthly_schedule,
        storage="local",
    )


# ---------------------------------------------------------------------------
# Storage config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def local_storage_config(tmp_path) -> LocalStorageConfig:
    return LocalStorageConfig(path=str(tmp_path / "backups"))


@pytest.fixture
def s3_storage_config() -> S3StorageConfig:
    return S3StorageConfig(
        bucket="test-bucket",
        region="ap-south-1",
        prefix="raven/",
        access_key="AKIATEST",
        secret_key="secretkey",
    )


@pytest.fixture
def azure_storage_config() -> AzureStorageConfig:
    return AzureStorageConfig(
        container="dbbackups",
        connection_string="DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;",
    )


# ---------------------------------------------------------------------------
# Full AppConfig fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def app_config(postgres_db_config, local_storage_config) -> AppConfig:
    return AppConfig(
        databases=[postgres_db_config],
        storage_backends={"local": local_storage_config},
        encryption=EncryptionConfig(enabled=False),
        retention=RetentionConfig(),
        api=ApiConfig(api_key="test-api-key-12345"),
    )


@pytest.fixture
def app_config_encrypted(postgres_db_config, local_storage_config) -> AppConfig:
    """AppConfig with encryption enabled for encryption tests."""
    return AppConfig(
        databases=[postgres_db_config],
        storage_backends={"local": local_storage_config},
        encryption=EncryptionConfig(
            enabled=True,
            key="dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ=",  # 32-byte base64 test key
        ),
        retention=RetentionConfig(),
        api=ApiConfig(api_key="test-api-key-12345"),
    )
