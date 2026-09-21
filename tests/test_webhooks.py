"""
Phase 12  Webhook Notification tests.

Tests cover:
  1. Event filtering  non-matching event does not fire
  2. Event filtering  all 4 subscribed events fire independently
  3. Successful delivery (200)  webhook_sent logged, no retries
  4. Retry on 500 then 200  webhook_sent logged after 2 attempts
  5. All retries exhausted (500 × max)  webhook_failed logged, no exception
  6. HMAC-SHA256 signature  X-Archon-Signature header is correct
  7. No secret  X-Archon-Signature header is absent
  8. Empty webhooks config  no HTTP calls made
"""
import asyncio
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import WebhookConfig, WebhookRetryConfig
from app.webhook import WebhookPayload, WebhookService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    url: str = "https://example.com/hook",
    events: list[str] | None = None,
    secret: str | None = None,
    max_attempts: int = 3,
    backoff_seconds: int = 0,   # 0 avoids real sleep in tests
    timeout_seconds: int = 10,
) -> WebhookConfig:
    return WebhookConfig(
        url=url,
        events=events or ["backup_completed"],
        secret=secret,
        timeout_seconds=timeout_seconds,
        retry=WebhookRetryConfig(
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        ),
    )


def _make_payload(event: str = "backup_completed") -> WebhookPayload:
    return WebhookPayload(
        event=event,
        timestamp="2025-06-15T14:00:00+00:00",
        database="primary_postgres",
        job_id="test-job-id",
        triggered_by="manual",
        backup_filename="raven_primary_postgres_2025-06-15T14-00-00_daily.sql",
        duration_seconds=1.23,
    )


def _make_mock_client(status_codes: list[int]) -> AsyncMock:
    """Build a mock httpx.AsyncClient whose .post() returns each status code in sequence."""
    responses = []
    for code in status_codes:
        r = MagicMock()
        r.status_code = code
        responses.append(r)
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------

class TestEventFiltering:
    @pytest.mark.asyncio
    async def test_non_matching_event_does_not_fire(self):
        """Webhook subscribed to backup_failed must NOT fire for backup_completed."""
        wh = _make_config(events=["backup_failed"])
        service = WebhookService([wh])
        payload = _make_payload("backup_completed")

        with patch.object(service, "_deliver", new_callable=AsyncMock) as mock_deliver:
            await service.fire("backup_completed", payload)
            await asyncio.sleep(0)  # flush pending tasks

        mock_deliver.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_four_events_fire_independently(self):
        """Webhook subscribed to all 4 events fires once per event."""
        all_events = [
            "backup_completed",
            "backup_failed",
            "restore_completed",
            "restore_failed",
        ]
        wh = _make_config(events=all_events)
        service = WebhookService([wh])

        with patch.object(service, "_deliver", new_callable=AsyncMock) as mock_deliver:
            for event in all_events:
                await service.fire(event, _make_payload(event))
                await asyncio.sleep(0)  # flush after each fire

        assert mock_deliver.call_count == 4


# ---------------------------------------------------------------------------
# Delivery  success
# ---------------------------------------------------------------------------

class TestDeliverySuccess:
    @pytest.mark.asyncio
    async def test_success_200_logs_webhook_sent(self):
        """HTTP 200 → webhook_sent logged, post called exactly once."""
        wh = _make_config()
        service = WebhookService([wh])
        payload = _make_payload()
        mock_client = _make_mock_client([200])

        with patch("app.webhook.httpx.AsyncClient", return_value=mock_client), \
             patch("app.webhook.log") as mock_log:
            await service._deliver(wh, payload, None)

        assert mock_client.post.call_count == 1
        logged_events = [c.args[0] for c in mock_log.info.call_args_list]
        assert "webhook_sent" in logged_events

    @pytest.mark.asyncio
    async def test_retry_500_then_200_logs_webhook_sent(self):
        """HTTP 500 first then 200 → webhook_sent after 2 attempts, no webhook_failed."""
        wh = _make_config(max_attempts=3)
        service = WebhookService([wh])
        payload = _make_payload()
        mock_client = _make_mock_client([500, 200])

        with patch("app.webhook.httpx.AsyncClient", return_value=mock_client), \
             patch("app.webhook.asyncio.sleep", new_callable=AsyncMock), \
             patch("app.webhook.log") as mock_log:
            await service._deliver(wh, payload, None)

        assert mock_client.post.call_count == 2
        logged_events = [c.args[0] for c in mock_log.info.call_args_list]
        assert "webhook_sent" in logged_events
        warning_events = [c.args[0] for c in mock_log.warning.call_args_list]
        assert "webhook_failed" not in warning_events


