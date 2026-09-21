# Archon – Plug-and-Play Database Backup & Restore Microservice
**Product Requirements Document | v2.0**

| Field | Detail |
|---|---|
| Author | AnonymousCoderDev |
| Version | 2.0 |
| Status | Finalized |
| Target Reader | Claude Code / Development Team |
| Previous Version | v1.3 |
| Changelog | Async backup API, job tracking, per-database retention, hourly retention, MongoDB authdb, restore target override, SHA-256 integrity, config reload endpoint, structured logging, ubuntu:22.04 base, extended API schemas |

---

## 1. Overview

Archon is a sidecar microservice written in Python that provides automated and on-demand database backup and restore capabilities for any backend project. It runs as a separate Docker container alongside the primary application container, requiring zero code changes to the host backend.

The motivation is simple: every project needs database backups, yet this layer is consistently skipped or re-implemented from scratch per project. Archon is built once and dropped into any project via a single docker-compose block.

---

## 2. Prerequisites & Dependencies

Archon has zero external dependencies beyond what you already have in any Docker-based project.

### 2.1 What You Need

| Requirement | Where It Lives | Notes |
|---|---|---|
| Docker + Docker Compose | Your machine / server | You already have this if you run any containerised backend |
| `archon.config.yaml` | Root of your project | The config file defined in Section 5. Created once per project |
| `.env` file | Root of your project | Your existing .env file. Just add a few Archon-specific variables |
| Backup destination | Local folder, S3 bucket, or Azure container | Local requires nothing extra. S3/Azure require credentials you already have |
| Archon Docker image | Built once from source | One `docker build` command. Then referenced in docker-compose.yml |

No external database for Archon itself, no secret manager, no Redis, no third-party service.

### 2.2 The .env File

Archon reads all secrets from environment variables. Add the following to your existing `.env` file:

```bash
# --- Archon variables (add to your existing .env) ---

# API key to authenticate REST API calls to Archon
# Generate with: openssl rand -hex 32
ARCHON_API_KEY=your-random-secret-string-here

# 32-byte AES-256 encryption key for backup files
# Generate with: openssl rand -base64 32
ENCRYPTION_KEY=your-base64-encoded-32-byte-key

# Your existing database credentials (already in your .env)
DB_USER=myuser
DB_PASSWORD=mypassword

# Only needed if using S3 storage
AWS_ACCESS_KEY=your-aws-access-key
AWS_SECRET_KEY=your-aws-secret-key

# Only needed if using Azure storage
AZURE_STORAGE_CONN_STR=your-azure-connection-string
```

### 2.3 How the API Key Works

`ARCHON_API_KEY` is a plain string you generate yourself. Archon reads it from the environment on startup and holds it in memory. No database lookup or token store is involved.

Every REST API call must include it as a request header:
```
X-API-Key: your-random-secret-string-here
```

Archon compares the incoming header value against the in-memory value. Returns `401` if they don't match. To rotate: update `.env` and restart the container.

### 2.4 How the Encryption Key Works

`ENCRYPTION_KEY` is a base64-encoded 32-byte random string. Archon reads it on startup and uses it for AES-256-CBC encryption of every backup file before it is written to storage. The key never leaves the container and is never written to disk by Archon.

Generate a valid key:
```bash
openssl rand -base64 32
```

> **Important:** If you lose this key, existing encrypted backups cannot be decrypted. Keep it in your `.env` file and back up your `.env` separately from your backups.

### 2.5 Project File Structure

After setup, your project root looks like this. Nothing new is introduced beyond three files:

```
your-project/
├── docker-compose.yml        # add the archon sidecar block here
├── archon.config.yaml       # archon config (you create this once)
├── .env                      # your existing env file, add archon vars
├── backups/                  # auto-created by archon for local storage
└── ... (rest of your project)
```

The `backups/` folder is only created if you use local storage. For S3 or Azure, no local folder is needed.

---

## 3. Goals & Non-Goals

