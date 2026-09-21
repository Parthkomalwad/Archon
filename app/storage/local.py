import shutil
from pathlib import Path

from app.config import LocalStorageConfig
from app.logger import log
from app.storage.base import BaseStorage, StorageError


class LocalStorage(BaseStorage):
    """
    Local filesystem storage backend.

    All files are stored flat inside the configured directory path.
    The directory is created automatically on first write if it does not exist.
    """

    def __init__(self, config: LocalStorageConfig) -> None:
        self.root = Path(config.path)

    def _full_path(self, filename: str) -> Path:
        return self.root / filename

    # ------------------------------------------------------------------
    # write()
    # ------------------------------------------------------------------

    def write(self, filename: str, data: bytes) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._full_path(filename).write_bytes(data)
        except Exception as e:
            log.error("storage_write_failed", "Local write failed", error=str(e))
            raise StorageError(f"Local write failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # read()
    # ------------------------------------------------------------------

    def read(self, filename: str) -> bytes:
        path = self._full_path(filename)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise StorageError(f"File not found in local storage: '{filename}'")
        except Exception as e:
            log.error("storage_read_failed", "Local read failed", error=str(e))
            raise StorageError(f"Local read failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # list()
    # ------------------------------------------------------------------

    def list(self, prefix: str) -> list[dict]:
        try:
            if not self.root.exists():
                return []
            return [
                {"filename": f.name, "size_bytes": f.stat().st_size}
                for f in sorted(self.root.iterdir())
                if f.is_file() and f.name.startswith(prefix)
            ]
        except Exception as e:
            log.error("storage_list_failed", "Local list failed", error=str(e))
            raise StorageError(f"Local list failed for prefix '{prefix}': {e}")

    # ------------------------------------------------------------------
    # delete()
    # ------------------------------------------------------------------

    def delete(self, filename: str) -> None:
        path = self._full_path(filename)
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            log.error("storage_delete_failed", "Local delete failed", error=str(e))
            raise StorageError(f"Local delete failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # exists()
    # ------------------------------------------------------------------

    def exists(self, filename: str) -> bool:
        return self._full_path(filename).exists()

    # ------------------------------------------------------------------
    # write_stream() / read_stream()
    # ------------------------------------------------------------------

    def write_stream(self, filename: str, source_path: Path) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, self._full_path(filename))
        except Exception as e:
            log.error("storage_write_failed", "Local write_stream failed", error=str(e))
            raise StorageError(f"Local write_stream failed for '{filename}': {e}")

    def read_stream(self, filename: str, dest_path: Path) -> None:
        src = self._full_path(filename)
        try:
            shutil.copy2(src, dest_path)
        except FileNotFoundError:
            raise StorageError(f"File not found in local storage: '{filename}'")
        except Exception as e:
            log.error("storage_read_failed", "Local read_stream failed", error=str(e))
            raise StorageError(f"Local read_stream failed for '{filename}': {e}")
