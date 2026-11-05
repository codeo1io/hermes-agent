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


# ---------------------------------------------------------------------------
# The transport lane: every external firer (cron-fired worker process,
# `hermes cron run`, non-headless reconcile) talks to the owner over the
# gateway, where a busy writer arrives as JSON-RPC 5001 'storage_unavailable'
# re-wrapped into GatewayRPCError — NOT as a raw 'database is locked' string.


def test_shared_transient_predicate_shapes():
    """One predicate for every transient-lock shape the firer lanes see."""
    from hermes_cli.gateway_client import GatewayRPCError

    busy = sqlite3.OperationalError("some busy text")
    busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
    locked = sqlite3.OperationalError("some locked text")
    locked.sqlite_errorcode = sqlite3.SQLITE_LOCKED
    shapes_transient = [
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("driver error: database table is locked"),
        busy,
        locked,
        GatewayRPCError("storage_unavailable", 5001, {}),
        RuntimeError("owner RPC: storage_unavailable"),
    ]
    shapes_permanent = [
        RuntimeError("permission_denied"),
        sqlite3.OperationalError("unable to open database file"),
        sqlite3.OperationalError("attempt to write a readonly database"),
        ValueError("something else entirely"),
    ]
    for exc in shapes_transient:
        assert scheduler_authority._is_transient_sqlite_lock(exc), f"{exc!r} must be transient"
    for exc in shapes_permanent:
        assert not scheduler_authority._is_transient_sqlite_lock(exc), f"{exc!r} must be permanent"


@pytest.mark.asyncio
async def test_transport_storage_unavailable_is_retried(monkeypatch):
    """GatewayRPCError('storage_unavailable') is the transport form of a busy
    writer: the same-identity poll must retry it, not abandon the fire."""
    async def sleep(_):
        return None
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    from hermes_cli.gateway_client import GatewayRPCError

    receipt = {"session_id": "s", "admission_id": "a"}
    calls = []

    async def call(op, params):
        calls.append(op)
        if len(calls) == 1:
            raise GatewayRPCError("storage_unavailable", 5001, {})
        return {"status": "terminal", "result": [True, "out", "ans", None]}

    state = await scheduler_authority._read_owner_with_lock_retry(call, "status", receipt)
    assert state["status"] == "terminal"
    assert calls == ["status", "status"]


@pytest.mark.asyncio
async def test_cancel_op_rides_the_same_retry_fence(monkeypatch):
    """The poll-loop cancel is same-identity too: a transient lock while
    cancelling must retry the SAME receipt instead of raising out of the fire
    (which books the whole execution as unknown)."""
    async def sleep(_):
        return None
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    receipt = {"session_id": "s", "admission_id": "a"}
    calls = []

    async def call(op, params):
        calls.append((op, dict(params)))
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"cancelled": True}

    result = await scheduler_authority._read_owner_with_lock_retry(call, "cancel", receipt)
    assert result == {"cancelled": True}
    assert calls == [("cancel", receipt)] * 2


def test_reconcile_recover_poll_retries_transport_busy(tmp_path, monkeypatch):
    """reconcile_pending's recover poll must survive one transport-layer busy:
    on base the storage_unavailable raises, the journal is scan-counted, and
    recovery defers (the #555 receipt_expired budget burn); with the shared
    predicate it resolves on the retry."""
    import asyncio
    import json
    import threading
    from contextlib import nullcontext

    from cron import executions as cron_executions
    from cron import scheduler, scheduler_bookkeeping
    from gateway import session_cron
    from hermes_cli.gateway_client import GatewayRPCError
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    admissions = tmp_path / "cron" / "admissions"
    admissions.mkdir(parents=True)
    params = {"job_id": "job-1", "request_id": "exec-1", "extra_prompt": None}
    journal = scheduler_authority.journal_path("job-1", "exec-1")
    journal.write_text(json.dumps({"params": params, "receipt": None}))

    monkeypatch.setattr(cron_executions, "execution_owner_live", lambda *a, **k: False)
    monkeypatch.setattr(cron_executions, "get_execution", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_apply_agent_failure_marker",
                        lambda job, s, e, a: (s, e, False))
    monkeypatch.setattr(scheduler, "_RunDelivery", lambda *a, **k: object())
    monkeypatch.setattr(scheduler, "_fire_secret_scope", nullcontext)
    monkeypatch.setattr(scheduler, "_save_compose_deliver", lambda *a, **k: None)
    monkeypatch.setattr(scheduler_bookkeeping, "fail_empty_response", lambda *a, **k: None)
    finished = []
    monkeypatch.setattr(scheduler_bookkeeping, "finish_completed_run",
                        lambda *a, **k: finished.append(a) or True)

    async def sleep(_):
        return None
    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)

    calls = []

    async def operation(authority, op, data):
        calls.append(op)
        if len(calls) == 1:
            raise GatewayRPCError("storage_unavailable", 5001, {})
        return {"status": "terminal", "result": [True, "out", "ans", None],
                "job": {"id": "job-1"}}

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    try:
        monkeypatch.setattr(session_cron, "owner_for_home", lambda home: (object(), loop))
        scheduler_authority.reconcile_pending(allow_connect=True)
    finally:
        loop.call_soon_threadsafe(loop.stop)

    assert calls == ["recover", "recover"], "recover must retry the transport busy"
    assert finished, "the journal must resolve terminal, not defer with a scan count"
    record = json.loads(journal.read_text(encoding="utf-8-sig"))
    assert int(record.get("recovery_scans") or 0) == 0
