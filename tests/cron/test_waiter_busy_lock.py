"""A transient SQLITE_BUSY on the executions ledger must not kill a healthy cron fire.

Field class, 2026-11-27: the gateway's external-worker waiter polls ``get_execution`` once a
second while its worker runs. Each call opens a fresh connection and re-runs schema-init DDL,
so a foreign writer convoy (state.db writer mutex held 31.1s during an upstream model outage)
exhausted the 5s busy_timeout and the resulting ``sqlite3.OperationalError: database is
locked`` escaped the wait loop as a post-handoff worker failure — booking false job failures
over live workers (jobs 35978cccc04f 12:04Z, 34afa079 12:14Z, e409464d 12:17Z; one of them a
2h44m fire whose real work had already merged). #589 gave the dispatch-critical writes a
bounded busy-lock ride; the waiter probe and the settlement writes that close an attempt
AFTER its side effects ran were still bare. These tests pin the extended contract: a busy
probe on a live worker keeps waiting, the post-exit read retries within the #589 budget and
falls back honestly when it stays busy, and finish/recover/terminalize commit the real
terminal verdict instead of discarding the run.
"""

from __future__ import annotations

import sqlite3
import subprocess
import time
from contextlib import contextmanager

import pytest

from cron import executions, scheduler


def _busy() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


class _Worker:
    """Worker whose ``wait`` times out for the first two polls, then exits 0."""

    def __init__(self, returncode: int = 0, polls_before_exit: int = 2) -> None:
        self._returncode = returncode
        self._polls_before_exit = polls_before_exit
        self.waits = 0

    def poll(self):
        return self._returncode if self.waits > self._polls_before_exit else None

    def wait(self, timeout=None):
        self.waits += 1
        if self.waits <= self._polls_before_exit:
            raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)
        return self._returncode


