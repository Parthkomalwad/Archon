from app.config import DatabaseConfig
from app.providers.base import BaseProvider, ProviderError
from app.providers.postgres import PostgresProvider
from app.providers.mongodb import MongoProvider
from app.providers.sqlite import SQLiteProvider
from app.providers.mysql import MySQLProvider

_PROVIDER_MAP = {
    "postgres": PostgresProvider,
    "mongodb": MongoProvider,
    "sqlite": SQLiteProvider,
    "mysql": MySQLProvider,
}


def get_provider(db: DatabaseConfig) -> BaseProvider:
    """Return the appropriate provider instance for the given database config."""
    cls = _PROVIDER_MAP.get(db.type)
    if cls is None:
        raise ProviderError(
            f"Unknown database type '{db.type}'. "
            f"Supported types: {', '.join(_PROVIDER_MAP)}"
        )
    return cls(db)
