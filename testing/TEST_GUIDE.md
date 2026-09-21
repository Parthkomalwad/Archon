# Archon End-to-End Test Guide

Tests the full backup → inspect → simulate data loss → restore cycle against a real PostgreSQL container.

**What gets exercised:**
- Docker image build and startup
- Config file mounting and parsing
- DB connection check on startup
- `POST /backup` → job queued → backup file written to local volume
- Backup file inspection (readable `.sql` since encryption is off)
- `GET /backups`  lists the file with metadata
- `GET /status`  shows next scheduled run time
- Simulated data loss (drop a table)
- `POST /restore` → restore pipeline → table back with all rows
- `DELETE /backups/{filename}`  removes file and sidecar
- `POST /reload`  hot-reloads config without restart

---

## Prerequisites

- Docker Desktop running
- `docker compose` available (`docker compose version`)
- Run all commands from inside the `testing/` directory

---

## Step 1  Build and start the environment

```bash
cd testing
docker compose up --build
```

**What to expect in the logs:**

```
archon  | {"timestamp":"...","level":"INFO","event":"db_connection_ok","message":"Reachable at postgres:5432","database":"testdb_postgres"}
archon  | {"timestamp":"...","level":"INFO","event":"startup_ok","message":"Archon started. 1 database(s) configured."}
```

If you see `db_connection_failed`, wait 10 seconds  postgres may still be initialising. Archon retries the connection check on the next startup if the container restarts.

> Leave this terminal open (streaming logs). Open a **new terminal** for the next steps.

---

## Step 2  Verify the database has data

Connect to PostgreSQL directly from your host:

```bash
docker exec -it testing-postgres-1 psql -U testuser -d testdb
```

Inside psql:
```sql
SELECT * FROM users;
SELECT * FROM products;
\q
```

You should see 3 users and 3 products. This is the data `init.sql` seeded on first start.

---

## Step 3  Check Archon is ready

```bash
curl -s http://localhost:8765/status \
  -H "X-API-Key: test-api-key-12345" | python -m json.tool
```

Expected response:
```json
{
    "databases": [
        {
            "database": "testdb_postgres",
            "last_run_time": null,
            "next_scheduled_run": "...",
            "last_status": null,
            "currently_running": false
        }
    ]
}
```

`next_scheduled_run` will show tomorrow at `02:00 UTC`  the scheduled time from `config.yaml`.

---

## Step 4  Trigger a manual backup

```bash
curl -s -X POST http://localhost:8765/backup \
  -H "X-API-Key: test-api-key-12345" \
  -H "Content-Type: application/json" | python -m json.tool
```

Response (202 Accepted):
```json
{
    "jobs": [
        {
            "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "database": "testdb_postgres",
            "status": "queued"
        }
    ]
}
```

Copy the `job_id`.

---

## Step 5  Poll the job until it completes

Replace `<job_id>` with the value from Step 4:

```bash
curl -s http://localhost:8765/jobs/<job_id> \
  -H "X-API-Key: test-api-key-12345" | python -m json.tool
```

Run this a few times. Status transitions: `queued` → `running` → `completed`.

Final response:
```json
{
    "job_id": "...",
    "database": "testdb_postgres",
    "status": "completed",
    "queued_at": "...",
    "started_at": "...",
    "completed_at": "...",
    "backup_filename": "archon_testdb_postgres_2025-06-15T14-00-01_daily.sql",
    "error_message": null
}
```

---

## Step 6  Inspect the backup file on disk

The `backups/` folder is mounted from inside the container to `testing/backups/` on your host:

```bash
ls -lh backups/
```

You should see two files:
```
archon_testdb_postgres_2025-06-15T14-00-01_daily.sql
archon_testdb_postgres_2025-06-15T14-00-01_daily.sql.sha256
```

**Open the `.sql` file**  it's a plain pg_dump output you can read:
```bash
cat backups/archon_testdb_postgres_*.sql
```

You'll see `CREATE TABLE` statements and `COPY` data blocks for `users` and `products`.

**Check the SHA-256 sidecar:**
```bash
cat backups/archon_testdb_postgres_*.sha256
```
It contains a 64-character hex string  the SHA-256 of the backup file.

---

## Step 7  List backups via the API

```bash
curl -s "http://localhost:8765/backups" \
  -H "X-API-Key: test-api-key-12345" | python -m json.tool
```