def test_waiter_rides_busy_probe_until_real_worker_exit(monkeypatch):
    """Busy locks on the 1s terminal probe must NOT escape the wait loop: the worker is
    alive, the probe is advisory, and the loop keeps waiting until the real wakeup (worker
    exit) — then the post-exit read retries its own busy lock and lands on the terminal row.

    RED on pre-fix main: the first busy probe raised straight out of the body as a
    post-handoff worker failure over a live worker."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    gets: list[str] = []

    def flaky_get(execution_id):
        gets.append(execution_id)
        if len(gets) < 4:
            raise _busy()
        return {"id": execution_id, "status": "completed"}

    monkeypatch.setattr(scheduler, "get_execution", flaky_get)

    result = scheduler._wait_for_external_cron_worker(
        _Worker(), execution_id="exec-498")

    assert result is True
    # 2 busy probes while the worker ran + 1 busy post-exit read + 1 terminal read.
    assert len(gets) == 4
    # Only the post-exit read retried (1.5s backoff between its two attempts).
    assert sleeps == [1.5]


def test_waiter_post_exit_busy_budget_falls_back_to_unknown_lane(monkeypatch, tmp_path):
    """When the post-exit ledger read stays busy past the whole retry budget, the waiter
    must fall back to the designed unknown-outcome lane: the row is terminalized ``unknown``
    with the truthful exit reason — never booked as a bare 'database is locked' job failure
    over work whose real state is unknown."""
    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    monkeypatch.setattr(scheduler, "get_execution", lambda _eid: (_ for _ in ()).throw(_busy()))
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    claimed = executions.create_execution("job-498", source="builtin")
    # Foreign, provably-dead owner so terminalize_dead_owner may act.
    monkeypatch.setattr(executions, "_PROCESS_ID", "waiter-proc")
    monkeypatch.setattr(executions, "_owner_is_live", lambda _pid, _started: False)

    with pytest.raises(scheduler._ExternalWorkerPostHandoffError) as excinfo:
        scheduler._wait_for_external_cron_worker(_Worker(), execution_id=claimed["id"])

    # The truthful cause, not the ledger's lock text.
    assert "Restart-safe cron worker exited" in str(excinfo.value)
    assert "database is locked" not in str(excinfo.value)
    row = executions.get_execution(claimed["id"])
    assert row["status"] == "unknown"
    # The post-exit read spent its whole budget: 1.5, 3.0, 6.0 backoffs.
    assert sleeps[:3] == [1.5, 3.0, 6.0]


def _running_row(executions, tmp_path, monkeypatch, job_id="job-1"):
    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    claimed = executions.create_execution(job_id, source="builtin")
    running = executions.mark_execution_running(claimed["id"])
    assert running["status"] == "running"
    return claimed["id"]


def test_finish_execution_rides_transient_busy_lock(monkeypatch, tmp_path):
    """The settlement write that closes a long run must retry a transient busy lock and
    commit the real terminal verdict (delivery outcome included) instead of raising and
    letting the lane book the completed run as failed."""
    execution_id = _running_row(executions, tmp_path, monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    real_transaction = executions._transaction
    calls = {"n": 0}

    @contextmanager
    def flaky_transaction():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _busy()
        with real_transaction() as conn:
            yield conn

    monkeypatch.setattr(executions, "_transaction", flaky_transaction)

    finished = executions.finish_execution(
        execution_id, success=True, delivery_outcome="delivered")

    assert finished is not None
    assert finished["status"] == "completed"
    assert finished["delivery_outcome"] == "delivered"
    assert sleeps == [1.5]
    assert calls["n"] == 2


def test_finish_execution_owner_fence_unchanged(monkeypatch, tmp_path):
    """Retries must not weaken the owner fence: a row claimed by a foreign process is
    still quietly refused (None), never rewritten and never retried into a write."""
    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    # Foreign row: created under another process identity.
    real_process_id = executions._PROCESS_ID
    monkeypatch.setattr(executions, "_PROCESS_ID", "foreign-proc")
    foreign = executions.create_execution("job-foreign", source="builtin")
    monkeypatch.setattr(executions, "_PROCESS_ID", real_process_id)
    ours = _running_row(executions, tmp_path, monkeypatch)

    real_transaction = executions._transaction

    @contextmanager
    def counting_transaction():
        counting_transaction.calls += 1
        with real_transaction() as conn:
            yield conn

    counting_transaction.calls = 0
    monkeypatch.setattr(executions, "_transaction", counting_transaction)

    assert executions.finish_execution(foreign["id"], success=True) is None
    assert counting_transaction.calls == 1  # one attempt, honest refusal, no retry churn

    finished = executions.finish_execution(ours, success=True)
    assert finished["status"] == "completed"


def test_finish_execution_busy_budget_exhaustion_reraises(monkeypatch, tmp_path):
    """A busy lock that survives the whole budget re-raises unchanged (fail-closed), with
    the bounded backoff trail proving it actually retried."""
    execution_id = _running_row(executions, tmp_path, monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    @contextmanager
    def always_busy():
        raise _busy()
        yield None  # pragma: no cover

    monkeypatch.setattr(executions, "_transaction", always_busy)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        executions.finish_execution(execution_id, success=True)
    assert sleeps == [1.5, 3.0, 6.0]


def test_recover_receipted_execution_rides_transient_busy_lock(monkeypatch, tmp_path):
    """Receipt recovery settles an owner-lost row; a transient busy lock must not abort
    that settlement — the retry commits the verified verdict."""
    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    claimed = executions.create_execution("job-r", source="builtin")

    real_transaction = executions._transaction
    calls = {"n": 0}

    @contextmanager
    def flaky_transaction():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _busy()
        with real_transaction() as conn:
            yield conn

    monkeypatch.setattr(executions, "_transaction", flaky_transaction)
    # Foreign, provably-dead owner: recoverable per _row_owner_live.
    monkeypatch.setattr(executions, "_PROCESS_ID", "recovery-proc")
    monkeypatch.setattr(executions, "_owner_is_live", lambda _pid, _started: False)

    record = executions.recover_receipted_execution(
        claimed["id"], "job-r", success=True, delivery_outcome="delivered")

    assert record is not None
    assert record["status"] == "completed"
    assert record["delivery_outcome"] == "delivered"
    assert sleeps == [1.5]


def test_terminalize_dead_owner_rides_transient_busy_lock(monkeypatch, tmp_path):
    """The unknown-outcome terminalization writes the truthful cause; a transient busy
    lock retries and commits instead of bouncing the waiter into a false dispatch failure."""
    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    claimed = executions.create_execution("job-t", source="builtin")

    real_transaction = executions._transaction
    calls = {"n": 0}

    @contextmanager
    def flaky_transaction():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _busy()
        with real_transaction() as conn:
            yield conn

    monkeypatch.setattr(executions, "_transaction", flaky_transaction)
    monkeypatch.setattr(executions, "_PROCESS_ID", "waiter-proc")
    monkeypatch.setattr(executions, "_owner_is_live", lambda _pid, _started: False)

    assert executions.terminalize_dead_owner(
        claimed["id"], reason="Restart-safe cron worker exited with status 0") is True
    row = executions.get_execution(claimed["id"])
    assert row["status"] == "unknown"
    assert "exited with status 0" in row["error"]
    assert sleeps == [1.5]
