"""A transient progress-stamp lock must not abandon an admitted live canonical cron run."""
from contextlib import asynccontextmanager
import sqlite3

import pytest

from cron import executions, scheduler_authority
from gateway import session_cron
from hermes_cli import gateway_client


@pytest.mark.parametrize("lock_message", ["database is locked", "database table is locked"])
def test_progress_lock_retries_same_owner_admission(tmp_path, monkeypatch, lock_message):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(session_cron, "owner_for_home", lambda home: None)
    status_calls = []
    submits = []
    stamps = []

    class Peer:
        async def rpc(self, method, **params):
            if method == "cron.submit":
                submits.append(params)
                return {"session_id": "same-session", "admission_id": "same-admission"}
            assert method == "cron.status"
            assert params == {"session_id": "same-session", "admission_id": "same-admission"}
            status_calls.append(params)
            if len(status_calls) < 3:
                return {"status": "started", "progress_at": 123.0}
            return {"status": "terminal", "result": [True, "real output", "answer", None]}

    @asynccontextmanager
    async def connected():
        yield Peer()

    def stamp(execution_id):
        stamps.append(execution_id)
        if len(stamps) == 1:
            raise sqlite3.OperationalError(lock_message)
        return True

    monkeypatch.setattr(gateway_client, "connect_gateway", connected)
    monkeypatch.setattr(executions, "touch_execution_progress", stamp)
    result = scheduler_authority.run_canonical_job({"id": "canonical"}, execution_id="exact-fire")
    assert result == (True, "real output", "answer", None)
    assert len(submits) == 1
    assert len(status_calls) == 3
    assert stamps == ["exact-fire", "exact-fire"]


def test_non_lock_sqlite_error_still_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(session_cron, "owner_for_home", lambda home: None)
    submits = []

    class Peer:
        async def rpc(self, method, **params):
            if method == "cron.submit":
                submits.append(params)
                return {"session_id": "same-session", "admission_id": "same-admission"}
            assert method == "cron.status"
            return {"status": "started", "progress_at": 123.0}

    @asynccontextmanager
    async def connected():
        yield Peer()

    def broken_stamp(execution_id):
        raise sqlite3.OperationalError("no such table: executions")

    monkeypatch.setattr(gateway_client, "connect_gateway", connected)
    monkeypatch.setattr(executions, "touch_execution_progress", broken_stamp)
    with pytest.raises(scheduler_authority.CronExecutionUnknown, match="no such table"):
        scheduler_authority.run_canonical_job({"id": "canonical"}, execution_id="exact-fire")
    assert len(submits) == 1
    assert scheduler_authority.journal_path("canonical", "exact-fire").exists()