### 3.1 Goals
- Single reusable sidecar service that attaches to any backend project regardless of language or framework
- Config-file-driven: all behaviour defined in a YAML file, no code changes required
- Support PostgreSQL, MongoDB, and SQLite in v1
- Store backups to Local Filesystem, AWS S3, and Azure Blob Storage
- Support both scheduled (cron) and manual (REST API) backup triggers
- AES-256 encryption on all backup files at rest
- SHA-256 checksum sidecar stored alongside every backup; verified before every restore
- Daily, weekly, monthly, and hourly backup retention with configurable counts
- Per-database retention override with global fallback
- Restore from any backup with a single API call and explicit confirmation flag
- Restore target override: optionally redirect a restore to a different database entry in config
- Support multiple databases in a single config file, each with independent schedules and storage targets
- Human-readable schedule config (frequency + time + timezone) converted to cron internally
- Async backup API: POST /backup returns a job ID immediately; caller polls GET /jobs/{job_id}
- Per-database backup queue: concurrent requests are serialized, not dropped
- Config reload without container restart via POST /reload
- Structured JSON logging to stdout

### 3.2 Non-Goals (v1)
- No notification system (Slack, email) in v1  can be added in v2
- No web-based UI dashboard in v1
- No support for MySQL/MariaDB in v1
- No multi-tenant or per-user-level backup granularity
- No streaming replication or point-in-time recovery
- No persistent job history (jobs are in-memory, purged after 24h)

---

## 4. Architecture

### 4.1 Deployment Model

Archon runs as a Docker sidecar container. It shares the host network with the backend container to access the database directly using credentials defined in `config.yaml`.

Add this block to any project's `docker-compose.yml`:

```yaml
archon:
  image: archon:latest
  volumes:
    - ./archon.config.yaml:/app/config.yaml
    - ./backups:/app/backups
  ports:
    - "8765:8765"
  env_file: .env
```

That is the entire integration. No code changes to the backend.

### 4.2 High-Level Component Flow

| Component | Responsibility |
|---|---|
| `ConfigLoader` | Parses and validates `config.yaml` on startup. Iterates the `databases` list and constructs one `BackupJob` per entry. Fails fast on bad config. |
| `BackupJob` | Represents one database entry from config. Holds its own provider instance, storage backend reference, and schedule. Multiple BackupJobs run independently. |
| `ProviderFactory` | Instantiates the correct DB provider class per BackupJob (Postgres, Mongo, SQLite). |
| `DB Providers` | Each provider implements `backup()` and `restore()` using native DB tools (`pg_dump`, `mongodump`, `sqlite3`). |
| `StorageBackend` | Abstraction layer for writing/reading/listing/deleting/checking backup files. Defined once in config, shared across BackupJobs that reference the same backend. |
| `EncryptionService` | AES-256-CBC encrypt/decrypt on backup files before they touch any storage backend. Appends `.enc` to filename when enabled. |
| `ScheduleParser` | Converts human-readable schedule config (frequency, at, on, timezone) into cron expressions. Also accepts raw cron strings for advanced users. |
| `Scheduler` | APScheduler-based cron runner. Registers one timezone-aware cron job per BackupJob entry. |
| `RetentionManager` | After each backup, enforces hourly/daily/weekly/monthly rotation policy scoped to that database's backup files. Respects per-database overrides. |
| `JobStore` | In-memory store tracking async backup jobs. Keyed by UUID job ID. Purges jobs older than 24h automatically. |
| `JobQueue` | Per-database asyncio queue. Ensures concurrent backup requests for the same database are serialized. Different databases run in parallel. |
| `REST API` | FastAPI server exposing all endpoints. All endpoints require `X-API-Key` header. |

### 4.3 Provider Pattern

All database providers implement a common abstract base class:

```python
class BaseProvider(ABC):
    @abstractmethod
    def backup(self, output_path: str) -> str: ...

    @abstractmethod
    def restore(self, backup_path: str, confirm: bool) -> bool: ...
```

