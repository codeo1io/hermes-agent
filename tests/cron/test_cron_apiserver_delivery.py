"""api_server cron delivery: transcript lane, not the send() stub.

Live failure (2026-09-07 01:34, job cd69dbd4c2b8): every api_server target
delivery errored with "API server uses HTTP request/response, not send()"
on BOTH the live-adapter and standalone lanes — a deliver=origin job
created from a WebUI session could never deliver. The fix routes
api_server targets through ``_deliver_to_api_server_transcript``: append a
user-role ``[Cron delivery: ...]`` message to the target session's
transcript (the same visibility model gateway/wake.py documents for this
platform), failing with a precise error when the session is gone.
"""

from __future__ import annotations

import pytest

from cron import scheduler


class _FakeSessionDB:
    """Minimal SessionDB double for the transcript-delivery helper."""

    def __init__(self, sessions, resolve=None, fail_on=None):
        self.sessions = sessions
        self.resolve = resolve or {}
        self.fail_on = fail_on or {}
        self.appended = []
        self.closed = False

    def get_session(self, session_id):
        if "lookup" in self.fail_on:
            raise RuntimeError(self.fail_on["lookup"])
        return self.sessions.get(session_id)

    def resolve_resume_session_id(self, session_id):
        return self.resolve.get(session_id, session_id)

    def append_message(self, **kwargs):
        if "append" in self.fail_on:
            raise RuntimeError(self.fail_on["append"])
        self.appended.append(kwargs)

    def close(self):
        self.closed = True


class TestDeliverToApiServerTranscript:
    def _job(self):
        return {"id": "j1", "name": "watchdog"}

    def test_appends_user_role_delivery_to_existing_session(self, monkeypatch):
        fake = _FakeSessionDB({"sess-1": {"id": "sess-1"}})
        monkeypatch.setattr(
            "hermes_state.SessionDB", lambda: fake, raising=True
        )
        err = scheduler._deliver_to_api_server_transcript(
            self._job(), "sess-1", "all good"
        )
        assert err is None
        assert len(fake.appended) == 1
        msg = fake.appended[0]
        assert msg["role"] == "user"
        assert msg["session_id"] == "sess-1"
        assert "[Cron delivery: watchdog]" in msg["content"]
        assert "all good" in msg["content"]
        assert fake.closed

    def test_missing_session_reports_precise_error(self, monkeypatch):
        fake = _FakeSessionDB({})
        monkeypatch.setattr("hermes_state.SessionDB", lambda: fake, raising=True)
        err = scheduler._deliver_to_api_server_transcript(
            self._job(), "gone-1", "payload"
        )
        assert err is not None
        assert "gone-1" in err
        assert "does not exist" in err
        assert fake.appended == []

    def test_rotated_session_resolves_to_live_tip(self, monkeypatch):
        # Origin points at a compression parent; the tip lives on.
        fake = _FakeSessionDB(
            {}, resolve={"parent-1": "child-9"}
        )
        monkeypatch.setattr("hermes_state.SessionDB", lambda: fake, raising=True)
        err = scheduler._deliver_to_api_server_transcript(
            self._job(), "parent-1", "payload"
        )
        assert err is None
        assert fake.appended[0]["session_id"] == "child-9"

    def test_empty_content_is_silent_success(self, monkeypatch):
        fake = _FakeSessionDB({"s": {"id": "s"}})
        monkeypatch.setattr("hermes_state.SessionDB", lambda: fake, raising=True)
        assert scheduler._deliver_to_api_server_transcript(
            self._job(), "s", "   "
        ) is None
        assert fake.appended == []

    def test_lookup_failure_returns_error_not_exception(self, monkeypatch):
        fake = _FakeSessionDB({}, fail_on={"lookup": "db locked"})
        monkeypatch.setattr("hermes_state.SessionDB", lambda: fake, raising=True)
        err = scheduler._deliver_to_api_server_transcript(
            self._job(), "s", "payload"
        )
        assert err is not None and "session lookup" in err


class TestDeliverResultApiServerBranch:
    def test_api_server_target_routes_to_transcript_lane(self, monkeypatch):
        """A deliver=origin job on an api_server origin delivers via the
        transcript append and never touches the send() stub."""
        calls = []

        def fake_transcript(job, chat_id, content):
            calls.append((job.get("id"), chat_id, content))
            return None

        monkeypatch.setattr(
            scheduler, "_deliver_to_api_server_transcript", fake_transcript
        )

        job = {
            "id": "cd69dbd4c2b8",
            "name": "watchdog",
            "deliver": "origin",
            "origin": {
                "platform": "api_server",
                "chat_id": "6f377642a7f0",
                "thread_id": None,
                "user_id": None,
                "scope_id": None,
                "chat_type": None,
            },
        }
        # _resolve_single_delivery_target consults gateway config; avoid the
        # dependency by passing the resolved target through the token path.
        # Directly exercise the branch instead: build the same shape the
        # resolver returns for an origin-matching target.
        from gateway.config import load_gateway_config

        # _deliver_result signature: (job, content, adapters, loop)
        err = scheduler._deliver_result(
            job, "watch output", adapters=None, loop=None
        )
        # With a live gateway config present the origin target resolves; the
        # transcript lane either delivered (err is None) or the config-less
        # environment reports a resolvable-target error — but NEVER the dead
        # send() stub message.
        assert err is None or "not send()" not in err
        assert calls, "api_server origin target must route to transcript lane"


class TestPreflightAllowsApiServer:
    """api_server is a known, credential-free delivery platform."""

    def test_explicit_apiserver_target_passes_preflight(self):
        from cron.scheduler import _preflight_check_delivery

        assert _preflight_check_delivery(
            {"id": "t", "deliver": "api_server:6f377642a7f0"}
        ) is None

    def test_apiserver_origin_target_passes_preflight(self):
        from cron.scheduler import _preflight_check_delivery

        assert _preflight_check_delivery(
            {
                "id": "t",
                "deliver": "origin",
                "origin": {"platform": "api_server", "chat_id": "x"},
            }
        ) is None

    def test_unknown_platform_still_blocked(self):
        from cron.scheduler import _preflight_check_delivery

        err = _preflight_check_delivery({"id": "t", "deliver": "nope:1"})
        assert err is not None and "not a known cron delivery target" in err


class TestWakeSelfPostBoundedLeaseWait:
    def test_wake_header_present(self):
        import inspect

        from gateway import wake

        src = inspect.getsource(wake._self_post_chat_completion)
        assert "X-Hermes-Lease-Wait-Seconds" in src
        assert "session_turn_lease_busy" in src
