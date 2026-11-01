"""A transient SQLite lock while stamping progress must not fail the canonical fire.

The observe loop guards the ``status`` RPC against transient SQLite busy/locked
errors, but the progress stamp (``touch_execution_progress``) runs on the same
loop outside that guard. A lock there escaped as ``CronExecutionUnknown``: a
verified, progressing run was booked as an unverified fire, the job was paused,
and the schedule silently stopped (observed 2026-10-31T23:40Z, execution
``d2a0ac1adf…`` on job ``35978cccc04f``).
"""
from contextlib import asynccontextmanager
import sqlite3

from cron import executions, jobs, scheduler_authority
from hermes_cli import gateway_client


def test_progress_stamp_lock_does_not_unknown_the_fire(tmp_path, monkeypatch):
    with jobs.use_cron_store(tmp_path / 'cron'):
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        fire = executions.create_execution(job['id'], source='test')['id']

        calls = {'status': 0}

        class Peer:
            async def rpc(self, method, **params):
                assert method in ('cron.submit', 'cron.status')
                if method == 'cron.submit':
                    return {'session_id': 'sess-1', 'admission_id': 'adm-1'}
                calls['status'] += 1
                if calls['status'] == 1:
                    # First status: the run is alive and its owner just stamped progress.
                    return {'status': 'started', 'progress_at': '2026-11-01T00:00:00+00:00'}
                return {'status': 'terminal', 'result': [True, 'ok', 'document', None],
                        'job_flags': {}}

        @asynccontextmanager
        async def connected():
            yield Peer()

        monkeypatch.setattr(gateway_client, 'connect_gateway', connected)

        def locked_stamp(_execution_id):
            raise sqlite3.OperationalError('database is locked')

        monkeypatch.setattr(executions, 'touch_execution_progress', locked_stamp)

        result = scheduler_authority.run_canonical_job(dict(job, execution_id=fire))
        assert list(result) == [True, 'ok', 'document', None]
        assert calls['status'] == 2
        assert executions.get_execution(fire)['status'] in ('claimed', 'running')


def test_progress_stamp_still_refreshes_when_healthy(tmp_path, monkeypatch):
    """The stamp remains best-effort telemetry: a healthy write is attempted once per
    owner progress tick, and a row no longer ours simply skips the stamp."""
    with jobs.use_cron_store(tmp_path / 'cron'):
        job = jobs.create_job(prompt='report', schedule='every 1h', deliver='local')
        fire = executions.create_execution(job['id'], source='test')['id']
        stamps = []

        class Peer:
            async def rpc(self, method, **params):
                if method == 'cron.submit':
                    return {'session_id': 'sess-1', 'admission_id': 'adm-1'}
                return {'status': 'terminal', 'result': [True, 'ok', 'document', None],
                        'job_flags': {}}

        @asynccontextmanager
        async def connected():
            yield Peer()

        monkeypatch.setattr(gateway_client, 'connect_gateway', connected)
        monkeypatch.setattr(executions, 'touch_execution_progress',
                            lambda eid: stamps.append(eid) or True)

        result = scheduler_authority.run_canonical_job(dict(job, execution_id=fire))
        assert list(result) == [True, 'ok', 'document', None]
        assert stamps == []  # terminal never reported a progress tick: nothing to stamp
