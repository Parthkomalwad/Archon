# Raven Phase 5  Hands-On Test Guide

Everything runs against the local Docker stack started from `testing/`.

---

## Quick Reference

| Item | Value |
|---|---|
| Base URL | `http://localhost:8765` |
| API Key | `bQ3fphuzWk08hmHzaFpMl2jNYZYPPOH0vzMI9QGpIWY=` |
| Test app DB | `testdb_postgres` → `postgres:5432` (testdb) |
| Test data subject | **Alice Smith**  `alice@example.com` (row id 1 in `users` table) |

Set these in your shell once and paste the commands below as-is:

```powershell
$BASE = "http://localhost:8765"
$KEY  = "bQ3fphuzWk08hmHzaFpMl2jNYZYPPOH0vzMI9QGpIWY="
$H    = @{ "X-API-Key" = $KEY; "Content-Type" = "application/json" }
```

---

## 1 · Knowledge Base  Upload Text

Paste in a short custom compliance note so you can see it appear in the Documents tab and later be cited by the bot.

```powershell
$body = @{
    title         = "Custom Note: Backup Retention After Erasure"
    content       = "Under Art.17(3)(b) GDPR, a controller may retain a backup containing personal data for the shortest time necessary and must ensure the data is not further processed. When the backup rotation cycle deletes the file, the erasure obligation is discharged. This is documented in the proof-of-deletion report."
    document_type = "custom"
    jurisdiction  = "EU"
} | ConvertTo-Json

Invoke-RestMethod -Uri "$BASE/knowledge/documents" -Method POST -Headers $H -Body $body
```

**Expected:** `{ "document_ids": ["<uuid>", ...], "chunks_ingested": 2 }`  the text is split into ~2 chunks.

---

## 2 · Knowledge Base  Upload from URL

Ingest the official ICO guidance page on right to erasure. Raven fetches, strips HTML, chunks and embeds it.

```powershell
$body = @{
    title         = "ICO  Right to Erasure (Right to be Forgotten)"
    url           = "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/"
    document_type = "guideline"
    jurisdiction  = "UK"
} | ConvertTo-Json

Invoke-RestMethod -Uri "$BASE/knowledge/documents" -Method POST -Headers $H -Body $body
```

**Expected:** `{ "document_ids": [...], "chunks_ingested": 15 }` (number varies by page length).

> **No API key yet?** The ingest still works  it stores the content as JSONB without embeddings. The bot endpoints need the key; ingest and browse work without it.

---

## 3 · Knowledge Base  Browse Documents

```powershell
# All documents
Invoke-RestMethod -Uri "$BASE/knowledge/documents?limit=20" -Headers $H

# Filter by type
Invoke-RestMethod -Uri "$BASE/knowledge/documents?doc_type=guideline&limit=20" -Headers $H

# Filter by jurisdiction
Invoke-RestMethod -Uri "$BASE/knowledge/documents?jurisdiction=UK&limit=20" -Headers $H
```

---

## 4 · Knowledge Base  URL Watcher

Add a source that Raven checks every night at 03:30 and re-ingests automatically if the page content changes.

```powershell
# Add a watched URL (EUR-Lex  Art.17 GDPR)
$body = @{
    url            = "https://gdpr-info.eu/art-17-gdpr/"
    frequency      = "daily"
    on_new_content = "auto"
} | ConvertTo-Json

Invoke-RestMethod -Uri "$BASE/knowledge/sources" -Method POST -Headers $H -Body $body
```

```powershell
# List all sources
Invoke-RestMethod -Uri "$BASE/knowledge/sources" -Headers $H
```

```powershell
# Force a sync right now (runs in background, returns 202)
Invoke-RestMethod -Uri "$BASE/knowledge/sync" -Method POST -Headers $H
```

After 5-10 seconds, GET `/knowledge/sources` again  `last_checked` updates and `status` becomes `ok`.

---

## 5 · Bot Query

The bot requires:
- **OPENAI_API_KEY**  always required for embeddings (vector search)
- **CLAUDE_API_KEY** *or* **GEMINI_API_KEY**  at least one LLM for answer generation

If both `claude_api_key` and `gemini_api_key` are set, **Claude is used** (preferred).

### Option A  Claude (recommended)

```yaml
openai_api_key: sk-...
claude_api_key: sk-ant-...
knowledge_seed_on_startup: true   # seeds 23 GDPR articles + 5 EDPB guidelines on first boot
```

### Option B  Gemini

