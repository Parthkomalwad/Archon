# Archon – Build Task List & Checkpoint Reference
**v2.0 | Reference: Archon-PRD.md v2.0**

---

## How to Use This File

- `[ ]` = not started &nbsp; `[x]` = done
- Work through phases **in order**  each phase builds on the previous
- **Do not start the next phase until all Checkpoint items pass**
- Phase status: ⬜ Not Started | 🔄 In Progress | ✅ Complete

---

## Phase Overview

| Phase | What Gets Built | Status |
|---|---|---|
| Phase 1 | Core scaffolding  config, logger, job store, FastAPI stub | ✅ |
| Phase 2 | DB Providers  PostgreSQL, MongoDB, SQLite | ✅ |
| Phase 3 | Storage Backends  Local, S3, Azure | ✅ |
| Phase 4 | Encryption + SHA-256 Integrity | ✅ |
| Phase 5 | ScheduleParser  human-readable → cron | ✅ |
| Phase 6 | Scheduler + RetentionManager | ✅ |
| Phase 7 | REST API  all endpoints wired up | ✅ |
| Phase 8 | Docker + Docs | ✅ |

---

## Phase 1  Core Scaffolding

> **Goal:** Project skeleton is in place. Config loads. FastAPI starts. Auth works. Logging works. Job store exists.

### 1.1 Project Structure
- [ ] Create directory layout per PRD Section 15:
  ```
  archon/app/providers/ archon/app/storage/ archon/app/api/ archon/tests/
  ```
- [ ] Create `requirements.txt` with all packages from PRD Section 16

### 1.2 Structured Logger (`app/logger.py`)
- [ ] JSON logger writing to stdout
- [ ] Fields: `timestamp` (UTC ISO 8601), `level`, `database`, `event`, `message`, `error`
- [ ] Single shared logger instance imported by all modules

### 1.3 ConfigLoader (`app/config.py`)
- [ ] Parse `databases` list into typed objects
- [ ] Parse `storage` backends (local, s3, azure)
- [ ] Parse `encryption` config
- [ ] Parse `retention` config  global block
- [ ] Parse per-database `retention` override  missing keys fall back to global
- [ ] Env var interpolation: `${VAR_NAME}` → actual value, fail if env var is missing
- [ ] Validate optional `authdb` on MongoDB entries  default to `"admin"` if absent
- [ ] Validate each database's `storage:` value references a defined storage backend
- [ ] Validate `api.port` and `api.api_key` present
- [ ] Fail fast with clear error message on any validation failure

### 1.4 Abstract Base Classes
- [ ] `app/providers/base.py`  `BaseProvider(ABC)` with `backup()` and `restore()` abstract methods
- [ ] `app/storage/base.py`  `BaseStorage(ABC)` with `write()`, `read()`, `list()`, `delete()`, `exists()` abstract methods

### 1.5 JobStore + JobQueue (`app/jobs.py`)
- [ ] `JobStore`  dict keyed by UUID job ID
- [ ] Job schema: `job_id`, `status` (`queued|running|completed|failed`), `database`, `queued_at`, `started_at`, `completed_at`, `backup_filename`, `error_message`
- [ ] `create_job(database)` → returns `job_id`
- [ ] `update_job(job_id, **fields)` → updates job in place
- [ ] `get_job(job_id)` → returns job dict or `None`
- [ ] Auto-purge: background task removes jobs older than 24h
- [ ] `JobQueue`  one `asyncio.Queue` per database name, created on demand

### 1.6 FastAPI App (`app/main.py`)
- [ ] Create FastAPI app instance
- [ ] Mount API router from `app/api/routes.py`
- [ ] On startup (lifespan event):
  - [ ] Load config
  - [ ] Attempt DB connection check for every configured database  `sys.exit(1)` with logged error if any fail
  - [ ] Initialise `JobStore` and `JobQueue`
  - [ ] Register `BackupJob` cron schedules with APScheduler (stub  actual logic in Phase 6)
  - [ ] Log `startup_ok` event

### 1.7 API Key Middleware (`app/api/middleware.py`)
- [ ] Read `X-API-Key` header on every request
- [ ] Compare to in-memory value from config
- [ ] Return `401 Unauthorized` if missing or mismatched

### 1.8 GET /status Stub (`app/api/routes.py`)
- [ ] Route registered and protected by auth middleware
- [ ] Returns 200 with empty per-database status placeholder
- [ ] Returns 401 without correct API key