# ---------------------------------------------------------------------------
# Delivery  failure / exhaustion
# ---------------------------------------------------------------------------

class TestDeliveryFailure:
    @pytest.mark.asyncio
    async def test_all_retries_exhausted_logs_webhook_failed(self):
        """Always 500 → webhook_failed logged, no exception raised, no webhook_sent."""
        wh = _make_config(max_attempts=3)
        service = WebhookService([wh])
        payload = _make_payload()
        mock_client = _make_mock_client([500, 500, 500])

        with patch("app.webhook.httpx.AsyncClient", return_value=mock_client), \
             patch("app.webhook.asyncio.sleep", new_callable=AsyncMock), \
             patch("app.webhook.log") as mock_log:
            # Must not raise
            await service._deliver(wh, payload, None)

        assert mock_client.post.call_count == 3
        warning_events = [c.args[0] for c in mock_log.warning.call_args_list]
        assert "webhook_failed" in warning_events
        info_events = [c.args[0] for c in mock_log.info.call_args_list]
        assert "webhook_sent" not in info_events


# ---------------------------------------------------------------------------
# HMAC signatures
# ---------------------------------------------------------------------------

class TestHMACSignature:
    @pytest.mark.asyncio
    async def test_hmac_signature_header_is_correct(self):
        """X-Archon-Signature must equal sha256=<HMAC-SHA256(secret, json_bytes)>."""
        secret = "super_secret_key"
        wh = _make_config(secret=secret)
        service = WebhookService([wh])
        payload = _make_payload()

        json_bytes = payload.model_dump_json().encode()
        expected_sig = hmac.new(
            secret.encode(), json_bytes, hashlib.sha256
        ).hexdigest()

        captured_headers: dict[str, str] = {}

        async def _capture_post(url: str, content: bytes, headers: dict) -> MagicMock:
            captured_headers.update(headers)
            r = MagicMock()
            r.status_code = 200
            return r

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=_capture_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.webhook.httpx.AsyncClient", return_value=mock_client):
            await service._deliver(wh, payload, None)

        assert "X-Archon-Signature" in captured_headers
        assert captured_headers["X-Archon-Signature"] == f"sha256={expected_sig}"

    @pytest.mark.asyncio
    async def test_no_secret_no_signature_header(self):
        """Without a secret, X-Archon-Signature header must not appear in the request."""
        wh = _make_config(secret=None)
        service = WebhookService([wh])
        payload = _make_payload()

        captured_headers: dict[str, str] = {}

        async def _capture_post(url: str, content: bytes, headers: dict) -> MagicMock:
            captured_headers.update(headers)
            r = MagicMock()
            r.status_code = 200
            return r

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=_capture_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.webhook.httpx.AsyncClient", return_value=mock_client):
            await service._deliver(wh, payload, None)

        assert "X-Archon-Signature" not in captured_headers


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_webhooks_no_http_calls(self):
        """WebhookService with no configs fires no HTTP calls."""
        service = WebhookService([])
        payload = _make_payload()

        with patch("app.webhook.httpx.AsyncClient") as mock_cls:
            await service.fire("backup_completed", payload)
            await asyncio.sleep(0)  # flush  no tasks created
            mock_cls.assert_not_called()
