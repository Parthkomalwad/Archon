"""
Webhook notification service.

Fires HTTP POST callbacks on backup/restore events with optional HMAC-SHA256 signing
and linear-backoff retry. All delivery happens in background asyncio tasks so the
backup/restore pipeline is never blocked.

When a DB pool is provided, every delivery attempt is persisted to `webhook_deliveries`
so in-flight webhooks survive container restarts and are replayed on startup.
.- .-..
"""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.config import WebhookConfig
from app.logger import log


# ---------------------------------------------------------------------------
# Payload model
# ---------------------------------------------------------------------------

class WebhookPayload(BaseModel):
    event: str
    timestamp: str                      # UTC ISO 8601
    database: str
    job_id: Optional[str] = None
    triggered_by: Optional[str] = None
    backup_filename: Optional[str] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class WebhookService:
    """
    Dispatches webhook notifications for configured endpoints.

    fire() is non-blocking  it creates background asyncio.Tasks for each
    matching webhook and returns immediately. Delivery failures are logged
    but never raised to the caller.

    When a DB pool is injected via set_pool(), every delivery is tracked in
    the `webhook_deliveries` table so pending webhooks survive restarts.
    Call replay_pending() once at startup to retry any that were left pending.
    """

    def __init__(self, webhook_configs: list[WebhookConfig]) -> None:
        self._configs = webhook_configs
        self._pool = None  # injected after DB init

    def set_pool(self, pool) -> None:
        """Called once from main.py after init_db() succeeds."""
        self._pool = pool

    async def fire(self, event: str, payload: WebhookPayload) -> None:
        """
        For each webhook whose events list includes `event`, schedule a
        background delivery task. Returns immediately without waiting.
        """
        matching = [wh for wh in self._configs if event in wh.events]
        for wh in matching:
            delivery_id = await self._create_delivery_record(wh.url, event, payload)
            asyncio.create_task(self._deliver(wh, payload, delivery_id))

    async def replay_pending(self) -> None:
        """
        Called once at startup. Retries any deliveries left in 'pending' or
        'retrying' state from a previous run. No-op if no DB pool is set.
        """
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM webhook_deliveries WHERE status IN ('pending', 'retrying')"
            )
        if not rows:
            return
        log.info("startup_ok", f"Replaying {len(rows)} pending webhook delivery(ies)")
        for row in rows:
            # Find the matching config by URL
            wh = next((c for c in self._configs if c.url == row["webhook_url"]), None)
            if wh is None:
                # URL no longer in config  mark failed
                await self._update_delivery(row["id"], "failed", "URL no longer in config")
                continue
            payload_dict = dict(row["payload"])
            try:
                payload = WebhookPayload(**payload_dict)
            except Exception:
                await self._update_delivery(row["id"], "failed", "Invalid payload in DB")
                continue
            asyncio.create_task(self._deliver(wh, payload, row["id"]))

    # ------------------------------------------------------------------
    # Internal  DB helpers
    # ------------------------------------------------------------------

    async def _create_delivery_record(
        self, url: str, event: str, payload: WebhookPayload
    ) -> Optional[UUID]:
        """Insert a new 'pending' row and return its UUID, or None if no pool."""
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO webhook_deliveries
                        (webhook_url, event_type, payload, status)
                    VALUES ($1, $2, $3::jsonb, 'pending')
                    RETURNING id
                    """,
                    url,
                    event,
                    payload.model_dump_json(),
                )
            return row["id"]
        except Exception as e:
            log.warning("webhook_failed", f"Could not persist webhook delivery record: {e}")
            return None

    async def _update_delivery(
        self,
        delivery_id: Optional[UUID],
        status: str,
        error: Optional[str] = None,
        delivered_at: Optional[datetime] = None,
    ) -> None:
        """Update delivery status in DB. No-op if delivery_id is None."""
        if not self._pool or delivery_id is None:
            return
        now = datetime.now(timezone.utc)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE webhook_deliveries
                       SET status            = $1,
                           error_message     = $2,
                           last_attempted_at = $3,
                           delivered_at      = $4,
                           attempts          = attempts + 1
                     WHERE id = $5
                    """,
                    status,
                    error,
                    now,
                    delivered_at,
                    delivery_id,
                )
        except Exception:
            pass  # never let DB write break webhook logic

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def _deliver(
        self,
        config: WebhookConfig,
        payload: WebhookPayload,
        delivery_id: Optional[UUID],
    ) -> None:
        """
        Attempt to POST `payload` to `config.url` with linear-backoff retry.

        Delivery order:
          1. Serialise payload to JSON bytes.
          2. Build headers (Content-Type, X-Archon-Event, optional X-Archon-Signature).
          3. Attempt up to max_attempts times; wait backoff_seconds * attempt between tries.
          4. On 2xx: log webhook_sent, mark delivered in DB, and return.
          5. After all attempts exhausted: log webhook_failed, mark failed in DB.
        """
        json_bytes = payload.model_dump_json().encode()

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Archon-Event": payload.event,
        }
        if config.secret:
            sig = hmac.new(
                config.secret.encode(), json_bytes, hashlib.sha256
            ).hexdigest()
            headers["X-Archon-Signature"] = f"sha256={sig}"

        last_error: Optional[str] = None
        last_status: Optional[int] = None

        # Mark as retrying before first attempt
        await self._update_delivery(delivery_id, "retrying")

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                for attempt in range(1, config.retry.max_attempts + 1):
                    try:
                        resp = await client.post(
                            config.url, content=json_bytes, headers=headers
                        )
                        if 200 <= resp.status_code < 300:
                            log.info(
                                "webhook_sent",
                                f"Webhook delivered to {config.url}",
                                database=payload.database,
                                webhook_event=payload.event,
                                status_code=resp.status_code,
                                attempt=attempt,
                            )
                            await self._update_delivery(
                                delivery_id,
                                "delivered",
                                delivered_at=datetime.now(timezone.utc),
                            )
                            return
                        last_status = resp.status_code
                        last_error = f"HTTP {resp.status_code}"
                    except httpx.TimeoutException as exc:
                        last_error = f"Timeout: {exc}"
                    except Exception as exc:
                        last_error = str(exc)

                    if attempt < config.retry.max_attempts:
                        await asyncio.sleep(config.retry.backoff_seconds * attempt)

        except Exception as exc:
            last_error = str(exc)

        log.warning(
            "webhook_failed",
            f"Webhook delivery failed after {config.retry.max_attempts} attempt(s): {config.url}",
            database=payload.database,
            webhook_event=payload.event,
            url=config.url,
            attempts=config.retry.max_attempts,
            error=last_error,
            status_code=last_status,
        )
        await self._update_delivery(delivery_id, "failed", error=last_error)