---

### ✅ Phase 1 Checkpoint

Before moving to Phase 2, verify **all** of the following:

- [ ] `uvicorn app.main:app` starts without errors with a valid `config.yaml`
- [ ] `GET /status` returns `200` with valid JSON
- [ ] `GET /status` without `X-API-Key` returns `401`
- [ ] Any request with wrong API key returns `401`
- [ ] Container exits with a clear log error if `config.yaml` is missing
- [ ] Container exits with a clear log error if `config.yaml` has an invalid `storage:` reference
- [ ] Container exits with a clear log error if a `${VAR_NAME}` env var is missing
- [ ] Container exits with a clear log error if any configured database is unreachable on startup
- [ ] All startup events appear as structured JSON in stdout

---

## Phase 2  DB Providers

> **Goal:** All three database types can be backed up and fully restored (drop-and-recreate).

### 2.1 PostgreSQL Provider (`app/providers/postgres.py`)
- [ ] `backup(output_path)`:
  - [ ] Run `pg_dump` via `subprocess`  output `.sql` file to `output_path`
  - [ ] Log `backup_started` and `backup_completed` (with file size) events
  - [ ] Raise exception with log on non-zero exit code
- [ ] `restore(backup_path, confirm)`:
  - [ ] Raise if `confirm != True`
  - [ ] `DROP DATABASE` the target DB
  - [ ] `CREATE DATABASE` fresh
  - [ ] Run `pg_restore` / `psql` to load backup
  - [ ] Log `restore_started` and `restore_completed` events

### 2.2 MongoDB Provider (`app/providers/mongodb.py`)
- [ ] `backup(output_path)`:
  - [ ] Run `mongodump` via subprocess  output `.archive` file
  - [ ] Pass `--authenticationDatabase` from `authdb` config field (default `admin`)
  - [ ] Log start, completion, errors
- [ ] `restore(backup_path, confirm)`:
  - [ ] Raise if `confirm != True`
  - [ ] Run `mongorestore --drop` (drops collections before restoring)
  - [ ] Pass `--authenticationDatabase` from `authdb` config field
  - [ ] Log start, completion, errors

### 2.3 SQLite Provider (`app/providers/sqlite.py`)
- [ ] `backup(output_path)`:
  - [ ] Use Python `sqlite3.connect(source).backup(dest_conn)`  safe hot-copy for active DBs
  - [ ] Output `.db` file to `output_path`
  - [ ] Log start, completion, errors
- [ ] `restore(backup_path, confirm)`:
  - [ ] Raise if `confirm != True`
  - [ ] Delete existing `.db` file at configured path
  - [ ] Copy backup file into place
  - [ ] Log start, completion, errors

### 2.4 ProviderFactory (`app/providers/__init__.py`)
- [ ] `get_provider(db_config)` → returns correct provider instance based on `type` field
- [ ] Raise clear error for unknown type

### 2.5 Unit Tests (`tests/test_providers.py`)
- [ ] PostgreSQL: mock `subprocess.run`, verify `pg_dump` called with correct args
- [ ] PostgreSQL restore: verify DROP + CREATE + pg_restore sequence
- [ ] MongoDB: verify `mongodump` called with `--authenticationDatabase admin` by default
- [ ] MongoDB: verify custom `authdb` is passed correctly
- [ ] SQLite: verify `.backup()` API is used (not file copy)
- [ ] All providers: verify exception raised if `confirm != True` on restore

---

### ✅ Phase 2 Checkpoint

- [ ] `pg_dump` runs against a live PostgreSQL container and produces a valid `.sql` file
- [ ] `pg_restore` fully restores data; original data is confirmed gone (drop-and-recreate)
- [ ] `mongodump` runs against a live MongoDB container and produces a valid archive file
- [ ] `mongorestore --drop` fully restores MongoDB data
- [ ] SQLite `.backup()` produces a valid copy of a database with concurrent writes happening
- [ ] SQLite restore deletes and replaces the `.db` file correctly
- [ ] All provider unit tests pass

---

## Phase 3  Storage Backends

> **Goal:** Files can be written, read, listed, deleted, and existence-checked on all three backends.

