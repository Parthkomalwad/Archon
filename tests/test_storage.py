"""
Unit tests for storage backends (Phase 3).

Local storage tests use a real temp directory.
S3 and Azure tests mock the cloud SDK clients entirely.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from app.config import LocalStorageConfig, S3StorageConfig, AzureStorageConfig
from app.storage import get_storage
from app.storage.base import StorageError
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage
from app.storage.azure import AzureStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def local_cfg(tmp_path):
    return LocalStorageConfig(path=str(tmp_path / "backups"))


@pytest.fixture
def s3_cfg():
    return S3StorageConfig(
        bucket="my-bucket",
        region="us-east-1",
        prefix="raven/",
        access_key="AKIATEST",
        secret_key="secretkey",
    )


@pytest.fixture
def azure_cfg():
    return AzureStorageConfig(
        container="backups",
        connection_string="DefaultEndpointsProtocol=https;AccountName=test;AccountKey=abc123==;EndpointSuffix=core.windows.net",
    )


# ---------------------------------------------------------------------------
# StorageFactory
# ---------------------------------------------------------------------------

class TestStorageFactory:
    def test_returns_local_storage(self, local_cfg):
        with patch("app.storage.local.LocalStorage.__init__", return_value=None):
            store = get_storage(local_cfg)
        assert isinstance(store, LocalStorage)

    def test_returns_s3_storage(self, s3_cfg):
        with patch("app.storage.s3.boto3.client"):
            store = get_storage(s3_cfg)
        assert isinstance(store, S3Storage)

    def test_returns_azure_storage(self, azure_cfg):
        with patch("app.storage.azure.BlobServiceClient.from_connection_string") as mock_bsc:
            mock_bsc.return_value.get_container_client.return_value = MagicMock()
            store = get_storage(azure_cfg)
        assert isinstance(store, AzureStorage)

    def test_unknown_config_raises_storage_error(self):
        with pytest.raises(StorageError, match="Unknown storage config type"):
            get_storage(object())


# ---------------------------------------------------------------------------
# LocalStorage
# ---------------------------------------------------------------------------

class TestLocalStorage:
    def test_write_creates_directory_and_file(self, local_cfg, tmp_path):
        store = LocalStorage(local_cfg)
        store.write("backup.sql", b"SELECT 1;")
        assert (tmp_path / "backups" / "backup.sql").read_bytes() == b"SELECT 1;"

    def test_read_returns_bytes(self, local_cfg, tmp_path):
        store = LocalStorage(local_cfg)
        store.write("file.db", b"\x00\x01\x02")
        assert store.read("file.db") == b"\x00\x01\x02"

    def test_read_raises_on_missing_file(self, local_cfg):
        store = LocalStorage(local_cfg)
        with pytest.raises(StorageError, match="not found"):
            store.read("nonexistent.sql")

    def test_list_returns_matching_files(self, local_cfg, tmp_path):
        store = LocalStorage(local_cfg)
        store.write("raven_pg_2025-01-01_daily.sql", b"a")
        store.write("raven_pg_2025-01-02_daily.sql", b"bb")
        store.write("raven_mongo_2025-01-01_daily.archive", b"ccc")

        results = store.list("raven_pg_")
        names = [r["filename"] for r in results]
        assert "raven_pg_2025-01-01_daily.sql" in names
        assert "raven_pg_2025-01-02_daily.sql" in names
        assert "raven_mongo_2025-01-01_daily.archive" not in names

    def test_list_returns_size_bytes(self, local_cfg):
        store = LocalStorage(local_cfg)
        store.write("file.sql", b"hello")
        results = store.list("file")
        assert results[0]["size_bytes"] == 5

    def test_list_empty_when_no_match(self, local_cfg):
        store = LocalStorage(local_cfg)
        store.write("other.sql", b"x")
        assert store.list("raven_") == []

    def test_list_empty_when_directory_missing(self, local_cfg):
        store = LocalStorage(local_cfg)
        assert store.list("anything") == []

    def test_delete_removes_file(self, local_cfg, tmp_path):
        store = LocalStorage(local_cfg)
        store.write("todelete.sql", b"data")
        assert store.exists("todelete.sql")
        store.delete("todelete.sql")
        assert not store.exists("todelete.sql")

    def test_delete_is_noop_on_missing_file(self, local_cfg):
        store = LocalStorage(local_cfg)
        store.delete("nonexistent.sql")  # must not raise

    def test_exists_true_for_existing_file(self, local_cfg):
        store = LocalStorage(local_cfg)
        store.write("exists.sql", b"x")
        assert store.exists("exists.sql") is True

    def test_exists_false_for_missing_file(self, local_cfg):
        store = LocalStorage(local_cfg)
        assert store.exists("missing.sql") is False

    def test_write_read_roundtrip(self, local_cfg):
        store = LocalStorage(local_cfg)
        data = b"binary\x00\xff\xfe content"
        store.write("roundtrip.db", data)
        assert store.read("roundtrip.db") == data


# ---------------------------------------------------------------------------
# S3Storage
# ---------------------------------------------------------------------------

class TestS3Storage:
    @pytest.fixture
    def mock_s3_client(self):
        with patch("app.storage.s3.boto3.client") as mock_boto:
            client = MagicMock()
            mock_boto.return_value = client
            yield client

    @pytest.fixture
    def store(self, s3_cfg, mock_s3_client):
        return S3Storage(s3_cfg)

    def test_write_calls_put_object_with_correct_key(self, store, mock_s3_client):
        store.write("backup.sql", b"data")
        mock_s3_client.put_object.assert_called_once_with(
            Bucket="my-bucket", Key="raven/backup.sql", Body=b"data"
        )

    def test_read_calls_get_object_and_returns_body(self, store, mock_s3_client):
        mock_s3_client.get_object.return_value = {"Body": MagicMock(read=lambda: b"content")}
        result = store.read("backup.sql")
        assert result == b"content"
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="raven/backup.sql"
        )

    def test_read_raises_storage_error_on_no_such_key(self, store, mock_s3_client):
        from botocore.exceptions import ClientError
        mock_s3_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
        )
        with pytest.raises(StorageError, match="not found"):
            store.read("missing.sql")

    def test_list_strips_prefix_from_filenames(self, store, mock_s3_client):
        page = {"Contents": [
            {"Key": "raven/raven_pg_daily.sql", "Size": 100},
            {"Key": "raven/raven_pg_weekly.sql", "Size": 200},
        ]}
        paginator = MagicMock()
        paginator.paginate.return_value = [page]
        mock_s3_client.get_paginator.return_value = paginator

        results = store.list("raven_pg_")
        assert {"filename": "raven_pg_daily.sql", "size_bytes": 100} in results
        assert {"filename": "raven_pg_weekly.sql", "size_bytes": 200} in results

    def test_list_empty_page_returns_empty(self, store, mock_s3_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]  # no "Contents" key
        mock_s3_client.get_paginator.return_value = paginator
        assert store.list("raven_") == []

    def test_delete_calls_delete_object(self, store, mock_s3_client):
        store.delete("old.sql")
        mock_s3_client.delete_object.assert_called_once_with(
            Bucket="my-bucket", Key="raven/old.sql"
        )

    def test_exists_returns_true_on_head_object_success(self, store, mock_s3_client):
        mock_s3_client.head_object.return_value = {}
        assert store.exists("backup.sql") is True

    def test_exists_returns_false_on_404(self, store, mock_s3_client):
        from botocore.exceptions import ClientError
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        assert store.exists("missing.sql") is False


# ---------------------------------------------------------------------------
# AzureStorage
# ---------------------------------------------------------------------------

class TestAzureStorage:
    @pytest.fixture
    def mock_container_client(self):
        with patch("app.storage.azure.BlobServiceClient.from_connection_string") as mock_bsc:
            container_client = MagicMock()
            mock_bsc.return_value.get_container_client.return_value = container_client
            yield container_client

    @pytest.fixture
    def store(self, azure_cfg, mock_container_client):
        return AzureStorage(azure_cfg)

    def test_write_calls_upload_blob(self, store, mock_container_client):
        store.write("backup.archive", b"binary")
        mock_container_client.upload_blob.assert_called_once_with(
            "backup.archive", b"binary", overwrite=True
        )

    def test_read_calls_download_blob_readall(self, store, mock_container_client):
        mock_container_client.download_blob.return_value.readall.return_value = b"blob data"
        result = store.read("backup.archive")
        assert result == b"blob data"
        mock_container_client.download_blob.assert_called_once_with("backup.archive")

    def test_read_raises_storage_error_when_not_found(self, store, mock_container_client):
        from azure.core.exceptions import ResourceNotFoundError
        mock_container_client.download_blob.side_effect = ResourceNotFoundError("not found")
        with pytest.raises(StorageError, match="not found"):
            store.read("missing.archive")

    def test_list_returns_blobs_matching_prefix(self, store, mock_container_client):
        blob1 = MagicMock(name="raven_mongo_daily.archive", size=512)
        blob1.name = "raven_mongo_daily.archive"
        blob1.size = 512
        blob2 = MagicMock()
        blob2.name = "raven_mongo_weekly.archive"
        blob2.size = 1024
        mock_container_client.list_blobs.return_value = [blob1, blob2]

        results = store.list("raven_mongo_")
        mock_container_client.list_blobs.assert_called_once_with(
            name_starts_with="raven_mongo_"
        )
        assert {"filename": "raven_mongo_daily.archive", "size_bytes": 512} in results
        assert {"filename": "raven_mongo_weekly.archive", "size_bytes": 1024} in results

    def test_delete_calls_delete_blob(self, store, mock_container_client):
        store.delete("old.archive")
        mock_container_client.delete_blob.assert_called_once_with("old.archive")

    def test_delete_noop_on_resource_not_found(self, store, mock_container_client):
        from azure.core.exceptions import ResourceNotFoundError
        mock_container_client.delete_blob.side_effect = ResourceNotFoundError("not found")
        store.delete("nonexistent.archive")  # must not raise

    def test_exists_returns_true_when_blob_exists(self, store, mock_container_client):
        blob_client = MagicMock()
        mock_container_client.get_blob_client.return_value = blob_client
        blob_client.get_blob_properties.return_value = {}
        assert store.exists("backup.archive") is True

    def test_exists_returns_false_when_not_found(self, store, mock_container_client):
        from azure.core.exceptions import ResourceNotFoundError
        blob_client = MagicMock()
        mock_container_client.get_blob_client.return_value = blob_client
        blob_client.get_blob_properties.side_effect = ResourceNotFoundError("not found")
        assert store.exists("missing.archive") is False
