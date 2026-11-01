"""Transient SQLite contention must not abandon an already admitted cron execution."""
import sqlite3

import pytest

from cron import scheduler_authority


@pytest.mark.asyncio
async def test_status_poll_retries_same_receipt_without_resubmitting(monkeypatch):
    sleeps = []
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    receipt = {"session_id": "same-session", "admission_id": "same-admission"}
    calls = []
    async def call(op, params):
        calls.append((op, dict(params)))
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return {"status": "terminal", "result": [True, "", "done", None]}
    state = await scheduler_authority._read_owner_with_lock_retry(call, "status", receipt)
    assert state["status"] == "terminal"
    assert calls == [("status", receipt)] * 3
    assert sleeps == list(scheduler_authority._LOCK_RETRY_DELAYS[:2])


@pytest.mark.asyncio
async def test_recover_poll_retry_preserves_exact_identity(monkeypatch):
    async def sleep(_):
        return None
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    params = {"job_id": "j", "request_id": "execution-id", "extra_prompt": None}
    calls = []
    async def call(op, p):
        calls.append((op, dict(p)))
        if len(calls) == 1:
            raise RuntimeError("owner RPC: database is locked")
        return {"status": "started", "session_id": "s", "admission_id": "a"}
    result = await scheduler_authority._read_owner_with_lock_retry(call, "recover", params)
    assert result["status"] == "started"
    assert calls == [("recover", params)] * 2


@pytest.mark.asyncio
async def test_non_lock_errors_and_submit_never_retried(monkeypatch):
    async def no_sleep(_):
        pytest.fail("unexpected retry")
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", no_sleep)
    for op, error in (("status", RuntimeError("permission_denied")),
                      ("submit", sqlite3.OperationalError("database is locked"))):
        calls = []
        async def call(name, params):
            calls.append(name)
            raise error
        with pytest.raises(type(error), match=str(error)):
            await scheduler_authority._read_owner_with_lock_retry(call, op, {})
        assert calls == [op]


@pytest.mark.asyncio
async def test_persistent_lock_exhausts_bounded_retries(monkeypatch):
    sleeps = []
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    calls = []
    async def call(op, params):
        calls.append(op)
        raise sqlite3.OperationalError("database is locked")
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        await scheduler_authority._read_owner_with_lock_retry(call, "status", {"admission_id": "a"})
    assert len(calls) == len(scheduler_authority._LOCK_RETRY_DELAYS) + 1
    assert sleeps == list(scheduler_authority._LOCK_RETRY_DELAYS)


def test_canonical_firer_reuses_single_admission_after_status_lock(tmp_path, monkeypatch):
    """The production firer must not re-submit when its admitted status read locks."""
    from contextlib import asynccontextmanager
    import json
    from gateway import session_cron
    from hermes_cli import gateway_client
    import hermes_constants

    monkeypatch.setattr(session_cron, "owner_for_home", lambda home: None)
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    calls = []

    class Peer:
        async def rpc(self, method, **params):
            calls.append(method)
            if method == "cron.submit":
                return {"session_id": "session-1", "admission_id": "admission-1"}
            assert method == "cron.status"
            assert params == {"session_id": "session-1", "admission_id": "admission-1"}
            if calls.count("cron.status") == 1:
                raise sqlite3.OperationalError("database is locked")
            return {"status": "terminal", "result": [True, "output", "answer", None]}

    @asynccontextmanager
    async def connected():
        yield Peer()

    monkeypatch.setattr(gateway_client, "connect_gateway", connected)
    result = scheduler_authority.run_canonical_job(
        {"id": "job-1", "execution_id": "execution-1"}, execution_id="execution-1"
    )
    assert result == (True, "output", "answer", None)
    assert calls == ["cron.submit", "cron.status", "cron.status"]
    journal = scheduler_authority.journal_path("job-1", "execution-1")
    assert json.loads(journal.read_text())["receipt"] == {
        "session_id": "session-1", "admission_id": "admission-1"
    }
