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


@pytest.mark.asyncio
async def test_storage_unavailable_transport_shape_is_retried(monkeypatch):
    """The external-worker lane's actual lock shape: the owner's busy SQLite writer
    crosses the wire as JSON-RPC 5001 'storage_unavailable' (gateway/session_controls
    wraps sqlite3.Error) re-raised by gateway_client as GatewayRPCError whose str is
    the bounded reason -- never the raw 'database is locked' text a raw sqlite poll
    sees. Regression for the transport lane whose first busy poll raised straight
    through to CronExecutionUnknown."""
    from hermes_cli.gateway_client import GatewayRPCError

    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    calls = []

    async def call(op, params):
        calls.append(op)
        if len(calls) < 2:
            raise GatewayRPCError("storage_unavailable", 5001)
        return {"status": "terminal", "result": [True, "", "done", None]}

    state = await scheduler_authority._read_owner_with_lock_retry(
        call, "status", {"admission_id": "a"})
    assert state["status"] == "terminal"
    assert calls == ["status", "status"]
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_cancel_poll_retries_the_same_execution(monkeypatch):
    """`cancel` shares the retry budget: a transient lock while cancelling an
    already admitted execution must not fail the fire (the admission and receipt
    are verified-durable; cancel is idempotent)."""
    from hermes_cli.gateway_client import GatewayRPCError

    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", sleep)
    receipt = {"session_id": "s", "admission_id": "a"}
    calls = []

    async def call(op, params):
        calls.append((op, dict(params)))
        if len(calls) < 3:
            raise GatewayRPCError("storage_unavailable", 5001)
        return {"status": "cancelled"}

    state = await scheduler_authority._read_owner_with_lock_retry(call, "cancel", receipt)
    assert state["status"] == "cancelled"
    assert calls == [("cancel", receipt)] * 3
    assert sleeps == list(scheduler_authority._LOCK_RETRY_DELAYS[:2])


@pytest.mark.asyncio
async def test_definite_gateway_refusals_are_never_retried(monkeypatch):
    """Only transient contention retries: a bounded owner refusal (any other JSON-RPC
    code or reason) must surface on the first attempt."""
    from hermes_cli.gateway_client import GatewayRPCError

    async def no_sleep(_):
        pytest.fail("unexpected retry")

    monkeypatch.setattr(scheduler_authority.asyncio, "sleep", no_sleep)
    for exc in (GatewayRPCError("not_found", 4004), GatewayRPCError("request_failed")):
        calls = []

        async def call(op, params):
            calls.append(op)
            raise exc

        with pytest.raises(type(exc), match=str(exc)):
            await scheduler_authority._read_owner_with_lock_retry(call, "status", {})
        assert calls == ["status"]


def test_reconcile_recover_poll_retries_transient_storage_unavailable(tmp_path, monkeypatch):
    """A transport-lane reconcile poll that hits a busy owner writer (JSON-RPC 5001
    'storage_unavailable') must retry and resolve the journal, not burn one of the
    64 recovery scans per tick toward a terminal receipt_expired."""
    import json
    from contextlib import asynccontextmanager

    from cron import executions, jobs
    from hermes_cli import gateway_client

    attempts = []

    class Peer:
        async def rpc(self, method, **params):
            attempts.append(method)
            if len(attempts) < 3:
                raise gateway_client.GatewayRPCError("storage_unavailable", 5001)
            job = jobs.get_job(params["job_id"])
            return {"status": "terminal", "job": job,
                    "result": [True, "document", "answer", None]}

    @asynccontextmanager
    async def connected():
        yield Peer()

    monkeypatch.setattr(gateway_client, "connect_gateway", connected)

    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        execution = executions.create_execution(job["id"], source="test")
        executions.mark_execution_running(execution["id"])
        with executions._transaction() as conn:
            conn.execute("UPDATE executions SET process_id=?,pid=? WHERE id=?",
                         ("old-owner", 999999, execution["id"]))
        journal = scheduler_authority.journal_path(job["id"], execution["id"])
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps(
            {"params": {"job_id": job["id"], "request_id": execution["id"],
                        "extra_prompt": None}, "receipt": None}))

        scheduler_authority.reconcile_pending()

        assert attempts == ["cron.recover"] * 3
        assert executions.get_execution(execution["id"])["status"] == "completed"
        assert not journal.exists()