Adding a new database type in the future requires only creating a new provider class. Nothing else in the system changes.

---

## 5. Configuration File (`archon.config.yaml`)

All service behaviour is driven by a single YAML config file mounted into the container at startup. Archon supports multiple databases in one config file. Each database entry is independent and can target a different storage backend and run on its own schedule.

Schedules are written in plain English (frequency, time, timezone) and converted to cron internally by the `ScheduleParser`. No cron knowledge required. Raw cron is also supported as an escape hatch.

Storage backends are defined once at the top level and referenced by name inside each database entry.

### Full Annotated Schema

```yaml
databases:
  - name: primary_postgres          # unique identifier for this backup job
    type: postgres                  # postgres | mongodb | sqlite
    host: postgres
    port: 5432
    db: mydb
    user: ${DB_USER}               # env var interpolation supported
    password: ${DB_PASSWORD}
    schedule:
      frequency: daily              # daily | weekly | monthly | hourly
      at: "14:00"                   # 24hr time format
      timezone: "Asia/Kolkata"      # any valid IANA timezone
    storage: s3                     # references storage.s3 below
    retention:                      # OPTIONAL  overrides global retention for this database
      daily: 14
      weekly: 8

  - name: analytics_mongo
    type: mongodb
    host: mongo
    port: 27017
    db: analytics
    user: ${MONGO_USER}
    password: ${MONGO_PASSWORD}
    authdb: admin                   # OPTIONAL  authentication database, defaults to 'admin'
    schedule:
      frequency: weekly
      on: sunday                    # day name for weekly (monday-sunday)
      at: "03:00"
      timezone: "UTC"
    storage: local

  - name: cache_sqlite
    type: sqlite
    path: /data/cache.db            # for SQLite, only path is needed
    schedule:
      frequency: monthly
      on: 1                         # day of month (1-28)
      at: "00:00"
      timezone: "America/New_York"
    storage: azure

  - name: metrics_hourly
    type: postgres
    host: postgres
    port: 5432
    db: metrics
    user: ${DB_USER}
    password: ${DB_PASSWORD}
    schedule:
      frequency: hourly
      timezone: "UTC"
    storage: local
    retention:
      hourly: 48                    # keep last 48 hourly backups for this database

  # Advanced: raw cron escape hatch for power users
  # - name: high_frequency_job
  #   schedule:
  #     cron: "*/30 * * * *"       # raw cron still supported
  #     timezone: "Asia/Kolkata"

# Storage backends defined once, referenced by name above
storage:
  s3:
    bucket: my-backups
    region: ap-south-1
    prefix: archon/
    access_key: ${AWS_ACCESS_KEY}
    secret_key: ${AWS_SECRET_KEY}
  local:
    path: /app/backups
  azure:
    container: dbbackups
    connection_string: ${AZURE_STORAGE_CONN_STR}

encryption:
  enabled: true
  key: ${ENCRYPTION_KEY}           # 32-byte base64 encoded key

retention:                          # global defaults  apply to all databases unless overridden
  hourly: 24                        # keep last 24 hourly backups
  daily: 7                          # keep last 7 daily backups
  weekly: 4                         # keep last 4 weekly backups
  monthly: 12                       # keep last 12 monthly backups

api:
  port: 8765
  api_key: ${ARCHON_API_KEY}      # required for all endpoints
```

### Key Design Decisions

- **Multi-database support:** The `databases` key is a list. Each entry becomes an independent `BackupJob` with its own provider, storage backend, and schedule.
- **Storage defined once:** Storage credentials live under the top-level `storage` key. Each database references a backend by name (e.g. `storage: s3`). No repeated credentials per database.
- **Human-readable schedules:** Schedules use plain language  `frequency`, `at`, `on`, `timezone`. The `ScheduleParser` converts to cron internally. Raw cron strings accepted as escape hatch.
- **Timezone support:** Every schedule entry carries its own IANA timezone. APScheduler handles timezone-aware execution natively.
- **Independent schedules:** Each database has its own schedule. Jobs never block each other.
- **Mixed storage per database:** Different databases can target different backends in the same config.
- **Env var interpolation:** Any value can use `${VAR_NAME}` syntax. Secrets never live in the config file itself.
- **Per-database retention override:** Each database entry may include an optional `retention:` block. If present, its values override the global retention for that database only. Missing keys fall back to global.
- **MongoDB authdb:** MongoDB entries accept an optional `authdb` field (default: `admin`) passed to `--authenticationDatabase` in mongodump/mongorestore.