Response:
```json
{
    "backups": [
        {
            "filename": "archon_testdb_postgres_..._daily.sql",
            "database": "testdb_postgres",
            "timestamp": "2025-06-15T14-00-01",
            "size_bytes": 3072,
            "rotation_type": "daily",
            "storage_backend": "local",
            "encrypted": false,
            "file_exists": true
        }
    ]
}
```

`encrypted: false` because `encryption.enabled: false` in `config.yaml`.

---

## Step 8  Simulate data loss

Drop a table inside the database to simulate an accident:

```bash
docker exec -it testing-postgres-1 psql -U testuser -d testdb -c "DROP TABLE products;"
```

Verify the table is gone:
```bash
docker exec -it testing-postgres-1 psql -U testuser -d testdb -c "\dt"
```

Only `users` should appear. `products` is gone.

---

## Step 9  Restore from backup

Get the exact filename from Step 6 or `GET /backups`, then run:

```bash
curl -s -X POST http://localhost:8765/restore \
  -H "X-API-Key: test-api-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "archon_testdb_postgres_2025-06-15T14-00-01_daily.sql",
    "confirm": true
  }' | python -m json.tool
```

> Replace the filename with the actual name from your `backups/` folder.

Response:
```json
{
    "status": "restored",
    "filename": "archon_testdb_postgres_..._daily.sql",
    "database": "testdb_postgres"
}
```

---

## Step 10  Verify the restore worked

```bash
docker exec -it testing-postgres-1 psql -U testuser -d testdb -c "SELECT * FROM products;"
```

All 3 products are back.

**In the Archon log stream** you will see:
```
{"event":"restore_started", "database":"testdb_postgres", ...}
{"event":"restore_completed", "database":"testdb_postgres", ...}
```

---

## Step 11  Test the auth middleware

Any request without a key returns `401`:

```bash
curl -s http://localhost:8765/status
# {"detail":"Invalid or missing X-API-Key"}

curl -s http://localhost:8765/status -H "X-API-Key: wrong-key"
# {"detail":"Invalid or missing X-API-Key"}
```

---

## Step 12  Delete a backup via API

```bash
curl -s -X DELETE \
  "http://localhost:8765/backups/archon_testdb_postgres_2025-06-15T14-00-01_daily.sql" \
  -H "X-API-Key: test-api-key-12345" | python -m json.tool
```

Check `backups/` again  both the `.sql` file and the `.sha256` sidecar are gone:

```bash
ls backups/
# (empty)
```

---

## Step 13  Test config hot-reload

Edit `testing/config.yaml`  for example change `at: "02:00"` to `at: "03:00"`.

Then reload without restarting the container:

```bash
curl -s -X POST http://localhost:8765/reload \
  -H "X-API-Key: test-api-key-12345" | python -m json.tool
```

Response:
```json
{
    "status": "reloaded",
    "databases_registered": 1,
    "errors": []
}
```

Check `GET /status`  `next_scheduled_run` now shows `03:00 UTC`.

---

## Step 14  Tear down

```bash
docker compose down          # stops containers, keeps postgres_data volume
docker compose down -v       # stops containers AND deletes postgres_data volume (full reset)
```

To also remove the backup files created during the test:
```bash
rm -rf backups/
```

---

## What each file does

| File | Purpose |
|---|---|
| `docker-compose.yml` | Starts postgres (with seed data) and archon |
| `config.yaml` | Archon config: postgres target, local storage, no encryption |
| `init.sql` | SQL run by postgres on first start  creates users + products tables with data |
| `backups/` | Created by docker compose  backup files land here from inside the container |

---

## Common issues

**`testdb_postgres` not found in logs / `startup_failed`**

The postgres container wasn't healthy when Archon started. Check:
```bash
docker compose ps    # postgres should show "healthy"
```
If postgres shows `starting`, wait 15 seconds and `docker compose restart archon`.

**`pg_dump: error: connection to server ... failed`**

Archon can reach the port but `pg_dump` authentication failed. Verify the credentials in `config.yaml` match the `POSTGRES_USER` / `POSTGRES_PASSWORD` in `docker-compose.yml`.

**Backup file is 0 bytes**

The `backups/` volume mount may not have correct permissions. Try:
```bash
mkdir -p backups && chmod 777 backups
```
then `docker compose restart archon`.

**Restore returns `404` for the sidecar**

The `.sha256` file was already deleted (Step 12) but you tried to restore from the same file. Re-run Step 4–5 to create a fresh backup first.
