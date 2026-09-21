from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from app.config import AzureStorageConfig
from app.logger import log
from app.storage.base import BaseStorage, StorageError


class AzureStorage(BaseStorage):
    """
    Azure Blob Storage backend.

    All blobs are stored directly in the configured container.
    The blob name is the filename as-is (no prefix added).
    """

    def __init__(self, config: AzureStorageConfig) -> None:
        self.container = config.container
        self._client = BlobServiceClient.from_connection_string(
            config.connection_string
        ).get_container_client(config.container)

    # ------------------------------------------------------------------
    # write()
    # ------------------------------------------------------------------

    def write(self, filename: str, data: bytes) -> None:
        try:
            self._client.upload_blob(filename, data, overwrite=True)
        except Exception as e:
            log.error("storage_write_failed", "Azure write failed", error=str(e))
            raise StorageError(f"Azure write failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # read()
    # ------------------------------------------------------------------

    def read(self, filename: str) -> bytes:
        try:
            return self._client.download_blob(filename).readall()
        except ResourceNotFoundError:
            raise StorageError(f"File not found in Azure Blob: '{filename}'")
        except Exception as e:
            log.error("storage_read_failed", "Azure read failed", error=str(e))
            raise StorageError(f"Azure read failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # list()
    # ------------------------------------------------------------------

    def list(self, prefix: str) -> list[dict]:
        try:
            return [
                {"filename": blob.name, "size_bytes": blob.size}
                for blob in self._client.list_blobs(name_starts_with=prefix)
            ]
        except Exception as e:
            log.error("storage_list_failed", "Azure list failed", error=str(e))
            raise StorageError(f"Azure list failed for prefix '{prefix}': {e}")

    # ------------------------------------------------------------------
    # delete()
    # ------------------------------------------------------------------

    def delete(self, filename: str) -> None:
        try:
            self._client.delete_blob(filename)
        except ResourceNotFoundError:
            pass  # no-op  consistent with BaseStorage contract
        except Exception as e:
            log.error("storage_delete_failed", "Azure delete failed", error=str(e))
            raise StorageError(f"Azure delete failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # exists()
    # ------------------------------------------------------------------

    def exists(self, filename: str) -> bool:
        try:
            self._client.get_blob_client(filename).get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            log.error("storage_exists_failed", "Azure exists check failed", error=str(e))
            raise StorageError(f"Azure exists check failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # write_stream() / read_stream()
    # ------------------------------------------------------------------

    def write_stream(self, filename: str, source_path: Path) -> None:
        try:
            with open(source_path, "rb") as f:
                self._client.upload_blob(filename, f, overwrite=True, max_concurrency=4)
        except Exception as e:
            log.error("storage_write_failed", "Azure write_stream failed", error=str(e))
            raise StorageError(f"Azure write_stream failed for '{filename}': {e}")

    def read_stream(self, filename: str, dest_path: Path) -> None:
        try:
            with open(dest_path, "wb") as f:
                self._client.download_blob(filename).readinto(f)
        except ResourceNotFoundError:
            raise StorageError(f"File not found in Azure Blob: '{filename}'")
        except Exception as e:
            log.error("storage_read_failed", "Azure read_stream failed", error=str(e))
            raise StorageError(f"Azure read_stream failed for '{filename}': {e}")
