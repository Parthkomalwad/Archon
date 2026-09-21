import { useEffect, useRef, useState } from "react";
import TopNav from "../components/TopNav";

// ─── Theme ────────────────────────────────────────────────────────────────────

const T = {
  bg: "#0C1120",
  surface: "#1E293B",
  border: "#2D3F57",
  primary: "#6366F1",
  text: "#F1F5F9",
  muted: "#64748B",
};

// ─── Sidebar sections ─────────────────────────────────────────────────────────

const sections = [
  { id: "quick-start", label: "Quick Start" },
  { id: "docker-setup", label: "Docker Setup" },
  { id: "config-reference", label: "config.yaml Reference" },
  { id: "database-providers", label: "Database Providers" },
  { id: "storage-backends", label: "Storage Backends" },
  { id: "encryption", label: "Encryption" },
  { id: "scheduling", label: "Scheduling" },
  { id: "retention", label: "Retention" },
  { id: "api-reference", label: "REST API Reference" },
  { id: "webhooks", label: "Webhooks" },
];

// ─── Code block ───────────────────────────────────────────────────────────────

function Code({ lang, children }: { lang: string; children: string }) {
  return (
    <div className="relative rounded-xl overflow-hidden my-4" style={{ background: "#0C1120", border: `1px solid ${T.border}` }}>
      <div
        className="absolute top-3 right-3 text-xs font-mono px-2 py-0.5 rounded z-10"
        style={{ color: T.muted, background: "#1F2D40" }}
      >
        {lang}
      </div>
      <pre className="p-5 pr-20 text-sm overflow-x-auto leading-relaxed whitespace-pre"
        style={{ color: "#818CF8", fontFamily: "'JetBrains Mono', monospace" }}>
        {children}
      </pre>
    </div>
  );
}

// ─── Section heading ─────────────────────────────────────────────────────────

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2
      id={id}
      className="text-xl font-bold mt-12 mb-4 pl-4 scroll-mt-20"
      style={{ color: T.text, borderLeft: `2px solid ${T.primary}` }}
    >
      {children}
    </h2>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-base font-semibold mt-6 mb-2" style={{ color: T.text }}>
      {children}
    </h3>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-sm leading-relaxed mb-3" style={{ color: T.muted }}>
      {children}
    </p>
  );
}

// ─── Table ────────────────────────────────────────────────────────────────────

