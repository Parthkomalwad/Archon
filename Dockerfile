FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    python3.11 \
    python3-pip \
    sqlite3 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# ── PostgreSQL client (version-matched via official PGDG apt repo) ────────────
# Ubuntu 22.04 ships postgresql-client 14 by default.
# Installing from the PGDG repo ensures pg_dump/pg_restore match the server
# version. postgresql-client-15 works with any Postgres 15.x server.
# To target Postgres 16, change 15 → 16 here and rebuild.
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] \
    https://apt.postgresql.org/pub/repos/apt jammy-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-15 \
 && rm -rf /var/lib/apt/lists/*

# ── MongoDB Database Tools ────────────────────────────────────────────────────
# Add MongoDB official apt repository (Ubuntu 22.04 / Jammy)
RUN curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg \
 && echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
    https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends mongodb-database-tools \
 && rm -rf /var/lib/apt/lists/*

# ── MySQL / MariaDB client tools ─────────────────────────────────────────────
# default-mysql-client provides mysqldump + mysql CLI compatible with MySQL 8.x
# and MariaDB servers (protocol-compatible).
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-mysql-client \
 && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY app/ app/

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 8765

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