### 5.1 ScheduleParser – Human-Readable Schedule Conversion

The `ScheduleParser` converts the human-readable schedule block into a cron expression consumed by APScheduler.

| Input (config.yaml) | Converted Cron | Description |
|---|---|---|
| `frequency: daily, at: 14:00, timezone: Asia/Kolkata` | `0 14 * * *` | Every day at 2pm IST |
| `frequency: weekly, on: sunday, at: 03:00, timezone: UTC` | `0 3 * * 0` | Every Sunday at 3am UTC |
| `frequency: monthly, on: 1, at: 00:00, timezone: America/New_York` | `0 0 1 * *` | 1st of every month at midnight EST |
| `frequency: hourly, timezone: Asia/Kolkata` | `0 * * * *` | Every hour |
| `cron: */30 * * * *, timezone: UTC` | `*/30 * * * *` | Raw cron passthrough |

**Implementation notes:**
- Timezone is applied at the APScheduler level, not by offsetting the cron expression. DST transitions are handled automatically.
- The `on` field accepts day names (`monday` through `sunday`) for weekly, or an integer `1–28` for monthly. Days 29–31 are excluded to ensure the job runs every month without skipping short months.

---

## 6. REST API Specification

All endpoints require the header: `X-API-Key: <ARCHON_API_KEY>`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/backup` | Trigger an immediate async backup. Returns 202 with job ID(s). Optional body: `{ "database": "primary_postgres" }`. If omitted, triggers all databases. |
| `GET` | `/jobs/{job_id}` | Poll the status of an async backup job by job ID. |
| `POST` | `/restore` | Restore from a specific backup file. Requires `confirm: true` in body. Optional `target_database` override. |
| `GET` | `/backups` | List all backups with extended metadata. Optional query param: `?database=primary_postgres`. |
| `GET` | `/status` | Returns health of all BackupJobs: last run time, next scheduled run, last status, currently running flag per database. |
| `DELETE` | `/backups/{filename}` | Delete a specific backup file from its storage backend (including cloud). Also deletes the `.sha256` sidecar. |
| `POST` | `/reload` | Re-read and validate `config.yaml`, cancel all existing scheduled jobs, re-register with new config. Protected by API key. |

### POST /backup – Request Body
```json
{
  "database": "primary_postgres"   // optional  omit to trigger all databases
}
```

### POST /backup – Response (202 Accepted)
```json
{
  "jobs": [
    { "job_id": "a1b2c3d4-...", "database": "primary_postgres", "status": "queued" }
  ]
}
```

### GET /jobs/{job_id} – Response
```json
{
  "job_id": "a1b2c3d4-...",
  "database": "primary_postgres",
  "status": "completed",           // queued | running | completed | failed
  "queued_at": "2025-06-15T14:00:00Z",
  "started_at": "2025-06-15T14:00:01Z",
  "completed_at": "2025-06-15T14:00:09Z",
  "backup_filename": "archon_primary_postgres_2025-06-15T14-00-01_daily.sql.enc",
  "error_message": null
}
```
Returns `404` if job_id is not found or has been purged (jobs purged after 24h).

### POST /restore – Request Body
```json
{
  "filename": "archon_primary_postgres_2025-06-15T02-00-00_daily.sql.enc",
  "confirm": true,
  "target_database": "staging_postgres"   // optional  defaults to database inferred from filename
}
```
> `confirm: true` must be explicitly provided. Returns `400` if missing.
> `target_database` must match a valid `name` in the `databases` config list.

### GET /backups – Response (per entry, extended metadata)
```json
{
  "backups": [
    {
      "filename": "archon_primary_postgres_2025-06-15T14-00-01_daily.sql.enc",
      "database": "primary_postgres",
      "timestamp": "2025-06-15T14:00:01Z",
      "size_bytes": 204800,
      "rotation_type": "daily",
      "storage_backend": "s3",
      "encrypted": true,
      "file_exists": true
    }
  ]
}
```

### POST /reload – Response
```json
{
  "status": "reloaded",
  "databases_registered": 3,
  "errors": []
}
```
Returns `400` with error details if the new config is invalid. Existing jobs continue running until the new config is validated.

---

## 7. Backup File Naming Convention

All backup files follow a deterministic naming pattern. The database name is embedded in the filename so backups from multiple databases never collide, even when stored in the same backend.

```
archon_{db_name}_{timestamp}_{rotation_type}.{ext}[.enc]
```

- `.enc` suffix is appended **only when** `encryption.enabled: true`. When encryption is disabled, the file has no `.enc` suffix.
- A `.sha256` sidecar file is **always** written alongside every backup regardless of encryption setting.

Examples (encryption enabled):
```
archon_primary_postgres_2025-06-15T02-00-00_daily.sql.enc
archon_primary_postgres_2025-06-15T02-00-00_daily.sql.enc.sha256

