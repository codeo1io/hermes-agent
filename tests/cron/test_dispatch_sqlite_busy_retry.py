"""Dispatch-critical ledger writes must ride out transient SQLITE_BUSY contention.

Field shape (2026-11-25): during upstream model outages the in-process state.db
writer mutex stretches to 24–147s, and the executions ledger's 5s busy_timeout
then fails ``create_execution`` / ``mark_execution_handoff_pending`` outright.
Every such failure skipped a job's whole occurrence ("not dispatched: execution
creation failed: database is locked") or booked it as a failed run with an
incident ("Restart-safe cron worker dispatch failed"). Three storms in 24h;
19 job dispatches lost in one. Lock-class contention is transient by
definition — the dispatch path must retry it, not book a failure.
"""
import logging
import sqlite3

import pytest

from cron import executions


@pytest.fixture()
def ledger_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _raise_busy():
    return sqlite3.OperationalError("database is locked")


def test_create_execution_retries_busy_lock_then_succeeds(ledger_home, monkeypatch, caplog):
    """A busy lock on the ledger INSERT retries with backoff and the run dispatches."""
    monkeypatch.setattr(executions, "_DISPATCH_LOCK_BACKOFF_S", 0.001)
    real_transaction = executions._transaction
    calls = {"n": 0}

    import contextlib

    @contextlib.contextmanager
    def flaky_transaction():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _raise_busy()
        with real_transaction() as conn:
            yield conn

    monkeypatch.setattr(executions, "_transaction", flaky_transaction)

    with caplog.at_level(logging.WARNING):
        record = executions.create_execution("job-busy", source="test")

    assert record["status"] == "claimed"
    assert calls["n"] == 2
    assert any("busy lock" in r.message for r in caplog.records)


def test_create_execution_gives_up_after_bounded_budget(ledger_home, monkeypatch):
    """A lock that survives the retry budget re-raises for the caller's failure lane."""
    monkeypatch.setattr(executions, "_DISPATCH_LOCK_BACKOFF_S", 0.001)
    calls = {"n": 0}

    import contextlib

    @contextlib.contextmanager
    def always_busy():
        calls["n"] += 1
        raise _raise_busy()
        yield  # pragma: no cover

    monkeypatch.setattr(executions, "_transaction", always_busy)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        executions.create_execution("job-wedged", source="test")
    assert calls["n"] == executions._DISPATCH_LOCK_RETRIES  # bounded, not infinite


def test_non_lock_sqlite_errors_propagate_immediately(ledger_home, monkeypatch):
    """Schema/corruption errors are NOT retried: no busy-class masking."""
    monkeypatch.setattr(executions, "_DISPATCH_LOCK_BACKOFF_S", 0.001)
    calls = {"n": 0}

    import contextlib

    @contextlib.contextmanager
    def broken_schema():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: executions")
        yield  # pragma: no cover

    monkeypatch.setattr(executions, "_transaction", broken_schema)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        executions.create_execution("job-schema", source="test")
    assert calls["n"] == 1  # no retry consumed


def test_mark_handoff_pending_retries_busy_lock(ledger_home, monkeypatch):
    """The handoff fence write also rides out a busy lock."""
    monkeypatch.setattr(executions, "_DISPATCH_LOCK_BACKOFF_S", 0.001)
    record = executions.create_execution("job-handoff", source="test")
    real_transaction = executions._transaction
    calls = {"n": 0}

    import contextlib

    @contextlib.contextmanager
    def flaky_transaction():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _raise_busy()
        with real_transaction() as conn:
            yield conn

    monkeypatch.setattr(executions, "_transaction", flaky_transaction)

    fenced = executions.mark_execution_handoff_pending(record["id"])
    assert fenced is not None
    assert fenced["handoff_pending"] == 1
    assert calls["n"] == 2


def test_settle_unstarted_retries_busy_and_stays_best_effort(ledger_home, monkeypatch):
    """The never-started receipt close retries busy locks; a persistent one only logs."""
    monkeypatch.setattr(executions, "_DISPATCH_LOCK_BACKOFF_S", 0.001)
    record = executions.create_execution("job-settle", source="test")
    real_transaction = executions._transaction
    calls = {"n": 0}

    import contextlib

    @contextlib.contextmanager
    def flaky_transaction():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _raise_busy()
        with real_transaction() as conn:
            yield conn

    monkeypatch.setattr(executions, "_transaction", flaky_transaction)
    executions.settle_unstarted_execution(record["id"], "job-settle", "boom")
    assert calls["n"] == 2
    assert executions.get_execution(record["id"])["status"] == "failed"


def test_is_busy_lock_classifier_is_narrow():
    """The classifier matches the SQLITE_BUSY message family only."""
    from cron.scheduler import _is_sqlite_busy_error

    assert _is_sqlite_busy_error(sqlite3.OperationalError("database is locked"))
    assert _is_sqlite_busy_error(sqlite3.OperationalError("database table is locked"))
    assert not _is_sqlite_busy_error(RuntimeError("boom"))  # no sqlite cause at all
    try:
        try:
            raise _raise_busy()
        except sqlite3.OperationalError as cause:
            raise RuntimeError("worker dispatch failed") from cause
    except RuntimeError as wrapped:
        assert _is_sqlite_busy_error(wrapped)
    assert not _is_sqlite_busy_error(sqlite3.OperationalError("no such table: executions"))
    assert not _is_sqlite_busy_error(ValueError("database is locked but not sqlite"))
