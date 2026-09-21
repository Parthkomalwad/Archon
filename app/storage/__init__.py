from app.config import LocalStorageConfig, S3StorageConfig, AzureStorageConfig
from app.storage.base import BaseStorage, StorageError
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage
from app.storage.azure import AzureStorage


def get_storage(storage_config) -> BaseStorage:
    """
    Return the appropriate storage backend instance for the given config object.

    Accepts LocalStorageConfig, S3StorageConfig, or AzureStorageConfig.
    Raises StorageError for unrecognised config types.
    """
    if isinstance(storage_config, LocalStorageConfig):
        return LocalStorage(storage_config)
    if isinstance(storage_config, S3StorageConfig):
        return S3Storage(storage_config)
    if isinstance(storage_config, AzureStorageConfig):
        return AzureStorage(storage_config)
    raise StorageError(
        f"Unknown storage config type '{type(storage_config).__name__}'. "
        "Expected LocalStorageConfig, S3StorageConfig, or AzureStorageConfig."
    )
