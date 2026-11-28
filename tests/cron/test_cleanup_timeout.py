"""Regression tests for bounded cron post-run cleanup.

A cron worker must release its in-memory dispatch guard even when SQLite or an
agent resource finalizer stops returning after the model turn has ended.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cron.scheduler import _teardown_cron_agent, run_job
from cron.scheduler_detached_worker import defer_teardown_to_running_worker


_RUNTIME = {
    "api_key": "test-key",
    "base_url": "https://example.invalid/v1",
    "provider": "openrouter",
    "api_mode": "chat_completions",
}


@contextmanager
def _owner_execution(db, job, execution_id=None):
    from gateway import session_cron
    from persistence_assembly import profile_scope
    owner = SimpleNamespace(db=db, persistence=MagicMock(scope=profile_scope(home=db.db_path.parent)))
    token = session_cron._execution.set((owner, "cleanup-session", job["id"], execution_id))
    try:
        yield
    finally:
        session_cron._execution.reset(token)


class HangingStore:
    """A storage interface handle whose lineage read hangs."""

    def __init__(self, release: threading.Event):
        self.release = release
        self.entered = threading.Event()
        self.sessions = self.lineage = self

    def tip(self, _session_id):
        self.entered.set()
        self.release.wait()

    def end(self, *_args, **_kwargs):
        return None

    def close(self):
        return None


class HangingAgent:
    def __init__(self, release: threading.Event):
        self.release = release
        self.entered = threading.Event()

    def close(self):
        self.entered.set()
        self.release.wait()


def test_run_job_bounds_sessiondb_finalization(tmp_path):
    release = threading.Event()
    fake_db = HangingStore(release)
    fake_db.db_path = tmp_path / "state.db"
    job = {"id": "cleanup-sessiondb-hang", "name": "test", "prompt": "hello"}

    try:
        with _owner_execution(fake_db, job), \
             patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("persistence_assembly.open_persistence", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls, \
             patch("cron.scheduler._cron_cleanup_timeout_seconds", return_value=0.02):
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            started = time.monotonic()
            success, _output, final_response, error = run_job(job)
            elapsed = time.monotonic() - started

        assert fake_db.entered.wait(timeout=2.0)
        assert elapsed < 5.0
        assert success is True
        assert final_response == "ok"
        assert error is None
    finally:
        release.set()


def test_agent_teardown_is_bounded():
    release = threading.Event()
    agent = HangingAgent(release)

    try:
        started = time.monotonic()
        _teardown_cron_agent(agent, "cleanup-agent-hang", timeout_seconds=0.02)
        elapsed = time.monotonic() - started

        assert agent.entered.wait(timeout=2.0)
        assert elapsed < 5.0
    finally:
        release.set()


def test_detached_worker_teardown_waits_for_future():
    """A timed-out worker keeps its agent and store until its Future completes."""
    future = Future()
    fake_db = MagicMock()
    agent = MagicMock()

    with patch("cron.scheduler._finalize_cron_session") as finalize, \
         patch("cron.scheduler._teardown_cron_agent") as teardown_agent:
        assert defer_teardown_to_running_worker(
            future, fake_db, agent, "detached-worker", "detached worker", "cron_detached-worker") is True
        finalize.assert_not_called()
        teardown_agent.assert_not_called()

        future.set_result({"final_response": "late"})

        finalize.assert_called_once_with(fake_db, agent, "detached-worker", "detached worker",
                                         "cron_detached-worker", workdir=None)
        teardown_agent.assert_called_once_with(agent, "detached-worker")
    assert defer_teardown_to_running_worker(
        future, fake_db, agent, "detached-worker", "detached worker", "cron_detached-worker") is False


def test_dispatch_guard_releases_after_sessiondb_finalization_hang(tmp_path):
    """A second scheduler tick can fire the same job after cleanup times out."""
    import cron.scheduler as sched

    release = threading.Event()
    fake_db = HangingStore(release)
    fake_db.db_path = tmp_path / "state.db"
    job = {
        "id": "cleanup-guard-hang",
        "name": "cleanup-guard-hang",
        "prompt": "hello",
        "schedule": "every 5m",
        "enabled": True,
        "next_run_at": "2020-01-01T00:00:00",
        "deliver": "local",
    }
    from cron import jobs

    def admitted(fired, **kwargs):
        with _owner_execution(fake_db, fired, kwargs.get("execution_id")):
            return run_job(fired, **kwargs)

    sched._parallel_pools.clear()
    sched._parallel_pool_max_workers.clear()
    sched._running_job_ids.clear()

    try:
        with jobs.use_cron_store(tmp_path), \
             patch("cron.scheduler_authority.run_canonical_job", side_effect=admitted), \
             patch("cron.scheduler_authority.reconcile_pending"), \
             patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("persistence_assembly.open_persistence", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls, \
             patch("cron.scheduler._cron_cleanup_timeout_seconds", return_value=0.02), \
             patch.object(sched, "get_due_jobs", return_value=[job]), \
             patch.object(sched, "claim_job_for_fire", return_value=True), \
             patch.object(sched, "save_job_output", return_value="/tmp/out"), \
             patch.object(sched, "mark_job_run"), \
             patch.object(sched, "_deliver_result", return_value=None):
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            assert sched.tick(verbose=False) == 1
            assert fake_db.entered.is_set()
            assert mock_agent.run_conversation.call_count == 1
            assert "cleanup-guard-hang" not in sched.get_running_job_ids()
            assert sched.tick(verbose=False) == 1
            assert mock_agent.run_conversation.call_count == 2
    finally:
        release.set()
        sched._running_job_ids.discard(sched._inflight_key("cleanup-guard-hang"))
        sched._shutdown_parallel_pool()


class _LatchingTitleStore:
    """Reproduces the 2026-11-28 07:27Z production death (item 508).

    The real ``_BoundedCronSessionDB`` proxy latches ``disabled`` after the first
    cleanup timeout; every later proxied call then raises RuntimeError immediately
    (``session finalization disabled after prior cleanup failure``). The production
    store additionally exposes ``next_title_in_lineage`` — and the title-recovery
    block in ``_finalize_cron_session`` evaluated
    ``getattr(_sessions, "next_title_in_lineage", ...)(...)`` OUTSIDE its try, so the
    latched call escaped the handler, escaped the finally block, and booked a
    completed 2h run as ``failed`` with a 0-byte output document.
    """

    def __init__(self):
        self._title_calls = 0
        self.latched = False
        self.lineage = self  # expose lineage.tip

    def tip(self, _session_id):
        return None  # no compression rotation

    def set_title(self, session_id, title):
        self._title_calls += 1
        if self.latched:
            raise RuntimeError("session finalization disabled after prior cleanup failure")
        # First write hangs: drives the first title write past the cleanup timeout.
        self.latched = True
        raise TimeoutError("simulated first title write exceeding cleanup patience")

    def next_title_in_lineage(self, base):
        # Bounded proxy call AFTER the latch: raises RuntimeError immediately.
        raise RuntimeError("session finalization disabled after prior cleanup failure")

    def end(self, *_a, **_k):
        self.ended = True

    def close(self):
        self.closed = True

    def sessions(self):  # pragma: no cover - attribute access path
        return self


def test_title_fallback_latch_never_escapes_finalization(tmp_path):
    """A latched bounded-proxy must never fail the whole run (item 508)."""
    from cron.scheduler import _finalize_cron_session

    store = _LatchingTitleStore()
    db_state = {"closed": False}
    fake_db = SimpleNamespace(
        sessions=store, lineage=store, db_path=tmp_path / "state.db",
        close=lambda: db_state.__setitem__("closed", True))

    # Patch the cleanup timeout down so the first hanging write times out quickly.
    with patch("cron.scheduler._cron_cleanup_timeout_seconds", return_value=0.05):
        # Must NOT raise: the title fallback runs INSIDE the guard now.
        _finalize_cron_session(fake_db, None, "item508-title-latch", "item508 job",
                               "cron_item508-title-latch", workdir=None)

    # The store still got its end()/close() calls: finalization continued past the
    # latched title failure instead of dying on the escaping RuntimeError.
    assert store.ended is True
    assert db_state["closed"] is True
