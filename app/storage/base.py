from abc import ABC, abstractmethod
from pathlib import Path


class StorageError(Exception):
    """Raised when a storage backend read/write/delete operation fails."""
    pass


class BaseStorage(ABC):
    """
    Abstract base class for all storage backends (local, S3, Azure).
    All cloud SDK calls must live inside subclasses  never outside.
    """

    @abstractmethod
    def write(self, filename: str, data: bytes) -> None:
        """
        Write data bytes to storage under filename.
        Raises StorageError on failure.
        """
        ...

    @abstractmethod
    def read(self, filename: str) -> bytes:
        """
        Read and return bytes for filename from storage.
        Raises StorageError if file not found or read fails.
        """
        ...

    @abstractmethod
    def list(self, prefix: str) -> list[dict]:
        """
        List files whose names start with prefix.
        Returns a list of dicts: [{"filename": str, "size_bytes": int}, ...]
        """
        ...

    @abstractmethod
    def delete(self, filename: str) -> None:
        """
        Delete filename from storage.
        Must be a no-op (not raise) if the file does not exist.
        """
        ...

    @abstractmethod
    def exists(self, filename: str) -> bool:
        """Return True if filename exists in storage, False otherwise."""
        ...

    @abstractmethod
    def write_stream(self, filename: str, source_path: Path) -> None:
        """
        Stream the contents of source_path to storage under filename.
        Uses backend-native streaming upload (multipart for S3, chunked for Azure).
        Raises StorageError on failure.
        """
        ...

    @abstractmethod
    def read_stream(self, filename: str, dest_path: Path) -> None:
        """
        Stream filename from storage into dest_path on the local filesystem.
        Raises StorageError if the file does not exist or the download fails.
        """
        ...