### 3.1 Local Storage (`app/storage/local.py`)
- [ ] `write(filename, data: bytes)`  write to configured local path
- [ ] `read(filename) -> bytes`  read file bytes
- [ ] `list(prefix: str) -> list[dict]`  return files matching prefix with name + size
- [ ] `delete(filename)`  delete file; no-op if not found
- [ ] `exists(filename) -> bool`  `os.path.exists` check

### 3.2 S3 Storage (`app/storage/s3.py`)
- [ ] `write(filename, data: bytes)`  upload object to bucket with configured prefix
- [ ] `read(filename) -> bytes`  download object bytes
- [ ] `list(prefix: str) -> list[dict]`  list objects with prefix, return name + size
- [ ] `delete(filename)`  delete object from bucket
- [ ] `exists(filename) -> bool`  `head_object` call; return `False` on 404

### 3.3 Azure Storage (`app/storage/azure.py`)
- [ ] `write(filename, data: bytes)`  upload blob to container
- [ ] `read(filename) -> bytes`  download blob bytes
- [ ] `list(prefix: str) -> list[dict]`  list blobs with prefix, return name + size
- [ ] `delete(filename)`  delete blob
- [ ] `exists(filename) -> bool`  `get_blob_properties`; return `False` on `ResourceNotFoundError`

### 3.4 StorageFactory (`app/storage/__init__.py`)
- [ ] `get_storage(storage_config)` → returns correct backend instance based on type key
- [ ] Raise clear error for unknown backend type

---

### ✅ Phase 3 Checkpoint

- [ ] A file written to local storage can be read back, listed, and deleted
- [ ] A file written to S3 appears in the bucket, can be downloaded, listed, and deleted via Archon
- [ ] A file written to Azure Blob appears in the container, can be downloaded, listed, and deleted
- [ ] `list()` for each backend returns only files matching the given prefix (no cross-database bleed)
- [ ] `exists()` returns `True` for an existing file and `False` for a non-existent file on all backends
- [ ] `delete()` on a non-existent file does not raise an exception

---

## Phase 4  Encryption + Integrity

> **Goal:** Backups are encrypted before storage. SHA-256 checksums are generated and verified on restore.

### 4.1 EncryptionService (`app/encryption.py`)
- [ ] `encrypt(data: bytes) -> bytes`:
  - [ ] Generate random 16-byte IV
  - [ ] AES-256-CBC encrypt with IV
  - [ ] Return `IV + ciphertext`
- [ ] `decrypt(data: bytes) -> bytes`:
  - [ ] Extract first 16 bytes as IV
  - [ ] Decrypt remainder
  - [ ] Return plaintext
- [ ] `enabled` flag  when `False`, `encrypt()` and `decrypt()` are pass-throughs
- [ ] Filename helper: `get_extension() -> str`  returns `".enc"` if enabled, `""` if disabled

### 4.2 SHA-256 Integrity
- [ ] `compute_checksum(data: bytes) -> str`  returns hex SHA-256 string
- [ ] `verify_checksum(data: bytes, expected_hex: str) -> bool`
- [ ] Integrate into backup flow:
  - [ ] After encryption, compute checksum of final bytes
  - [ ] Write `<filename>.sha256` to same storage backend as backup
- [ ] Integrate into restore flow:
  - [ ] Read `.sha256` sidecar from storage
  - [ ] Verify checksum  raise `IntegrityError` with log if mismatch (abort before touching DB)

### 4.3 Unit Tests (`tests/test_encryption.py`)
- [ ] `encrypt → decrypt` roundtrip produces original plaintext
- [ ] Different IVs produce different ciphertext for same input
- [ ] Tampered ciphertext (1 byte changed) produces garbage on decrypt (not original data)
- [ ] `enabled: false`  encrypt/decrypt are pass-throughs
- [ ] `compute_checksum` is deterministic for same input
- [ ] `verify_checksum` returns `False` for modified data

---

### ✅ Phase 4 Checkpoint

- [ ] Encrypted backup file is unreadable as plaintext
- [ ] Decrypting the file returns the exact original backup bytes
- [ ] A `.sha256` sidecar file is created alongside every backup in storage
- [ ] Corrupted backup (1 byte changed in storage) causes restore to abort with `IntegrityError` before touching the database
- [ ] With `encryption.enabled: false`, file has no `.enc` suffix and data is unchanged
- [ ] All encryption unit tests pass

---

## Phase 5  ScheduleParser

> **Goal:** Human-readable schedule config is correctly converted to cron expressions.

