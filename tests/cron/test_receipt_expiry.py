"""Permanently-unknown cron admission journals must expire, not retry forever.

The 2026-10-24 receipt-recovery loop: journals whose owner died pre-receipt (execution row
``unknown``, peer answers ``unknown``) were re-scanned every tick indefinitely — and journals
whose recovery raised (the ``UnscopedSecretError`` class) re-spammed the log on every pass.
``reconcile_pending`` now bounds both: the unknown state books a terminal ``receipt_expired``
outcome through the ordinary refusal shape, and the exception path retires the journal aside
(evidence preserved). Young journals never expire — recovery keeps its full window.
"""
from contextlib import asynccontextmanager
import json

import pytest

from cron import jobs, executions, scheduler_authority
from hermes_cli import gateway_client


def peer(monkeypatch, call):
    class Peer:
        async def rpc(self, method, **params):
            return call(method, params)
    @asynccontextmanager
    async def connected():
        yield Peer()
    monkeypatch.setattr(gateway_client, 'connect_gateway', connected)


def _plant(job_id, request_id, *, record_extra=None):
    params = {'job_id': job_id, 'request_id': request_id, 'extra_prompt': None}
    journal = scheduler_authority.journal_path(job_id, request_id)
    journal.parent.mkdir(parents=True, exist_ok=True)
    record = {'params': params, 'receipt': None}
    record.update(record_extra or {})
    journal.write_text(json.dumps(record))
    return journal


def test_unknown_journal_expires_to_terminal_booking(tmp_path, monkeypatch):
    """A permanently-unknown admission past the scan bound books an honest failure, settles
    the ledger row, lifts its own pause, and retires the journal — never re-fired."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        monkeypatch.setattr(scheduler_authority, 'RECOVERY_SCAN_LIMIT', 3)
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        execution = executions.create_execution(job['id'], source='test')
        with executions._transaction() as conn:
            conn.execute('UPDATE executions SET status=?,process_id=?,pid=? WHERE id=?',
                         ('unknown', 'departed-owner', 999999, execution['id']))
        journal = _plant(job['id'], execution['id'])
        peer(monkeypatch, lambda method, params: {'status': 'unknown', 'result': None})
        for _ in range(scheduler_authority.RECOVERY_SCAN_LIMIT - 1):
            scheduler_authority.reconcile_pending()
            assert journal.exists(), 'journal must survive inside the recovery window'
            assert jobs.get_job(job['id'])['state'] == 'paused'
        scheduler_authority.reconcile_pending()
        row = executions.get_execution(execution['id'])
        assert row['status'] == 'failed'
        assert 'receipt expired' in row['error']
        saved = jobs.get_job(job['id'])
        assert saved['last_status'] == 'error'
        assert saved['failure_streak'] == 1
        assert saved['state'] == 'scheduled', 'the pause this uncertainty caused is lifted'
        assert saved['repeat']['completed'] == 1
        assert not journal.exists(), 'expired journal retires out of the scan'
        # Terminal state is stable: nothing re-books, nothing re-fires.
        scheduler_authority.reconcile_pending()
        assert jobs.get_job(job['id'])['repeat']['completed'] == 1
        assert jobs.get_job(job['id'])['state'] == 'scheduled'


def test_young_unknown_journal_never_expires(tmp_path, monkeypatch):
    """Inside the bounds the existing behavior is untouched: observe, pause, keep the journal."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        journal = _plant(job['id'], 'lost-fire')
        peer(monkeypatch, lambda method, params: {'status': 'unknown', 'result': None})
        for _ in range(5):
            scheduler_authority.reconcile_pending()
            assert journal.exists()
            assert jobs.get_job(job['id'])['state'] == 'paused'
        record = json.loads(journal.read_text())
        assert record['recovery_scans'] == 5, 'scan counter advances on the journal record'


