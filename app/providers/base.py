from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Raised when a DB provider subprocess fails (pg_dump, mongodump, etc.)."""
    pass


class BaseProvider(ABC):
    """
    Abstract base class for all database providers.
    Each provider implements backup() and restore() using native DB tools.
    """

    @abstractmethod
    def backup(self, output_path: str) -> None:
        """
        Run a database backup and write the result to output_path.
        Raises ProviderError on failure.
        """
        ...

    @abstractmethod
    def restore(self, backup_path: str, confirm: bool) -> None:
        """
        Restore the database from backup_path using drop-and-recreate semantics.
        Must raise ValueError immediately if confirm is not True.
        Raises ProviderError on subprocess failure.
        """
        ...