archon_analytics_mongo_2025-06-15T03-00-00_daily.archive.enc
archon_analytics_mongo_2025-06-15T03-00-00_daily.archive.enc.sha256

archon_cache_sqlite_2025-06-01T04-00-00_monthly.db.enc
archon_cache_sqlite_2025-06-01T04-00-00_monthly.db.enc.sha256
```

Examples (encryption disabled):
```
archon_primary_postgres_2025-06-15T02-00-00_daily.sql
archon_primary_postgres_2025-06-15T02-00-00_daily.sql.sha256
```

- `db_name` maps to the `name` field in the `databases` list in `config.yaml`
- `rotation_type` (hourly/daily/weekly/monthly) is assigned by the `RetentionManager` based on schedule frequency and calendar date
- The `.sha256` sidecar stores the hex-encoded SHA-256 hash of the backup file (after encryption, if enabled)

---

## 8. Encryption Specification

| Property | Value |
|---|---|
| Algorithm | AES-256-CBC |
| Key management | 32-byte key passed via environment variable, base64 encoded |
| IV | Randomly generated per backup, prepended to the encrypted file |
| Scope | Encryption happens before the file is written to any storage backend |
| Restore | Decryption happens after file is read from storage, before handing to DB provider |
| Filename | `.enc` suffix appended only when `encryption.enabled: true` |

The `EncryptionService` is a wrapper that can be disabled via config (`encryption.enabled: false`) for local dev environments. When disabled, data passes through unchanged and filenames carry no `.enc` suffix.

---

## 9. Retention Policy

After each backup completes, the `RetentionManager` enforces the rotation policy scoped to that specific database's backup files. Per-database `retention:` config overrides global values; missing keys fall back to global.

| Rotation Type | When Applied | Default Keep Count |
|---|---|---|
| `hourly` | Every backup run for hourly-scheduled databases | 24 |
| `daily` | Every backup run | 7 |
| `weekly` | Runs on Sunday | 4 |
| `monthly` | Runs on the 1st of the month | 12 |

**Overlap rule:** A backup can qualify as multiple types (e.g. Sunday on the 1st is both weekly and monthly). In this case it is retained under the longer retention window.

**Sidecar cleanup:** When the `RetentionManager` deletes an expired backup file, it also deletes the corresponding `.sha256` sidecar file from the same storage backend.

**Per-database override example:**
```yaml
# Global: daily: 7, weekly: 4, monthly: 12
- name: primary_postgres
  retention:
    daily: 14     # overrides global daily for this database only
    weekly: 8     # overrides global weekly for this database only
    # monthly not specified  falls back to global: 12