function Table({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto my-4 rounded-xl" style={{ border: `1px solid ${T.border}` }}>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr style={{ background: T.surface }}>
            {headers.map((h, i) => (
              <th key={i} className="text-left px-4 py-3 font-semibold"
                style={{ color: T.text, borderBottom: `1px solid ${T.border}` }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ borderBottom: i < rows.length - 1 ? `1px solid ${T.border}` : "none" }}>
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3 font-mono text-xs" style={{ color: T.muted }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Docs() {
  const [activeSection, setActiveSection] = useState("quick-start");
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id);
            break;
          }
        }
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
    );

    sections.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observerRef.current?.observe(el);
    });

    return () => observerRef.current?.disconnect();
  }, []);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="min-h-screen flex flex-col" style={{ background: T.bg, color: T.text, fontFamily: "Inter, sans-serif" }}>
      <TopNav />

      <div className="flex flex-1 max-w-6xl mx-auto w-full px-6 py-10 gap-10">

        {/* ── Sidebar ── */}
        <aside className="w-56 shrink-0">
          <div className="sticky top-20">
            <p className="text-xs font-semibold tracking-widest uppercase mb-4" style={{ color: T.muted }}>
              Documentation
            </p>
            <nav className="flex flex-col gap-0.5">
              {sections.map(({ id, label }) => (
                <button
                  key={id}
                  onClick={() => scrollTo(id)}
                  className="text-left text-sm px-3 py-2 rounded-lg transition-colors w-full"
                  style={{
                    color: activeSection === id ? T.text : T.muted,
                    background: activeSection === id ? "#6366F115" : "transparent",
                    fontWeight: activeSection === id ? 600 : 400,
                    borderLeft: activeSection === id ? `2px solid ${T.primary}` : "2px solid transparent",
                  }}
                >
                  {label}
                </button>
              ))}
            </nav>
          </div>
        </aside>

        {/* ── Content ── */}
        <main className="flex-1 min-w-0 pb-24">

          {/* Quick Start */}
          <SectionHeading id="quick-start">Quick Start</SectionHeading>
          <P>Add Archon to your project in under 2 minutes. No code changes to your application.</P>
          <Code lang="bash">{`# 1. Add to your docker-compose.yml
services:
  archon:
    image: archon:latest
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./backups:/app/backups
    ports:
      - "8765:8765"
    environment:
      ARCHON_API_KEY: your-secret-key`}</Code>
          <Code lang="bash">{`# 2. Create your config
cp config.yaml.example config.yaml

# 3. Start
docker compose up archon`}</Code>
          <P>Archon will connect to your databases, register scheduled jobs, and begin accepting API requests.</P>

          {/* Docker Setup */}
          <SectionHeading id="docker-setup">Docker Setup</SectionHeading>
          <P>
            Archon runs as a sidecar container alongside your application. It needs Docker network access to your database
            containers. The easiest approach is to use a shared Docker network or reference your database by its Docker
            service name.
          </P>
          <P>
            If your database runs on the host machine, use <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>host.docker.internal</code> as the hostname.
          </P>
          <Code lang="yaml">{`version: "3.9"

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: mydb
      POSTGRES_USER: \${DB_USER}
      POSTGRES_PASSWORD: \${DB_PASS}
    networks:
      - app-network

  your-app:
    image: your-app:latest
    depends_on: [postgres]
    networks:
      - app-network

  archon:
    image: archon:latest
    depends_on: [postgres]
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./backups:/app/backups
    ports:
      - "8765:8765"
    environment:
      ARCHON_API_KEY: \${ARCHON_API_KEY}
      DB_USER: \${DB_USER}
      DB_PASS: \${DB_PASS}
    networks:
      - app-network

networks:
  app-network:`}</Code>

          {/* config.yaml Reference */}
          <SectionHeading id="config-reference">config.yaml Reference</SectionHeading>
          <P>The entire Archon configuration lives in a single file. Environment variables are interpolated with <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>${`{VAR}`}</code> syntax.</P>
          <Code lang="yaml">{`# ── API ──────────────────────────────────────────────────────────
api:
  key: \${ARCHON_API_KEY}          # required  all endpoints need X-API-Key header

# ── Databases ────────────────────────────────────────────────────
databases:
  - name: primary_postgres        # unique identifier used in filenames
    type: postgres                # postgres | mongodb | mysql | sqlite
    host: postgres                # Docker service name or hostname
    port: 5432
    database: mydb
    username: \${DB_USER}
    password: \${DB_PASS}
    storage: local                # which storage backend to use
    schedule:
      frequency: daily            # hourly | daily | weekly | monthly
      at: "02:00"                 # time in 24h format
      timezone: UTC               # any IANA timezone
    retention:                    # optional  overrides global retention
      hourly: 24
      daily: 7
      weekly: 4
      monthly: 12

# ── Storage backends ─────────────────────────────────────────────
storage:
  local:
    type: local
    path: /app/backups

  s3:
    type: s3
    bucket: my-backup-bucket
    prefix: archon/
    region: us-east-1
    access_key: \${AWS_ACCESS_KEY}
    secret_key: \${AWS_SECRET_KEY}

  azure:
    type: azure
    container: backups
    connection_string: \${AZURE_CONN_STR}

# ── Encryption ───────────────────────────────────────────────────
encryption:
  enabled: true
  key: \${ENCRYPTION_KEY}          # 32-byte hex string

# ── Global retention ─────────────────────────────────────────────
retention:
  hourly: 24
  daily: 7
  weekly: 4
  monthly: 12

# ── Webhooks (optional) ──────────────────────────────────────────
webhooks:
  - url: https://hooks.example.com/archon
    secret: \${WEBHOOK_SECRET}
    events:
      - backup_completed
      - backup_failed
      - restore_completed
    max_attempts: 3
    backoff_seconds: 5`}</Code>

          {/* Database Providers */}
          <SectionHeading id="database-providers">Database Providers</SectionHeading>
          <P>Archon ships with built-in support for four database engines. All use the same config structure.</P>
          <Table
            headers={["Type", "config type value", "Tool used", "Restore strategy"]}
            rows={[
              ["PostgreSQL", "postgres", "pg_dump / pg_restore", "drop_recreate or shadow (near-zero downtime)"],
              ["MongoDB", "mongodb", "mongodump / mongorestore", "drop (--drop flag)"],
              ["MySQL", "mysql", "mysqldump / mysql", "drop_recreate"],
              ["SQLite", "sqlite", "sqlite3 hot-copy", "file replace"],
            ]}
          />
          <P>All providers call their respective CLI tools via subprocess. The tools must be present in the Archon container (they are pre-installed in the official image).</P>

          {/* Storage Backends */}
          <SectionHeading id="storage-backends">Storage Backends</SectionHeading>

          <SubHeading>Local filesystem</SubHeading>
          <Code lang="yaml">{`storage:
  local:
    type: local
    path: /app/backups      # path inside the container (mount a volume here)`}</Code>

          <SubHeading>AWS S3</SubHeading>
          <Code lang="yaml">{`storage:
  s3:
    type: s3
    bucket: my-backup-bucket
    prefix: archon/           # optional key prefix
    region: us-east-1
    access_key: \${AWS_ACCESS_KEY}
    secret_key: \${AWS_SECRET_KEY}`}</Code>

          <SubHeading>Azure Blob Storage</SubHeading>
          <Code lang="yaml">{`storage:
  azure:
    type: azure
    container: backups
    connection_string: \${AZURE_CONN_STR}`}</Code>
          <P>Each database in your config references a storage backend by name. You can mix backends  one database to S3, another to local.</P>

          {/* Encryption */}
          <SectionHeading id="encryption">Encryption</SectionHeading>
          <P>Archon uses AES-256-CBC encryption for all backup files when enabled. A SHA-256 checksum sidecar is always written regardless of encryption setting.</P>
          <Code lang="yaml">{`encryption:
  enabled: true
  key: \${ENCRYPTION_KEY}    # 32-byte hex string (64 hex characters)

  # Key rotation: add previous keys here
  previous_keys:
    - \${OLD_ENCRYPTION_KEY}`}</Code>

          <SubHeading>How it works</SubHeading>
          <P>When encryption is enabled, the backup pipeline is:</P>
          <Code lang="text">{`provider.backup() → encrypt() → compute_checksum() → storage.write(file) → storage.write(file.sha256) → retention.enforce()`}</Code>
          <P>On restore, checksum verification happens BEFORE decryption. If the <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>.sha256</code> sidecar is missing, the restore is aborted.</P>

          <SubHeading>Filename convention</SubHeading>
          <Code lang="text">{`archon_{db_name}_{timestamp}_{rotation_type}.{ext}[.enc]

Examples:
  archon_primary_postgres_2025-06-15T14-00-01_daily.sql.enc
  archon_primary_postgres_2025-06-15T14-00-01_daily.sql.enc.sha256
  archon_cache_sqlite_2025-06-01T00-00-00_monthly.db
  archon_cache_sqlite_2025-06-01T00-00-00_monthly.db.sha256`}</Code>

          {/* Scheduling */}
          <SectionHeading id="scheduling">Scheduling</SectionHeading>
          <P>Schedules can be declared with human-readable frequency or raw cron expressions.</P>
          <Code lang="yaml">{`# Human-readable
schedule:
  frequency: daily      # hourly | daily | weekly | monthly
  at: "02:00"           # time in 24h HH:MM format
  timezone: America/New_York

# Weekly  runs every Sunday at midnight
schedule:
  frequency: weekly
  at: "00:00"
  timezone: UTC

# Raw cron expression
schedule:
  cron: "0 2 * * *"
  timezone: UTC`}</Code>

          <SubHeading>Rotation tag overlap rule</SubHeading>
          <P>
            If a backup runs on Sunday AND it is the 1st of the month, it is tagged <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>monthly</code>, not <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>weekly</code>. Priority: monthly &gt; weekly &gt; daily &gt; hourly.
          </P>

          {/* Retention */}
          <SectionHeading id="retention">Retention</SectionHeading>
          <P>Retention rules control how many backups of each rotation type are kept. Older backups beyond the limit are deleted automatically after each backup run.</P>
          <Code lang="yaml">{`# Global retention (applies to all databases unless overridden)
retention:
  hourly: 24    # keep last 24 hourly backups
  daily: 7      # keep last 7 daily backups
  weekly: 4     # keep last 4 weekly backups
  monthly: 12   # keep last 12 monthly backups

# Per-database override
databases:
  - name: critical_db
    ...
    retention:
      daily: 30   # keep 30 daily for this DB specifically`}</Code>
          <P>When a backup is deleted by retention, its <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>.sha256</code> sidecar is deleted too.</P>

          {/* REST API Reference */}
          <SectionHeading id="api-reference">REST API Reference</SectionHeading>
          <P>All endpoints require the <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>X-API-Key</code> header. Missing or incorrect key returns <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>401</code>.</P>

          <Table
            headers={["Method", "Path", "Description"]}
            rows={[
              ["POST", "/backup", "Trigger an immediate backup for all or one database"],
              ["GET", "/jobs/{job_id}", "Get status and result of a backup job"],
              ["POST", "/restore", "Restore a database from a specific backup file"],
              ["GET", "/backups", "List all backup files with metadata"],
              ["GET", "/status", "Per-database scheduler and connection status"],
              ["DELETE", "/backups/{filename}", "Delete a backup file and its SHA-256 sidecar"],
              ["POST", "/reload", "Reload config.yaml without restarting the container"],
            ]}
          />

          <SubHeading>POST /backup</SubHeading>
          <Code lang="bash">{`curl -X POST http://localhost:8765/backup \\
  -H "X-API-Key: your-secret-key" \\
  -H "Content-Type: application/json"`}</Code>
          <Code lang="json">{`{
  "jobs": [
    {
      "job_id": "3f7a1d2e-...",
      "database": "primary_postgres",
      "status": "queued"
    }
  ]
}`}</Code>

          <SubHeading>GET /jobs/{"{job_id}"}</SubHeading>
          <Code lang="bash">{`curl http://localhost:8765/jobs/3f7a1d2e-... \\
  -H "X-API-Key: your-secret-key"`}</Code>
          <Code lang="json">{`{
  "job_id": "3f7a1d2e-...",
  "database": "primary_postgres",
  "status": "completed",
  "filename": "archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc",
  "started_at": "2025-01-15T14:00:00Z",
  "completed_at": "2025-01-15T14:00:02Z"
}`}</Code>

          <SubHeading>POST /restore</SubHeading>
          <Code lang="bash">{`curl -X POST http://localhost:8765/restore \\
  -H "X-API-Key: your-secret-key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "database": "primary_postgres",
    "filename": "archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc"
  }'`}</Code>
          <Code lang="json">{`{
  "status": "completed",
  "database": "primary_postgres",
  "filename": "archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc",
  "duration_seconds": 3.1
}`}</Code>

          <SubHeading>GET /backups</SubHeading>
          <Code lang="bash">{`curl http://localhost:8765/backups \\
  -H "X-API-Key: your-secret-key"`}</Code>
          <Code lang="json">{`{
  "backups": [
    {
      "filename": "archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc",
      "database": "primary_postgres",
      "rotation_type": "daily",
      "size_bytes": 524288,
      "created_at": "2025-01-15T14:00:02Z",
      "encrypted": true
    }
  ]
}`}</Code>

          <SubHeading>GET /status</SubHeading>
          <Code lang="bash">{`curl http://localhost:8765/status \\
  -H "X-API-Key: your-secret-key"`}</Code>
          <Code lang="json">{`{
  "databases": [
    {
      "name": "primary_postgres",
      "type": "postgres",
      "connected": true,
      "next_backup": "2025-01-16T02:00:00Z",
      "last_backup": "2025-01-15T02:00:02Z",
      "last_status": "completed"
    }
  ]
}`}</Code>

          <SubHeading>DELETE /backups/{"{filename}"}</SubHeading>
          <Code lang="bash">{`curl -X DELETE \\
  http://localhost:8765/backups/archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc \\
  -H "X-API-Key: your-secret-key"`}</Code>
          <Code lang="json">{`{
  "deleted": [
    "archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc",
    "archon_primary_postgres_2025-01-15T14-00-00_daily.sql.enc.sha256"
  ]
}`}</Code>

          <SubHeading>POST /reload</SubHeading>
          <Code lang="bash">{`curl -X POST http://localhost:8765/reload \\
  -H "X-API-Key: your-secret-key"`}</Code>
          <Code lang="json">{`{
  "status": "reloaded",
  "databases": 2,
  "jobs_registered": 2
}`}</Code>

          {/* Webhooks */}
          <SectionHeading id="webhooks">Webhooks</SectionHeading>
          <P>Archon sends HMAC-SHA256 signed HTTP POST requests to your webhook URLs when events occur.</P>
          <Code lang="yaml">{`webhooks:
  - url: https://hooks.example.com/archon
    secret: \${WEBHOOK_SECRET}
    events:
      - backup_completed
      - backup_failed
      - restore_completed
      - restore_failed
    max_attempts: 3
    backoff_seconds: 5`}</Code>

          <SubHeading>Signature verification</SubHeading>
          <P>Every request includes an <code className="text-xs px-1 py-0.5 rounded" style={{ background: "#1F2D40", color: "#818CF8" }}>X-Archon-Signature</code> header with the HMAC-SHA256 hex digest of the request body, signed with your webhook secret.</P>
          <Code lang="python">{`import hmac, hashlib

def verify_signature(body: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)`}</Code>

          <SubHeading>Event payload</SubHeading>
          <Code lang="json">{`{
  "event": "backup_completed",
  "timestamp": "2025-01-15T02:00:05Z",
  "database": "primary_postgres",
  "job_id": "3f7a1d2e-...",
  "backup_filename": "archon_primary_postgres_2025-01-15T02-00-00_daily.sql.enc",
  "duration_seconds": 2.4
}`}</Code>

          <SubHeading>Available events</SubHeading>
          <Table
            headers={["Event", "When fired"]}
            rows={[
              ["backup_completed", "Backup file and sidecar successfully written to storage"],
              ["backup_failed", "Backup job raised an exception"],
              ["restore_completed", "Database restore finished successfully"],
              ["restore_failed", "Restore raised an exception (includes integrity failures)"],
            ]}
          />

        </main>
      </div>

      {/* ── Footer ── */}
      <footer style={{ borderTop: `1px solid ${T.border}`, background: T.surface }}>
        <div className="max-w-6xl mx-auto px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
          <span style={{ color: T.muted }}>Archon v2.0</span>
          <div className="flex items-center gap-6">
            {[{ to: "/app", label: "Dashboard" }, { to: "/docs", label: "Docs" }, { to: "/about", label: "About" }].map(({ to, label }) => (
              <a key={to} href={to} className="transition-colors no-underline" style={{ color: T.muted }}
                onMouseEnter={e => ((e.currentTarget as HTMLElement).style.color = T.text)}
                onMouseLeave={e => ((e.currentTarget as HTMLElement).style.color = T.muted)}
              >
                {label}
              </a>
            ))}
          </div>
          <span className="italic" style={{ color: T.muted }}>Built for engineers who take data seriously.</span>
        </div>
      </footer>
    </div>
  );
}