### 5.1 ScheduleParser (`app/schedule_parser.py`)
- [ ] `parse(schedule_config) -> str`  returns cron expression string
- [ ] Handle `frequency: daily` + `at: "HH:MM"` → `0 HH * * *`
- [ ] Handle `frequency: weekly` + `on: <day_name>` + `at` → `0 HH * * D`
  - [ ] Validate day names: `monday`–`sunday` (map to 0–6)
- [ ] Handle `frequency: monthly` + `on: <1-28>` + `at` → `0 HH DOM * *`
  - [ ] Reject values 29–31 with clear error
- [ ] Handle `frequency: hourly` → `0 * * * *` (no `at` field needed)
- [ ] Handle raw `cron: "<expression>"`  pass through unchanged, skip all validation
- [ ] Validate IANA timezone string using `pytz.timezone()`  raise error on invalid
- [ ] Raise `ConfigError` with specific message for any invalid schedule config

### 5.2 Unit Tests (`tests/test_schedule_parser.py`)
- [ ] `daily + at: "14:00"` → `"0 14 * * *"`
- [ ] `weekly + on: sunday + at: "03:00"` → `"0 3 * * 0"`
- [ ] `weekly + on: monday + at: "09:00"` → `"0 9 * * 1"`
- [ ] `monthly + on: 1 + at: "00:00"` → `"0 0 1 * *"`
- [ ] `monthly + on: 28 + at: "12:00"` → `"0 12 28 * *"`
- [ ] `monthly + on: 29` → raises `ConfigError`
- [ ] `hourly` → `"0 * * * *"`
- [ ] `cron: "*/30 * * * *"` → `"*/30 * * * *"` (passthrough)
- [ ] Invalid timezone string → raises `ConfigError`
- [ ] Invalid day name (e.g., `on: funday`) → raises `ConfigError`

---

### ✅ Phase 5 Checkpoint

- [ ] All ScheduleParser unit tests pass
- [ ] Invalid schedule configs produce clear, specific error messages
- [ ] Raw cron string passes through without modification

---

## Phase 6  Scheduler + RetentionManager

> **Goal:** Scheduled backups fire automatically. Old backups are cleaned up after each run. Queuing works.

### 6.1 Scheduler (`app/scheduler.py`)
- [ ] Initialise APScheduler `AsyncIOScheduler`
- [ ] For each `BackupJob` in config, register a timezone-aware cron job using parsed cron expression
- [ ] Each cron job calls the full backup pipeline:
  1. Acquire per-database `JobQueue` slot (queue if busy)
  2. Create job in `JobStore` (status: `running`)
  3. Run provider `backup()` → temp file
  4. Run `EncryptionService.encrypt()` → encrypted bytes
  5. Compute SHA-256 checksum
  6. Write encrypted file to storage backend
  7. Write `.sha256` sidecar to storage backend
  8. Run `RetentionManager`
  9. Update `JobStore` job to `completed` with filename
  10. Log `backup_completed`
  - [ ] On any exception: update job to `failed`, log `backup_failed` with error
- [ ] Scheduler starts when FastAPI app starts (lifespan)
- [ ] `POST /reload` cancels all jobs and re-registers from new config

### 6.2 RetentionManager (`app/retention.py`)
- [ ] `enforce(database_name, storage_backend, retention_config)`:
  - [ ] List all backup files for this database from storage
  - [ ] Parse rotation type from filename (`_daily`, `_weekly`, `_monthly`, `_hourly`)
  - [ ] Group by rotation type
  - [ ] For each type: sort by timestamp (oldest first), delete files beyond keep count
  - [ ] Also delete `.sha256` sidecar for every deleted backup
  - [ ] **Overlap rule:** A file qualifying as both weekly and monthly → kept under the longer window
  - [ ] Use per-database retention override if present; fall back to global for missing keys
  - [ ] Log `retention_run` event with count of deleted files

### 6.3 Unit Tests (`tests/test_retention.py`)
- [ ] Daily limit: 8 daily backups with limit 7 → oldest 1 deleted
- [ ] Weekly limit enforced independently of daily
- [ ] Monthly limit enforced independently
- [ ] Hourly limit enforced independently
- [ ] Sunday + 1st (weekly + monthly overlap) → file kept under monthly window (12), not weekly (4)
- [ ] Per-database override: database with `daily: 14` keeps 14, not global 7
- [ ] Global fallback: database without override uses global values
- [ ] `.sha256` sidecar is deleted alongside its backup file