def test_age_bound_expires_unknown_journal(tmp_path, monkeypatch):
    """A journal carried across restarts (first-seen anchor persisted) ages out even when the
    live scan count is below the limit."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        monkeypatch.setattr(scheduler_authority, 'RECOVERY_AGE_LIMIT_SECONDS', 0.0)
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        journal = _plant(job['id'], 'old-fire')
        peer(monkeypatch, lambda method, params: {'status': 'unknown', 'result': None})
        scheduler_authority.reconcile_pending()
        assert not journal.exists()
        saved = jobs.get_job(job['id'])
        assert saved['last_status'] == 'error' and 'receipt expired' in saved['last_error']


def test_raising_recovery_retires_journal_aside(tmp_path, monkeypatch):
    """The 2026-10-24 loop class: recovery itself raises every pass. Past the bound the
    journal is renamed aside — out of the scan, evidence preserved, never deleted."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        monkeypatch.setattr(scheduler_authority, 'RECOVERY_SCAN_LIMIT', 2)
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        execution = executions.create_execution(job['id'], source='test')
        with executions._transaction() as conn:
            conn.execute('UPDATE executions SET status=?,process_id=?,pid=? WHERE id=?',
                         ('unknown', 'departed-owner', 999999, execution['id']))
        journal = _plant(job['id'], execution['id'])

        def raising(method, params):
            raise RuntimeError('UnscopedSecretError: MATRIX_HOME_ROOM (synthetic loop shape)')
        peer(monkeypatch, raising)
        for _ in range(scheduler_authority.RECOVERY_SCAN_LIMIT):
            scheduler_authority.reconcile_pending()
        aside = journal.with_name(journal.name + '.deferred-expired')
        assert not journal.exists()
        assert aside.exists(), 'evidence preserved aside, not deleted'
        record = json.loads(aside.read_text())
        assert record['recovery_scans'] == scheduler_authority.RECOVERY_SCAN_LIMIT
        # The retired journal is out of the scan: further passes touch nothing.
        before = aside.read_text()
        scheduler_authority.reconcile_pending()
        scheduler_authority.reconcile_pending()
        assert aside.read_text() == before
        assert executions.get_execution(execution['id'])['status'] == 'unknown'


def test_unreadable_journal_ages_out_by_mtime(tmp_path, monkeypatch):
    """A journal that cannot even be parsed can never resolve; past the age bound it is
    retired aside rather than re-raising on every scan pass."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        journal = _plant(job['id'], 'corrupt-fire')
        journal.write_text('{not json')
        import os
        old = os.stat(journal).st_mtime - (scheduler_authority.RECOVERY_AGE_LIMIT_SECONDS + 3600)
        os.utime(journal, (old, old))
        peer(monkeypatch, lambda method, params: {'status': 'unknown', 'result': None})
        scheduler_authority.reconcile_pending()
        aside = journal.with_name(journal.name + '.deferred-expired')
        assert not journal.exists()
        assert aside.exists()


def test_operator_pause_survives_expiry_booking(tmp_path, monkeypatch):
    """The expiry lifts only the pause IT recorded for the unknown: an operator pause taken
    after the recovery pause (different identity) keeps the job paused after expiry."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        journal = _plant(job['id'], 'lost-fire')
        peer(monkeypatch, lambda method, params: {'status': 'unknown', 'result': None})
        scheduler_authority.reconcile_pending()  # records the recovery pause; young, no expiry
        assert jobs.get_job(job['id'])['state'] == 'paused'
        assert jobs.get_job(job['id'])['paused_reason'] == 'Canonical cron unknown; no automatic re-execution'
        from cron.jobs import pause_job
        pause_job(job['id'], reason='operator hold')
        monkeypatch.setattr(scheduler_authority, 'RECOVERY_AGE_LIMIT_SECONDS', 0.0)
        scheduler_authority.reconcile_pending()  # expiry books the failure; identity mismatch
        saved = jobs.get_job(job['id'])
        assert saved['last_status'] == 'error' and 'receipt expired' in saved['last_error']
        assert saved['state'] == 'paused', 'the operator hold outlives the expiry booking'
        assert saved['paused_reason'] == 'operator hold'
        assert not journal.exists()
