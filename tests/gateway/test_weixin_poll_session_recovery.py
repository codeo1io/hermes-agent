"""Weixin session-expiry and rate-limit failures must escalate with their real detail (cycle-3 W17).

Two halves of one bug class — an invisible failure:
* the poll loop's session-expired branch logged once and slept 10 minutes between
  retries forever, with the same dead token: a zombie that never surfaces in
  runtime status and never picks up a re-paired account. Persistent expiry now
  escalates to a retryable fatal error carrying ret/errcode/errmsg, routing
  through the gateway's reconnect queue (``connect()`` re-reads the persisted
  account, so a re-paired token takes over) instead of retrying the same token
  indefinitely.
* the send-chunk fail-fast raise lost WHY the cooldown opened: a loop re-entry
  (or a follow-up send) raised "rate limited; cooldown active for Xs" while the
  first-hit log kept ret/errcode/errmsg — the raised error must retain them.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gateway.config import PlatformConfig
from gateway.platforms import weixin
from gateway.platforms.weixin import WeixinAdapter


def _make_adapter() -> WeixinAdapter:
    return WeixinAdapter(
        PlatformConfig(enabled=True, token="test-token", extra={"account_id": "test-account"}),
    )


def _connected_adapter() -> WeixinAdapter:
    adapter = _make_adapter()
    adapter._session = object()
    adapter._send_session = adapter._session
    adapter._token = "test-token"
    adapter._base_url = "https://weixin.example.com"
    adapter._token_store.get = lambda account_id, chat_id: None
    return adapter


def _expired_response() -> dict:
    return {
        "ret": weixin.SESSION_EXPIRED_ERRCODE,
        "errcode": weixin.SESSION_EXPIRED_ERRCODE,
        "errmsg": "session expired",
        "get_updates_buf": "buf-1",
    }


class TestPollSessionExpiryEscalation:
    def _run(self, responses):
        adapter = _make_adapter()
        adapter._running = True
        adapter._poll_session = Mock()
        notified = []
        adapter.set_fatal_error_handler(lambda a: notified.append(a.fatal_error_code))
        it = iter(responses)

        async def _get_updates(*args, **kwargs):
            try:
                return next(it)
            except StopIteration:
                # Safety stop for the unfixed path: bounded polls, no hang.
                adapter._running = False
                return {"ret": 0, "msgs": []}

        async def scenario():
            with patch("gateway.platforms.weixin.asyncio.sleep", new_callable=AsyncMock):
                await adapter._poll_loop()

        with (
            patch("gateway.platforms.weixin._get_updates", _get_updates),
            patch("gateway.platforms.weixin._load_sync_buf", lambda *a: "buf-0"),
            patch("gateway.platforms.weixin._save_sync_buf", lambda *a, **k: None),
        ):
            asyncio.run(scenario())
        return adapter, notified

    def test_persistent_expiry_escalates_to_retryable_fatal_with_detail(self):
        adapter, notified = self._run([_expired_response() for _ in range(8)])

        assert adapter.fatal_error_code == "weixin_session_expired"
        assert adapter.fatal_error_retryable is True
        message = adapter.fatal_error_message or ""
        assert "session expired" in message  # errmsg survives
        assert str(weixin.SESSION_EXPIRED_ERRCODE) in message  # ret/errcode detail survives
        assert notified == ["weixin_session_expired"]

    def test_transient_expiry_blip_recovers_without_fatal(self):
        # Alternating expired/healthy polls: each expiry is followed by recovery,
        # so the streak never reaches the escalation threshold.
        responses = [_expired_response(), {"ret": 0, "msgs": [], "get_updates_buf": "buf-1"}] * 6
        adapter, notified = self._run(responses)

        assert adapter.fatal_error_code is None
        assert notified == []


class TestCooldownFailFastDetail:
    @patch("gateway.platforms.weixin.asyncio.sleep", new_callable=AsyncMock)
    @patch("gateway.platforms.weixin._send_message", new_callable=AsyncMock)
    def test_fail_fast_raise_keeps_triggering_failure_detail(self, send_message_mock, sleep_mock):
        adapter = _connected_adapter()
        adapter._send_chunk_retries = 3
        adapter._send_chunk_retry_delay_seconds = 0
        adapter._rate_limit_circuit_threshold = 1
        adapter._rate_limit_circuit_window_seconds = 60
        adapter._rate_limit_circuit_open_seconds = 60

        send_message_mock.return_value = {
            "ret": weixin.RATE_LIMIT_ERRCODE,
            "errcode": weixin.RATE_LIMIT_ERRCODE,
            "errmsg": "frequency limit",
        }

        first = asyncio.run(adapter.send("wxid_test123", "first"))
        second = asyncio.run(adapter.send("wxid_test123", "second"))

        assert first.success is False
        assert second.success is False
        # The follow-up send never hits the wire (fail-fast) ...
        assert send_message_mock.await_count == 1
        # ... and its error still names WHY the cooldown opened.
        assert "cooldown" in (second.error or "")
        assert "frequency limit" in (second.error or "")
        assert str(weixin.RATE_LIMIT_ERRCODE) in (second.error or "")