---

### ✅ Phase 6 Checkpoint

- [ ] Scheduled backup fires at the correct time (test with a 1-minute schedule temporarily)
- [ ] Two databases on different schedules fire independently without blocking each other
- [ ] When two backup requests arrive for the same database simultaneously, the second queues and runs after the first completes
- [ ] `RetentionManager` deletes the oldest backup when the count limit is exceeded
- [ ] `.sha256` sidecar is deleted when its backup is purged
- [ ] Per-database retention override takes effect correctly
- [ ] All retention unit tests pass

---

## Phase 7  REST API Complete

> **Goal:** All endpoints are fully wired with real logic, job tracking, integrity checks, and cloud-aware delete.

### 7.1 POST /backup
- [ ] Parse optional `{ "database": "name" }` body
- [ ] If `database` specified: enqueue that database only; if omitted: enqueue all databases
- [ ] For each database: create job in `JobStore`, add to `JobQueue`, kick off backup coroutine
- [ ] Return `202` with `{ "jobs": [{ "job_id": "...", "database": "...", "status": "queued" }] }`
- [ ] Return `404` if specified `database` name not found in config

### 7.2 GET /jobs/{job_id}
- [ ] Return full job dict from `JobStore`
- [ ] Return `404` if job not found or purged

### 7.3 POST /restore
- [ ] Validate `confirm: true` present  return `400` if missing
- [ ] Determine target database:
  - [ ] If `target_database` in body: use that  return `404` if not in config
  - [ ] Else: infer from `db_name` embedded in filename
- [ ] Read backup file bytes from storage backend
- [ ] Read `.sha256` sidecar  if missing, abort with `404`
- [ ] Verify SHA-256 checksum  if mismatch, abort with `400 "Integrity check failed"`
- [ ] Decrypt bytes (if encryption enabled)
- [ ] Write decrypted bytes to temp file
- [ ] Call provider `restore(temp_path, confirm=True)`
- [ ] Return `200` on success, `500` with error on failure
- [ ] Log `restore_started` and `restore_completed` or `restore_failed`

### 7.4 GET /backups
- [ ] Optional `?database=<name>` query param
- [ ] List files from all storage backends (or filtered by database name prefix)
- [ ] For each file, resolve storage backend, check `exists()`, build extended metadata:
  - `filename`, `database`, `timestamp`, `size_bytes`, `rotation_type`, `storage_backend`, `encrypted`, `file_exists`
- [ ] Return `200` with `{ "backups": [...] }`

### 7.5 GET /status
- [ ] For each database in config, return:
  - `database`, `last_run_time`, `next_scheduled_run`, `last_status`, `currently_running`
- [ ] Return `200` with `{ "databases": [...] }`

### 7.6 DELETE /backups/{filename}
- [ ] Determine which storage backend owns the file (from database name in filename)
- [ ] Call `storage.delete(filename)`  return `404` if file not found
- [ ] Call `storage.delete(filename + ".sha256")`  no error if sidecar missing
- [ ] Log `backup_deleted` event
- [ ] Return `200` on success

### 7.7 POST /reload
- [ ] Re-read `/app/config.yaml` from disk
- [ ] Validate new config  return `400` with errors if invalid (existing jobs keep running)
- [ ] On valid config: cancel all APScheduler jobs
- [ ] Re-register all `BackupJob` cron schedules from new config
- [ ] Log `config_reloaded` event
- [ ] Return `200` with `{ "status": "reloaded", "databases_registered": N, "errors": [] }`

---

### ✅ Phase 7 Checkpoint

- [ ] `POST /backup` returns `202` with a valid UUID job ID
- [ ] `GET /jobs/{job_id}` shows `queued → running → completed` status transitions
- [ ] `GET /jobs/{job_id}` returns `404` for an unknown or purged job ID
- [ ] `POST /restore` without `confirm: true` returns `400`
- [ ] `POST /restore` with a tampered file (checksum mismatch) returns `400` before touching the DB
- [ ] `POST /restore` with `target_database` successfully restores to the correct database
- [ ] `GET /backups` returns extended metadata including `file_exists: true/false`
- [ ] `DELETE /backups/{filename}` removes the file from S3/Azure and deletes the `.sha256` sidecar
- [ ] `POST /reload` picks up a new database entry added to config without restarting the container
- [ ] All endpoints return `401` without correct `X-API-Key`