```yaml
openai_api_key: sk-...
gemini_api_key: AIza...            # Google AI Studio key
knowledge_seed_on_startup: true
```

> **Get a Gemini key:** [Google AI Studio](https://aistudio.google.com/app/apikey) → "Create API key" → free tier available.
> The bot uses **gemini-2.0-flash** (fast + cost-effective).

Add the chosen config block to `testing/config.yaml`, then rebuild:

```powershell
docker compose up --build -d backops
```

Confirm the correct LLM loaded  look for this in the startup logs:

```powershell
docker compose logs backops | Select-String "AI clients"
```

Expected for Gemini: `AI clients initialised (OpenAI embeddings + Gemini generation)`

### Ask the bot

```powershell
$body = @{ question = "Do I need to delete backup files when a user requests erasure under Art.17?" } | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$BASE/bot/query" -Method POST -Headers $H -Body $body
$resp | ConvertTo-Json -Depth 5
```

**What to look for:**
- `answer`  paragraph citing the Art.17(3)(b) exception about backups
- `citations`  array with at least one `{"title": "...", "source_url": "...", "excerpt": "..."}`
- `feedback_id`  UUID you'll use in step 6

```powershell
# Save the feedback_id for the next step
$FID = $resp.feedback_id
```

---

## 6 · Feedback Queue

Simulate a reviewer marking an answer wrong and providing a correction.

```powershell
# Mark wrong with correction
$body = @{
    feedback   = "wrong"
    correction = "Art.17(3)(b) only exempts processing necessary for archiving purposes in the public interest, not standard operational backups. A DPA may take a stricter view."
} | ConvertTo-Json

Invoke-RestMethod -Uri "$BASE/bot/feedback/$FID" -Method POST -Headers $H -Body $body
```

**What happens behind the scenes:**
1. The `bot_feedback` row is updated with `feedback = 'wrong'` and `reviewed = TRUE`.
2. If `openai_client` is available, the correction text is **automatically ingested** as a new `custom` knowledge document so future answers reflect the correction.

```powershell
# Browse the feedback queue (unreviewed wrong/partial answers)
Invoke-RestMethod -Uri "$BASE/bot/feedback?feedback=wrong&reviewed=false" -Headers $H

# All feedback regardless of status
Invoke-RestMethod -Uri "$BASE/bot/feedback?limit=20" -Headers $H
```

---

## 7 · GDPR Full Flow  Alice Smith (alice@example.com)

Alice is in the `users` table of `testdb_postgres` (id = 1). We'll:
1. Submit an erasure request for her
2. Trigger the deletion workflow
3. Watch the state machine run: `pending → scanning → deleting → completed`
4. Download the PDF proof of deletion

### Step 1  Submit the erasure request

```powershell
$body = @{
    subject_email = "alice@example.com"
    request_type  = "erasure"
    notes         = "User submitted via account settings on 2026-03-06"
} | ConvertTo-Json

$req = Invoke-RestMethod -Uri "$BASE/gdpr/request" -Method POST -Headers $H -Body $body
$req | ConvertTo-Json
```

**Expected response:**
```json
{
  "id": "<uuid>",
  "request_ref": "REQ-XXXXXXXX",
  "subject_email": "alice@example.com",
  "request_type": "erasure",
  "status": "pending",
  "requested_at": "2026-03-06T...",
  "deadline_at": "2026-04-05T..."
}
```

```powershell
# Save for later
$RID = $req.id
$REF = $req.request_ref
```

### Step 2  Check it's pending

```powershell
Invoke-RestMethod -Uri "$BASE/gdpr/request/$RID" -Headers $H
```

### Step 3  Trigger the deletion workflow

This runs in the background. Returns 202 immediately.

```powershell
Invoke-RestMethod -Uri "$BASE/gdpr/request/$RID/process" -Method POST -Headers $H
```

**What Raven does in the background:**
1. `pending → scanning`  reads every backup file in local storage, decrypts it, parses the pg_dump COPY blocks, and searches every row for `alice@example.com`
2. Any matched row is archived into `archived_rows` in Raven DB (with `data_before`, `backup_file_ref`, and any retention-rule `retain_until` date)
3. `scanning → deleting`  connects to the live `testdb_postgres` and runs `DELETE FROM users WHERE email = 'alice@example.com'`; same for any other tables with matching data
4. `deleting → completed`  writes the proof document reference

### Step 4  Poll until completed

```powershell
# Run a few times, or paste into a loop
do {
    $s = Invoke-RestMethod -Uri "$BASE/gdpr/request/$RID" -Headers $H
    Write-Host ("Status: " + $s.status)
    Start-Sleep -Seconds 2
} until ($s.status -in "completed","failed")
$s | ConvertTo-Json
```

### Step 5  Verify Alice is gone from the live DB

```powershell
# Connect to the postgres container and check
docker exec testing-postgres-1 psql -U testuser -d testdb -c "SELECT * FROM users;"
```

Expected: Alice's row is gone. Bob and Charlie remain.

### Step 6  Download the proof-of-deletion PDF

```powershell
Invoke-WebRequest `
    -Uri "$BASE/gdpr/request/$RID/report" `
    -Headers @{ "X-API-Key" = $KEY } `
    -OutFile "proof_${REF}.pdf"

Start-Process "proof_${REF}.pdf"
```

The PDF contains:
- Request reference and subject email
- List of every table scanned
- Per-backup-file: which rows matched, whether they were archived or blocked by a retention rule
- SHA-256 of the deletion evidence
- Timestamp of completion

### Step 7  Export the archived data (right-to-access)

If Alice had submitted an `access` request instead, this is the data dump:

```powershell
Invoke-RestMethod -Uri "$BASE/gdpr/request/$RID/export" -Headers $H | ConvertTo-Json -Depth 6
```

Returns the exact row values that were found and archived from each backup file.

---

## 8 · Retention Rules

Retention rules let you block deletion of certain tables (e.g. financial records must be kept 7 years).

```powershell
# Add a rule: audit_log must be kept 2555 days (7 years)  legal basis: tax law
$body = @{
    database_name    = "testdb_postgres"
    table_name       = "audit_log"
    data_category    = "financial"
    retention_days   = 2555
    legal_basis      = "Tax Procedures Act §147  7-year retention obligation"
    exemption_clause = "Art.17(3)(b) GDPR"
    auto_delete      = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri "$BASE/gdpr/retention-rules" -Method POST -Headers $H -Body $body
```

```powershell
# List all rules for the test DB
Invoke-RestMethod -Uri "$BASE/gdpr/retention-rules?database=testdb_postgres" -Headers $H
```

When the GDPR deletion workflow runs and finds a row in `audit_log` matching the subject, it will **archive but not delete** the row, set `retain_until = now + 2555 days`, and note the legal basis in the PDF report.

---

## 9 · Audit Log

Every API action creates an immutable audit entry.

```powershell
# All events
Invoke-RestMethod -Uri "$BASE/audit-log?limit=30" -Headers $H

# Filter to GDPR events only
Invoke-RestMethod -Uri "$BASE/audit-log?event_type=gdpr_request_created&limit=20" -Headers $H
```

---

## 10 · Quick Smoke Test  All Knowledge Endpoints

| # | Command | Expected |
|---|---|---|
| 1 | `GET /knowledge/documents` | 200 + `{ documents: [...] }` |
| 2 | `POST /knowledge/documents` (text body) | 201 + chunk count |
| 3 | `POST /knowledge/documents` (url body) | 201 + chunk count |
| 4 | `GET /knowledge/sources` | 200 + `{ sources: [...] }` |
| 5 | `POST /knowledge/sources` | 201 + source record |
| 6 | `POST /knowledge/sync` | 202 + `{ status: "accepted" }` |
| 7 | `GET /bot/feedback` | 200 + `{ feedback: [...] }` |
| 8 | `POST /bot/feedback/{id}` | 200 + updated record |
| 9 | `POST /bot/query` (no keys set) | 503 + "AI bot not configured" |
| 10 | `POST /bot/query` (Gemini key only) | 200 + answer from Gemini |

---

## 11 · Troubleshooting

| Symptom | Check |
|---|---|
| `503 Persistence not configured` on GDPR endpoints | Raven DB not reachable  confirm `raven-db` container is healthy: `docker compose ps` |
| `503 AI bot not configured` | Add `openai_api_key` + `claude_api_key` (or `gemini_api_key`) to config.yaml, rebuild |
| GDPR request stuck in `scanning` | Check `docker compose logs backops`  likely a storage path issue or decryption failure |
| URL ingest returns 0 chunks | The page may block bots. Try a direct text paste instead |
| PDF report download fails with 400 | Request is not `completed` yet  poll status first |

---

*Raven v3 · Phase 5 test guide · Generated 2026-03-06*