```

---

## 10. Backup Integrity

Every backup produces a SHA-256 checksum sidecar file stored alongside the backup in the same storage backend.

**On backup:**
1. Run DB provider `backup()` → raw file
2. Encrypt file (if enabled) → encrypted file
3. Compute SHA-256 hash of the final file bytes
4. Write encrypted file to storage backend
5. Write `<filename>.sha256` (hex string) to storage backend

**On restore:**
1. Read backup file from storage
2. Read `.sha256` sidecar from storage
3. Compute SHA-256 of the downloaded file bytes
4. Compare: if mismatch → abort restore immediately with error `"Integrity check failed: checksum mismatch"`
5. Decrypt file (if encryption enabled)
6. Hand to DB provider `restore()`

This detects file corruption and storage tampering before any data is touched.

---

## 11. Restore Behavior

When `POST /restore` is called:

1. `confirm: true` is required  returns `400` if missing
2. SHA-256 integrity check runs first  aborts if failed
3. Decryption runs next (if encryption enabled)
4. Target database is determined:
   - Default: inferred from the `db_name` embedded in the filename
   - Override: use `target_database` from request body (must exist in config)
5. Provider `restore()` is called with **drop-and-recreate** semantics:
   - **PostgreSQL:** `DROP DATABASE` → `CREATE DATABASE` → `pg_restore` / `psql`
   - **MongoDB:** `mongorestore --drop` flag (drops collections before restoring)
   - **SQLite:** Delete existing `.db` file → copy restored file into place

> **Warning:** Restore is destructive. All existing data in the target database is lost. This is why `confirm: true` is required.

If restore fails midway, the database may be in a broken state. Archon logs the failure with full error details. No automatic rollback is performed in v1.

---

## 12. Startup Behavior

On container startup, Archon performs the following in order:

1. Read and validate `config.yaml`  exit with clear error if missing or invalid
2. Interpolate all `${VAR_NAME}` environment variables  exit with clear error if any are missing
3. Attempt a connection check to **every** configured database  exit with clear error if any are unreachable
4. Initialise `JobStore`, `JobQueue` (one queue per database), and `RetentionManager`
5. Register all `BackupJob` cron schedules with APScheduler
6. Start FastAPI / uvicorn server

All startup events are logged as structured JSON to stdout. If startup fails at any step, the container exits with a non-zero exit code and a human-readable error message.

> **Note:** Use `depends_on` with healthchecks in your `docker-compose.yml` to ensure database containers are ready before Archon starts.

---

## 13. Concurrent Backup Handling

Each database has its own asyncio queue (`JobQueue`). When a backup request arrives for a database:

- If no backup is running for that database: start immediately, set status to `running`
- If a backup is already running for that database: enqueue the request, set status to `queued`; it runs automatically when the current backup finishes
- Different databases always run concurrently  queues are per-database and never block each other

The `GET /jobs/{job_id}` endpoint allows callers to observe the transition from `queued` → `running` → `completed` or `failed`.

---

## 14. Logging

All log output is written to **stdout** as newline-delimited JSON (one JSON object per line). This integrates natively with Docker log drivers, Datadog, CloudWatch, and any other log aggregation system.

### Log Fields

| Field | Type | Description |
|---|---|---|
| `timestamp` | ISO 8601 string | UTC time of the event |
| `level` | string | `INFO`, `WARNING`, `ERROR` |
| `database` | string or null | Database name if event is DB-scoped |
| `event` | string | Machine-readable event identifier |
| `message` | string | Human-readable description |
| `error` | string or null | Error message if level is ERROR |

### Example Log Lines

```json
{"timestamp":"2025-06-15T14:00:00Z","level":"INFO","database":null,"event":"startup_ok","message":"Archon started. 3 backup jobs registered.","error":null}
{"timestamp":"2025-06-15T14:00:01Z","level":"INFO","database":"primary_postgres","event":"backup_started","message":"Backup job triggered (manual API)","error":null}
{"timestamp":"2025-06-15T14:00:09Z","level":"INFO","database":"primary_postgres","event":"backup_completed","message":"Backup written to S3","error":null}
{"timestamp":"2025-06-15T14:00:09Z","level":"INFO","database":"primary_postgres","event":"retention_run","message":"Deleted 1 expired daily backup","error":null}
{"timestamp":"2025-06-15T14:01:00Z","level":"ERROR","database":"primary_postgres","event":"backup_failed","message":"pg_dump subprocess exited with code 1","error":"FATAL: password authentication failed for user \"myuser\""}
```

---

## 15. Project Structure

```
archon/
├── Dockerfile
├── config.yaml.example
├── requirements.txt
├── README.md
├── app/
│   ├── main.py              # FastAPI entrypoint, startup checks
│   ├── config.py            # ConfigLoader – parses and validates config.yaml
│   ├── logger.py            # Structured JSON logger (shared across all modules)
│   ├── jobs.py              # In-memory JobStore + per-database JobQueue
│   ├── scheduler.py         # APScheduler setup and BackupJob registration
│   ├── schedule_parser.py   # Converts human-readable schedule to cron
│   ├── retention.py         # RetentionManager (hourly/daily/weekly/monthly + per-db)
│   ├── encryption.py        # AES-256 EncryptionService + SHA-256 integrity
│   ├── providers/
│   │   ├── base.py          # Abstract BaseProvider
│   │   ├── postgres.py      # pg_dump / pg_restore (drop-and-recreate)
│   │   ├── mongodb.py       # mongodump / mongorestore --drop (authdb support)
│   │   └── sqlite.py        # sqlite3.connect().backup() hot-copy
│   ├── storage/
│   │   ├── base.py          # Abstract StorageBackend (write/read/list/delete/exists)
│   │   ├── local.py         # Local filesystem
│   │   ├── s3.py            # boto3 S3
│   │   └── azure.py         # azure-storage-blob
│   └── api/
│       ├── routes.py        # All API route definitions
│       └── middleware.py    # API key auth middleware
└── tests/
    ├── test_providers.py
    ├── test_retention.py
    ├── test_encryption.py
    └── test_schedule_parser.py
