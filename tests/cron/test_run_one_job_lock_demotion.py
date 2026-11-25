"""run_one_job must not book a permanent failure for pre-handoff lock contention.

Field shape (2026-11-25, item-487/488): during upstream model outages the
executions ledger's 5s busy_timeout lost races to 24-147s foreign writer
holds, and ``_launch_external_cron_worker`` raised ``database is locked``
BEFORE any worker process existed. The old lane booked that as a job failure
with a crash delivery and an incident row — 19 jobs' occurrences burned in one
storm on 2026-11-25 alone. A pre-handoff lock failure has no side effects and
must defer the occurrence to the next tick instead.
"""
import logging
import sqlite3

import pytest

from cron import executions
from cron import scheduler


@pytest.fixture()
def ledger_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _busy_handoff(job):  # raised before any subprocess exists
    raise sqlite3.OperationalError("database is locked")


def test_pre_handoff_lock_contention_defers_not_fails(ledger_home, monkeypatch, caplog):
    """A busy lock before worker handoff defers the occurrence; no job failure booked."""
    monkeypatch.setattr(scheduler, "_launch_external_cron_worker", _busy_handoff)
    failure_bookings = []
    monkeypatch.setattr(
        scheduler, "mark_job_run",
        lambda *a, **kw: failure_bookings.append((a, kw)))
    crash_deliveries = []
    monkeypatch.setattr(
        scheduler, "_deliver_crash_failure",
        lambda *a, **kw: crash_deliveries.append((a, kw)) or (None, None))

    job = {"id": "job-lock-defer", "execution_id": None}
    with caplog.at_level(logging.WARNING):
        processed = scheduler.run_one_job(job)

    assert processed is True  # the tick is done with this job (deferred, not failed)
    assert failure_bookings == []  # no permanent job failure
    assert crash_deliveries == []  # no crash-failure delivery, no incident lane

    deferred = [r for r in caplog.records if "lock contention" in r.message]
    assert deferred, "the deferral must be observable in the log"


def test_pre_handoff_non_lock_error_still_fails_loud(ledger_home, monkeypatch):
    """Non-lock dispatch failures keep the existing failure lane (#123401)."""
    def _broken(job):
        raise RuntimeError("worker spawn failed: ENOMEM")

    monkeypatch.setattr(scheduler, "_launch_external_cron_worker", _broken)
    failure_bookings = []
    monkeypatch.setattr(
        scheduler, "mark_job_run",
        lambda *a, **kw: failure_bookings.append((a, kw)))
    monkeypatch.setattr(
        scheduler, "_deliver_crash_failure",
        lambda *a, **kw: (None, None))

    job = {"id": "job-hard-fail", "execution_id": None}
    processed = scheduler.run_one_job(job)

    assert processed is True
    assert len(failure_bookings) == 1  # the honest failure lane still books
    assert "dispatch failed" in failure_bookings[0][1].get("error", failure_bookings[0][0][2])


def test_post_handoff_lock_error_is_not_demoted(ledger_home, monkeypatch):
    """A lock error AFTER handoff (worker may exist, side effects possible) keeps the failure lane."""
    def _post_handoff(job):
        raise scheduler._ExternalWorkerPostHandoffError("database is locked after handoff")

    monkeypatch.setattr(scheduler, "_launch_external_cron_worker", _post_handoff)
    unknown_recordings = []
    import cron.scheduler_worker_failure as swf
    monkeypatch.setattr(
        swf, "record_unknown_worker_outcome",
        lambda job, **kw: unknown_recordings.append(job) or True)

    job = {"id": "job-post-handoff", "execution_id": None}
    processed = scheduler.run_one_job(job)

    assert processed is True
    assert unknown_recordings, "post-handoff errors must record unknown outcomes, never demote"