---

## Phase 8  Docker + Docs

> **Goal:** Service is containerised, documented, and ready to drop into any project.

### 8.1 Dockerfile
- [ ] Base: `ubuntu:22.04`
- [ ] Install Python 3.11 via apt (`python3.11`, `python3.11-pip` or `python3-pip`)
- [ ] Add MongoDB official apt repository (`repo.mongodb.org/apt/ubuntu`)
- [ ] Install `mongodb-database-tools` from MongoDB apt repo
- [ ] Install `postgresql-client` (provides `pg_dump`, `pg_restore`, `psql`)
- [ ] Install `sqlite3`
- [ ] Copy `requirements.txt` and run `pip install -r requirements.txt`
- [ ] Copy `app/` directory
- [ ] Expose port `8765`
- [ ] `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]`

### 8.2 docker-compose Example
- [ ] Write `docker-compose.yml` example with the sidecar block from PRD Section 4.1
- [ ] Include commented example showing `depends_on` with healthcheck for the database container

### 8.3 config.yaml.example
- [ ] Full annotated example from PRD Section 5 including all new fields (`authdb`, per-database `retention`, `hourly` retention)

### 8.4 README.md
- [ ] Quickstart  5 steps from zero to first backup
- [ ] Config reference  every field documented with type, required/optional, default
- [ ] API reference  all endpoints with request/response examples
- [ ] Troubleshooting  common errors (DB unreachable, bad config, wrong API key, checksum mismatch)

---

### ✅ Phase 8 Checkpoint

- [ ] `docker build -t archon:latest .` completes with no errors
- [ ] `docker run` with valid `config.yaml` mounted starts successfully and logs `startup_ok`
- [ ] `docker run` with missing `config.yaml` exits immediately with a clear error log
- [ ] `docker run` with a misconfigured DB exits immediately with a clear error log
- [ ] Full end-to-end test: scheduled backup fires, encrypted file + `.sha256` sidecar appear in storage, `POST /restore` restores the database successfully

---

## Full Acceptance Criteria Checklist

These map 1:1 to PRD Section 19. Sign off on each when confirmed in a real environment.

- [ ] **AC-1** PostgreSQL backup + restore; SHA-256 integrity passes on restore
- [ ] **AC-2** MongoDB backup + restore; drop-and-recreate confirmed
- [ ] **AC-3** SQLite hot-copy backup + restore confirmed
- [ ] **AC-4** AES-256 encrypted files are unreadable without the key
- [ ] **AC-5** Backups written correctly to Local, S3, and Azure
- [ ] **AC-6** Scheduled backups fire without manual intervention
- [ ] **AC-7** Retention deletes oldest backups across all 4 types when limit exceeded
- [ ] **AC-8** `/restore` without `confirm: true` returns `400`
- [ ] **AC-9** All endpoints return `401` without correct `X-API-Key`
- [ ] **AC-10** Service added to any docker-compose via single block
- [ ] **AC-11** 3-database config produces 3 independent, non-interfering backup jobs
- [ ] **AC-12** `/backup` with database name triggers one DB; without body triggers all
- [ ] **AC-13** Backup filenames namespaced by DB name  no collisions in shared storage
- [ ] **AC-14** ScheduleParser converts all schedule types to correct cron expressions
- [ ] **AC-15** Raw cron passthrough works correctly
- [ ] **AC-16** Two databases same `at:` different timezones fire at different UTC times
- [ ] **AC-17** `POST /backup` returns 202 + job ID; `GET /jobs/{job_id}` shows correct state transitions
- [ ] **AC-18** `/restore` with `target_database` restores to correct target
- [ ] **AC-19** Corrupted backup aborts restore with error before touching DB
- [ ] **AC-20** `DELETE /backups/{filename}` removes from cloud storage + deletes `.sha256` sidecar
- [ ] **AC-21** Per-database retention override takes precedence over global
- [ ] **AC-22** Hourly backups use `hourly` retention count
- [ ] **AC-23** `POST /reload` picks up config changes without container restart
- [ ] **AC-24** Container exits on startup if any configured DB is unreachable
- [ ] **AC-25** All log output is structured JSON to stdout

---

*Last updated: 2026-03-02 | Ref: Archon-PRD.md v2.0*
