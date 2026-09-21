import os
import re
import yaml
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised for any invalid or incomplete config.yaml at parse time."""
    pass


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ScheduleConfig(BaseModel):
    frequency: Optional[str] = None   # daily | weekly | monthly | hourly
    at: Optional[str] = None          # "HH:MM" 24-hour format
    on: Optional[Union[str, int]] = None  # day name (weekly) or 1-28 (monthly)
    timezone: str = "UTC"
    cron: Optional[str] = None        # raw cron escape hatch

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduleConfig":
        if self.cron:
            return self  # raw cron  skip all other validation

        if not self.frequency:
            raise ValueError("schedule must specify either 'frequency' or 'cron'")

        valid_frequencies = {"daily", "weekly", "monthly", "hourly"}
        if self.frequency not in valid_frequencies:
            raise ValueError(
                f"Invalid frequency '{self.frequency}'. Must be one of: {sorted(valid_frequencies)}"
            )

        if self.frequency in {"daily", "weekly", "monthly"} and not self.at:
            raise ValueError(f"frequency '{self.frequency}' requires an 'at' field (e.g. '14:00')")

        if self.frequency == "weekly" and not self.on:
            raise ValueError("frequency 'weekly' requires an 'on' field (e.g. 'sunday')")

        if self.frequency == "monthly" and not self.on:
            raise ValueError("frequency 'monthly' requires an 'on' field (integer 1-28)")

        return self


class RetentionConfig(BaseModel):
    hourly: int = 24
    daily: int = 7
    weekly: int = 4
    monthly: int = 12


class DatabaseConfig(BaseModel):
    name: str
    type: str                          # postgres | mongodb | sqlite | mysql
    host: Optional[str] = None
    port: Optional[int] = None
    db: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    path: Optional[str] = None        # sqlite only
    authdb: str = "admin"             # mongodb only  authentication database
    schedule: ScheduleConfig
    storage: str                      # references a key in top-level storage block
    retention: Optional[RetentionConfig] = None  # per-database override
    restore_strategy: str = "drop_recreate"  # "drop_recreate" | "shadow" (shadow: postgres only)

    @model_validator(mode="after")
    def validate_type_fields(self) -> "DatabaseConfig":
        if self.type == "sqlite":
            if not self.path:
                raise ValueError(f"SQLite database '{self.name}' requires a 'path' field")
        elif self.type in {"postgres", "mongodb", "mysql"}:
            required = ["host", "port", "db", "user", "password"]
            missing = [f for f in required if not getattr(self, f)]
            if missing:
                raise ValueError(
                    f"Database '{self.name}' (type: {self.type}) is missing required fields: {missing}"
                )
        else:
            raise ValueError(
                f"Unknown database type '{self.type}' for '{self.name}'. "
                f"Must be one of: postgres, mongodb, sqlite, mysql"
            )

        valid_strategies = {"drop_recreate", "shadow"}
        if self.restore_strategy not in valid_strategies:
            raise ValueError(
                f"Database '{self.name}': invalid restore_strategy '{self.restore_strategy}'. "
                f"Must be one of: {sorted(valid_strategies)}"
            )
        if self.restore_strategy == "shadow" and self.type != "postgres":
            raise ValueError(
                f"Database '{self.name}': restore_strategy 'shadow' is only supported for "
                f"postgres databases, got type='{self.type}'"
            )

        return self


class LocalStorageConfig(BaseModel):
    path: str


class S3StorageConfig(BaseModel):
    bucket: str
    region: str
    prefix: str = "archon/"
    access_key: str
    secret_key: str


class AzureStorageConfig(BaseModel):
    container: str
    connection_string: str


class EncryptionConfig(BaseModel):
    enabled: bool = True
    key: Optional[str] = None

    @model_validator(mode="after")
    def validate_key(self) -> "EncryptionConfig":
        if self.enabled and not self.key:
            raise ValueError(
                "encryption.key is required when encryption.enabled is true. "
                "Generate one with: openssl rand -base64 32"
            )
        return self


class ApiConfig(BaseModel):
    port: int = 8765
    api_key: str


class PersistenceConfig(BaseModel):
    host: str
    port: int = 5432
    db: str
    user: str
    password: str

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


# ---------------------------------------------------------------------------
# Webhook config
# ---------------------------------------------------------------------------

_VALID_WEBHOOK_EVENTS: frozenset[str] = frozenset({
    "backup_completed",
    "backup_failed",
    "restore_completed",
    "restore_failed",
})


class WebhookRetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_seconds: int = 5


class WebhookConfig(BaseModel):
    url: str
    events: list[str]
    secret: Optional[str] = None
    timeout_seconds: int = 10
    retry: WebhookRetryConfig = Field(default_factory=WebhookRetryConfig)

    @model_validator(mode="after")
    def validate_webhook(self) -> "WebhookConfig":
        if not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise ValueError(
                f"Webhook URL must start with http:// or https://, got '{self.url}'"
            )
        invalid = [e for e in self.events if e not in _VALID_WEBHOOK_EVENTS]
        if invalid:
            raise ValueError(
                f"Invalid webhook event(s): {invalid}. "
                f"Must be one of: {sorted(_VALID_WEBHOOK_EVENTS)}"
            )
        return self


class AppConfig(BaseModel):
    databases: list[DatabaseConfig]
    storage_backends: dict[str, Any]  # name → parsed storage config object
    encryption: EncryptionConfig
    retention: RetentionConfig        # global defaults
    api: ApiConfig
    max_parallel: Optional[int] = None  # global concurrent backup limit; None = unlimited
    webhooks: list[WebhookConfig] = Field(default_factory=list)
    persistence: Optional[PersistenceConfig] = None  # PostgreSQL for job history + logs
    # Phase 5  AI Compliance Bot
    openai_api_key: Optional[str] = None        # from env var OPENAI_API_KEY
    claude_api_key: Optional[str] = None        # from env var CLAUDE_API_KEY
    gemini_api_key: Optional[str] = None        # from env var GEMINI_API_KEY (alternative LLM)
    knowledge_seed_on_startup: bool = False     # seed GDPR Articles at first startup

    @property
    def bot_enabled(self) -> bool:
        """
        Bot requires an embedding source + an LLM source.
        Embedding: OpenAI (preferred) OR Gemini.
        LLM:       Claude OR Gemini.
        Gemini-only works: it handles both embeddings and generation.
        """
        has_embed = bool(self.openai_api_key or self.gemini_api_key)
        has_llm = bool(self.claude_api_key or self.gemini_api_key)
        return has_embed and has_llm

    @property
    def llm_provider(self) -> str:
        """Which LLM is active: 'claude' | 'gemini' | 'none'."""
        if self.claude_api_key:
            return "claude"
        if self.gemini_api_key:
            return "gemini"
        return "none"

    @field_validator("max_parallel")
    @classmethod
    def validate_max_parallel(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError(f"max_parallel must be a positive integer >= 1, got {v}")
        return v


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STORAGE_MODELS: dict[str, type] = {
    "local": LocalStorageConfig,
    "s3": S3StorageConfig,
    "azure": AzureStorageConfig,
}


def _interpolate_env_vars(value: Any) -> Any:
    """
    Recursively walk the parsed YAML structure and replace every
    occurrence of ${VAR_NAME} with the matching environment variable.
    Raises ConfigError if a referenced variable is not set.
    """
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            val = os.environ.get(var_name)
            if val is None:
                raise ConfigError(
                    f"Environment variable '{var_name}' is referenced in config but not set"
                )
            return val

        return pattern.sub(_replace, value)

    elif isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [_interpolate_env_vars(item) for item in value]

    return value


def _parse_storage_backend(name: str, raw: dict) -> Any:
    """Validate and return a typed storage config object for backend `name`."""
    model = _STORAGE_MODELS.get(name)
    if model is None:
        raise ConfigError(
            f"Unknown storage backend '{name}'. "
            f"Supported backends: {list(_STORAGE_MODELS.keys())}"
        )
    try:
        return model(**raw)
    except Exception as e:
        raise ConfigError(f"Invalid config for storage backend '{name}': {e}")


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------

class ConfigLoader:
    """
    Reads, interpolates, validates, and returns the full AppConfig.
    Called once at startup from app/main.py  never elsewhere.
    """

    DEFAULT_PATH = os.environ.get("CONFIG_PATH", "/app/config.yaml")

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path = Path(config_path or self.DEFAULT_PATH)

    def load(self) -> AppConfig:
        if not self.config_path.exists():
            raise ConfigError(
                f"Config file not found at '{self.config_path}'. "
                f"Mount it via Docker volume or set CONFIG_PATH env var."
            )

        with open(self.config_path) as f:
            raw = yaml.safe_load(f)

        if not raw:
            raise ConfigError(f"Config file '{self.config_path}' is empty")

        # Step 1: Interpolate ${VAR} env vars throughout the whole tree
        raw = _interpolate_env_vars(raw)

        # Step 2: Parse and validate
        return self._parse(raw)

    def _parse(self, raw: dict) -> AppConfig:
        # --- Top-level keys ---
        required_keys = ["databases", "storage", "encryption", "retention", "api"]
        missing = [k for k in required_keys if k not in raw]
        if missing:
            raise ConfigError(f"Config is missing required top-level keys: {missing}")

        if not isinstance(raw["databases"], list) or len(raw["databases"]) == 0:
            raise ConfigError("'databases' must be a non-empty list")

        if not isinstance(raw["storage"], dict) or len(raw["storage"]) == 0:
            raise ConfigError("'storage' must be a non-empty mapping of backend names to configs")

        # --- Storage backends ---
        storage_backends: dict[str, Any] = {}
        for backend_name, backend_cfg in raw["storage"].items():
            if not isinstance(backend_cfg, dict):
                raise ConfigError(
                    f"Storage backend '{backend_name}' config must be a mapping, got {type(backend_cfg).__name__}"
                )
            storage_backends[backend_name] = _parse_storage_backend(backend_name, backend_cfg)

        # --- Global retention ---
        try:
            retention = RetentionConfig(**raw.get("retention", {}))
        except Exception as e:
            raise ConfigError(f"Invalid retention config: {e}")

        # --- Databases ---
        databases: list[DatabaseConfig] = []
        for i, db_raw in enumerate(raw["databases"]):
            if not isinstance(db_raw, dict):
                raise ConfigError(f"databases[{i}] must be a mapping, not {type(db_raw).__name__}")

            db_name = db_raw.get("name", f"<database #{i + 1}>")

            # Validate storage reference
            storage_ref = db_raw.get("storage")
            if not storage_ref:
                raise ConfigError(f"Database '{db_name}' is missing the 'storage' field")
            if storage_ref not in storage_backends:
                raise ConfigError(
                    f"Database '{db_name}' references undefined storage backend '{storage_ref}'. "
                    f"Defined backends: {list(storage_backends.keys())}"
                )

            # Per-database retention: merge global → db-specific overrides
            if "retention" in db_raw and isinstance(db_raw["retention"], dict):
                merged_retention = {**retention.model_dump(), **db_raw["retention"]}
                db_raw = {**db_raw, "retention": merged_retention}

            try:
                db = DatabaseConfig(**db_raw)
            except Exception as e:
                raise ConfigError(f"Invalid config for database '{db_name}': {e}")

            databases.append(db)

        # --- Encryption ---
        try:
            encryption = EncryptionConfig(**raw.get("encryption", {}))
        except Exception as e:
            raise ConfigError(f"Invalid encryption config: {e}")

        # --- API ---
        api_raw = raw.get("api", {})
        if not isinstance(api_raw, dict):
            raise ConfigError("'api' must be a mapping")
        if not api_raw.get("api_key"):
            raise ConfigError("api.api_key is required")
        try:
            api = ApiConfig(**api_raw)
        except Exception as e:
            raise ConfigError(f"Invalid api config: {e}")

        # --- Webhooks ---
        webhooks: list[WebhookConfig] = []
        webhooks_raw = raw.get("webhooks", [])
        if webhooks_raw:
            if not isinstance(webhooks_raw, list):
                raise ConfigError("'webhooks' must be a list")
            for i, wh_raw in enumerate(webhooks_raw):
                if not isinstance(wh_raw, dict):
                    raise ConfigError(
                        f"webhooks[{i}] must be a mapping, not {type(wh_raw).__name__}"
                    )
                try:
                    webhooks.append(WebhookConfig(**wh_raw))
                except Exception as e:
                    raise ConfigError(f"Invalid config for webhook[{i}]: {e}")

        # --- Persistence (optional) ---
        persistence: Optional[PersistenceConfig] = None
        persistence_raw = raw.get("persistence")
        if persistence_raw:
            if not isinstance(persistence_raw, dict):
                raise ConfigError("'persistence' must be a mapping")
            try:
                persistence = PersistenceConfig(**persistence_raw)
            except Exception as e:
                raise ConfigError(f"Invalid persistence config: {e}")

        return AppConfig(
            databases=databases,
            storage_backends=storage_backends,
            encryption=encryption,
            retention=retention,
            api=api,
            max_parallel=raw.get("max_parallel"),
            webhooks=webhooks,
            persistence=persistence,
            openai_api_key=raw.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"),
            claude_api_key=raw.get("claude_api_key") or os.environ.get("CLAUDE_API_KEY"),
            gemini_api_key=raw.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY"),
            knowledge_seed_on_startup=bool(raw.get("knowledge_seed_on_startup", False)),
        )