```

---

## 16. Python Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | REST API framework |
| `uvicorn` | ASGI server for FastAPI |
| `apscheduler` | Cron-based job scheduler with timezone support |
| `pycryptodome` | AES-256 encryption/decryption |
| `boto3` | AWS S3 storage backend |
| `azure-storage-blob` | Azure Blob Storage backend |
| `pyyaml` | Config file parsing |
| `pydantic` | Config validation and API schemas |
| `python-dotenv` | Environment variable interpolation in config |
| `pytz` | IANA timezone validation and conversion |

`uuid` is used for job ID generation  part of Python standard library, no install needed.

---

## 17. Dockerfile Spec

- **Base image:** `ubuntu:22.04`
- **Python:** Install Python 3.11 via apt (`python3.11`, `python3-pip`)
- **Native tools required** (installed via apt):
  - `postgresql-client` (for `pg_dump` and `pg_restore`)
  - `mongodb-database-tools` (for `mongodump` and `mongorestore`)  requires adding MongoDB's official apt repository
  - `sqlite3`

The `config.yaml` is never baked into the image. It is always mounted at runtime via a Docker volume. This keeps the image generic and reusable across all projects.

> **Note on MongoDB tools:** The `mongodb-database-tools` package requires adding MongoDB's official apt source (`repo.mongodb.org`) to the Dockerfile. This is non-trivial for slim images and is why `ubuntu:22.04` is used as the base instead of `python:3.11-slim`.

---

## 18. Implementation Phases

| Phase | Scope | Deliverable |
|---|---|---|
| Phase 1 | Core scaffolding | Project structure, `ConfigLoader`, `BaseProvider`, `BaseStorage`, `JobStore`, `JobQueue`, structured JSON logger, startup connection checks, FastAPI skeleton with `/status` endpoint |
| Phase 2 | DB Providers | PostgreSQL (`pg_dump`/`pg_restore` drop-and-recreate), MongoDB (`mongodump`/`mongorestore --drop`, authdb support), SQLite (`.backup()` hot-copy)  all unit tested |
| Phase 3 | Storage Backends | Local, S3, Azure backends with `write`/`read`/`list`/`delete`/`exists`  all tested |
| Phase 4 | Encryption + Integrity | AES-256 `EncryptionService`, SHA-256 checksum sidecar generation and verification on restore  all tested |
| Phase 5 | ScheduleParser | Human-readable schedule parsing, cron conversion, timezone support, raw cron passthrough  all tested |
| Phase 6 | Scheduler + Retention | APScheduler cron registration, per-database `JobQueue`, `RetentionManager` with hourly/daily/weekly/monthly and per-database override |
| Phase 7 | REST API complete | All endpoints wired: `POST /backup` (async + job ID), `GET /jobs/{job_id}`, `POST /restore` (drop-and-recreate + integrity check + target override), `GET /backups` (extended), `GET /status`, `DELETE /backups/{filename}` (cloud delete + sidecar), `POST /reload` |
| Phase 8 | Docker + Docs | Dockerfile (ubuntu:22.04 + MongoDB apt repo), docker-compose example, README with quickstart, `config.yaml.example` |

---

## 19. Acceptance Criteria

| # | Criteria |
|---|---|
| AC-1 | A PostgreSQL database can be fully backed up and restored via the REST API; SHA-256 integrity check passes on restore |
| AC-2 | A MongoDB database can be fully backed up and restored with drop-and-recreate confirmed |
| AC-3 | A SQLite database can be fully backed up (hot-copy) and restored |
| AC-4 | Backups are encrypted with AES-256 and cannot be read without the encryption key |
| AC-5 | Backups are written to Local, S3, and Azure storage backends correctly |
| AC-6 | Scheduled backups run at the configured time without manual intervention |
| AC-7 | Retention policy correctly deletes old backups (all 4 types) after the configured count is exceeded |
| AC-8 | Restore endpoint returns `400` if `confirm: true` is not explicitly provided |
| AC-9 | All API endpoints return `401` if the correct `X-API-Key` header is not provided |
| AC-10 | The service can be added to any `docker-compose.yml` with only the block defined in Section 4.1 |
| AC-11 | A config with three databases results in three independent backup jobs running on their own schedules without interfering |
| AC-12 | `POST /backup` with `{ "database": "name" }` triggers only that database; without a body it triggers all databases |
| AC-13 | Backup files from different databases in the same storage backend are namespaced by database name and never overwrite each other |
| AC-14 | `ScheduleParser` correctly converts daily/weekly/monthly/hourly config into the expected cron expression for all supported combinations |
| AC-15 | A schedule entry with `cron:` directly bypasses `ScheduleParser` and is passed through to APScheduler as-is |
| AC-16 | Timezone is correctly applied per-database. Two databases with the same `at:` time but different timezones fire at different UTC times |
| AC-17 | `POST /backup` returns 202 with a job ID; `GET /jobs/{job_id}` transitions through `queued → running → completed` correctly |
| AC-18 | `POST /restore` with `target_database` override restores to the correct database entry from config |
| AC-19 | A corrupted backup file (checksum mismatch) causes restore to abort with an error before touching the database |
| AC-20 | `DELETE /backups/{filename}` removes the file from its cloud storage backend (S3/Azure) and deletes the `.sha256` sidecar |
| AC-21 | Per-database retention override takes precedence over global for that database; global applies to databases without an override |
| AC-22 | Hourly-scheduled databases use the `hourly` retention count |
| AC-23 | `POST /reload` picks up new database entries and updated schedules from config without a container restart |
| AC-24 | Container exits on startup with a clear error message if any configured database is unreachable |
| AC-25 | All log output is structured JSON written to stdout; backup start, completion, errors, and retention events are all logged |

---

*End of PRD – Archon v2.0*
