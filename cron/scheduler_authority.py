"""Transport-only cron execution; output/delivery remain with the firing scheduler."""
import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid


class CronExecutionUnknown(RuntimeError):
    """The owner may have accepted this fire; never book it as failed or re-fire."""


# A permanently-unknown admission (firer died pre-receipt, execution row unknown, owner gone)
# can never resolve: the owner that would answer ``recover`` is dead. Recovery retried such
# journals forever (the 2026-10-24 receipt-recovery loop: ~54 deferrals/3min per journal), so
# reconcile counts its own scans on the journal record and, past the bounds below, books a
# terminal ``receipt_expired`` outcome instead of retrying. Fail-closed shape: the job's own
# pause for the unknown stays until the receipt expiry retires it; nothing is re-fired.
RECOVERY_SCAN_LIMIT = 64
RECOVERY_AGE_LIMIT_SECONDS = 24 * 3600.0


def _expiry_state(journal, record):
    """``(scans, first_seen)`` tracked on the journal record; increments persist immediately.

    The counter lives in the journal (not the ledger) so a restarted scheduler sees the same
    history: one scan == one reconcile pass that could not resolve this journal.
    """
    scans = int(record.get('recovery_scans') or 0)
    first_seen = record.get('recovery_first_seen_at')
    if not first_seen:
        from hermes_time import now as _hermes_now
        first_seen = _hermes_now().isoformat()
    record['recovery_scans'] = scans + 1
    record['recovery_first_seen_at'] = first_seen
    from utils import atomic_json_write
    atomic_json_write(journal, record, mode=0o600, fsync_dir=True)
    return record['recovery_scans'], first_seen


def _expired(scans, first_seen):
    from datetime import datetime
    from hermes_time import now as _hermes_now
    try:
        age = (_hermes_now() - datetime.fromisoformat(first_seen)).total_seconds()
    except (TypeError, ValueError):
        age = 0.0
    return scans >= RECOVERY_SCAN_LIMIT or age >= RECOVERY_AGE_LIMIT_SECONDS


def _retire_expired_journal(journal, reason):
    """Set an unresolvable journal aside — never delete: out of the ``*.json`` scan,
    evidence preserved for the operator (the 2026-10-25 manual mitigation's shape)."""
    logger = logging.getLogger(__name__)
    try:
        target = journal.with_name(journal.name + '.deferred-expired')
        journal.rename(target)
        logger.warning('Cron receipt journal retired after exhausting recovery: %s (%s)',
                       target, reason)
    except OSError:
        # Unwritable store: the journal stays in the scan; nothing is lost or dropped.
        pass


def _bound_deferred_retry(journal):
    """Bound the deferred-retry loop in the exception path: a journal whose recovery keeps
    raising (the 2026-10-24 ``UnscopedSecretError`` loop class) can never resolve, and each
    pass re-spams the log. Parseable journals count scans on the record (same counter as the
    unknown-state expiry); unreadable journals — which can never resolve at all — age-bound
    by mtime. Past the bounds the journal is retired aside, evidence preserved."""
    try:
        record = json.loads(journal.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        import os
        import time
        try:
            if time.time() - os.path.getmtime(journal) >= RECOVERY_AGE_LIMIT_SECONDS:
                _retire_expired_journal(journal, 'unreadable journal past the age bound')
        except OSError:
            pass
        return
    if not isinstance(record, dict):
        return
    try:
        scans, first_seen = _expiry_state(journal, record)
    except (OSError, TypeError, ValueError):
        return
    if _expired(scans, first_seen):
        _retire_expired_journal(journal, f'{scans} deferred recovery scans')


def journal_path(job_id, request_id):
    from hermes_constants import get_hermes_home
    key = hashlib.sha256(json.dumps([job_id, request_id]).encode()).hexdigest()
    return get_hermes_home() / 'cron' / 'admissions' / (key + '.json')


def _pause_identity(paused):
    """The exact pause this recovery uncertainty caused, so only that pause is ever lifted."""
    return {'paused_at': paused.get('paused_at'), 'reason': paused.get('paused_reason')} if paused else True


def replayable_completions(job_id, completions):
    """The recorded completion ids whose admission journal still exists: only journal recovery
    can replay a completion into ``mark_job_run``, so an id without one is a dead tombstone."""
    return [eid for eid in completions or () if journal_path(job_id, eid).exists()]


def pause_for_unknown(job_id, execution_id, reason):
    """The firer pauses the job for this fire's unverified admission and records that exact pause
    on the fire's journal, so the receipt that later proves the run terminal can lift it."""
    from cron.jobs import pause_job
    from utils import atomic_json_write
    paused = pause_job(job_id, reason=reason)
    journal = journal_path(job_id, execution_id)
    if paused and journal.exists():
        record = json.loads(journal.read_text(encoding='utf-8-sig'))
        record['pause_recorded'] = _pause_identity(paused)
        atomic_json_write(journal, record, mode=0o600, fsync_dir=True)


def _lift_pause(job_id, pause):
    """A verified terminal receipt resolved the uncertainty that paused the schedule: resume it iff
    the job is still held by exactly that pause (an operator's own pause/resume is never touched)."""
    from cron.jobs import get_job, resume_job
    job = get_job(job_id) if isinstance(pause, dict) else None
    if (job is not None and job.get('state') == 'paused'
            and (job.get('paused_at'), job.get('paused_reason')) == (pause['paused_at'], pause['reason'])):
        try:
            resume_job(job_id)
        except ValueError:  # a one-shot whose instant has passed stays paused for the operator
            pass


def run_canonical_job(job, *, extra_prompt=None, cancel_event=None, execution_id=None):
    from gateway.session_cron import owner_for_home, operation
    from hermes_cli.gateway_client import connect_gateway
    from hermes_constants import get_hermes_home
    from utils import atomic_json_write

    request_id = execution_id or job.get('execution_id')
    if not request_id:
        request_id = job['execution_id'] = uuid.uuid4().hex
    params = {'job_id': job['id'], 'request_id': request_id,
              'extra_prompt': extra_prompt}
    root = get_hermes_home() / 'cron' / 'admissions'
    journal = journal_path(params['job_id'], params['request_id'])
    record = {'params': params, 'receipt': None}
    if journal.exists():
        record = json.loads(journal.read_text(encoding='utf-8-sig'))
        if record['params'] != params:
            raise CronExecutionUnknown('cron admission identity conflict')
    attempted = journal.exists()
    owner = owner_for_home(get_hermes_home())

    def save():
        root.mkdir(parents=True, exist_ok=True)
        atomic_json_write(journal, record, mode=0o600, fsync_dir=True)

    async def observe(call):
        nonlocal attempted
        from hermes_cli.gateway_client import GatewayRPCError
        attempted = True
        save()
        try:
            receipt = await call('submit', params)
        except Exception as exc:
            # A returned owner exception is definite; a transport disconnect is not. Even an
            # owner error after commit must retain the admitted identity, so verify its absence.
            if owner is not None or isinstance(exc, GatewayRPCError):
                state = await call('recover', params)
                if state['status'] == 'missing':
                    error = f'{type(exc).__name__}: {exc}'
                    result = [False, f'# Cron Job: {job["id"]} (FAILED)\n\n{error}\n', '', error]
                    record['refusal'] = result
                    record['job'] = dict(job)
                    save()
                    return tuple(result)
                if state['status'] not in {'queued', 'started', 'terminal'}:
                    raise
                # Admitted before the answer was lost: observe it through the recovered receipt.
                receipt = {'session_id': state['session_id'], 'admission_id': state['admission_id']}
            else:
                raise
        record['receipt'] = receipt
        save()
        delay, progress, busy_retries = .1, None, 0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                await call('cancel', receipt)
            try:
                state = await call('status', receipt)
            except (sqlite3.OperationalError, GatewayRPCError) as exc:
                # The admission identity and receipt are durable. A transient SQLite
                # lock (direct owner) or storage_unavailable RPC (remote owner)
                # must not cause duplicate submission. Retain the unknown/pause
                # fence if bounded observation retries cannot resolve the lock.
                sqlite_busy = (isinstance(exc, sqlite3.OperationalError) and (
                    getattr(exc, 'sqlite_errorcode', None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                    or 'locked' in str(exc).lower()))
                remote_busy = (isinstance(exc, GatewayRPCError) and exc.code == 5001
                               and str(exc) == 'storage_unavailable')
                if not (sqlite_busy or remote_busy):
                    raise
                busy_retries += 1
                if busy_retries > 5:
                    raise
                await asyncio.sleep(min(.25 * 2 ** (busy_retries - 1), 2.0))
                continue
            busy_retries = 0
            if state.get('progress_at') not in (None, progress):
                # The owner's agent is still working: refresh OUR ledger row (the owner's stamp is
                # fenced to the row's owner), once per owner stamp, so the stale-claim sweep measures
                # the run's silence. A wedged owner stops stamping and the sweep still fires.
                from cron.executions import touch_execution_progress
                progress = state['progress_at']
                await asyncio.to_thread(touch_execution_progress, request_id)
            if state['status'] == 'terminal':
                job.update(state.get('job_flags') or {})
                return tuple(state['result'])
            if state['status'] == 'unknown':
                raise CronExecutionUnknown('unknown_execution: cron admission was not replayed')
            await asyncio.sleep(delay)
            delay = min(delay * 2, 2.0)

    async def remote():
        async with connect_gateway() as client:
            return await observe(lambda op, data: client.rpc('cron.' + op, **data))

    try:
        if owner is not None:
            authority, loop = owner
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is loop:
                raise RuntimeError('cron synchronous execution must run off the owner event loop')
            return asyncio.run_coroutine_threadsafe(
                observe(lambda op, data: operation(authority, op, data)), loop).result()
        return asyncio.run(remote())
    except Exception as exc:
        if attempted:
            raise CronExecutionUnknown(f'Cron execution unverified; reconcile {journal}: {exc}') from exc
        error = f'{type(exc).__name__}: {exc}'
        return False, f'# Cron Job: {job["id"]} (FAILED)\n\n{error}\n', '', error

def reconcile_pending(*, allow_connect=True):
    """Observe prepared fires; never submit missing or interrupted work.

    With allow_connect=False, a headless tick leaves durable receipts for the next
    live owner instead of ensuring or spawning a gateway.
    """
    from gateway.session_cron import owner_for_home, operation
    from hermes_constants import get_hermes_home
    from hermes_cli.gateway_client import connect_gateway
    from cron.executions import execution_owner_live, get_execution
    from cron.jobs import get_job, pause_job
    from cron.scheduler import (_RunDelivery, _FireOwnership, _apply_agent_failure_marker,
                                _save_compose_deliver, _fire_secret_scope)
    from cron.scheduler_bookkeeping import fail_empty_response, finish_completed_run
    from utils import atomic_json_write
    import logging

    root = get_hermes_home() / 'cron' / 'admissions'
    for journal in sorted(root.glob('*.json')):
        try:
            record = json.loads(journal.read_text(encoding='utf-8-sig'))
            params = record['params']
            if journal != journal_path(params['job_id'], params['request_id']):
                raise ValueError('cron journal identity conflict')
            if execution_owner_live(params['request_id'], params['job_id']):
                # Its firer (this process included) still owns the row and its tail: re-saving the
                # output or re-marking the job on every tick would duplicate its side effects.
                continue
            row = get_execution(params['request_id'])
            if row is not None and row['job_id'] == params['job_id'] and row['status'] in {'completed', 'failed'}:
                # The firer booked this attempt's terminal outcome itself (ownership lost, shutdown
                # interrupt, a crashed tail): the receipt is not a result to save or deliver again.
                journal.unlink(missing_ok=True)
                continue
            if 'refusal' in record:
                state = {'status': 'terminal', 'result': record['refusal'], 'job': record['job']}
            else:
                owner = owner_for_home(get_hermes_home())
                if owner is None and not allow_connect:
                    continue
                async def observe():
                    if owner is not None:
                        return await operation(owner[0], 'recover', params)
                    async with connect_gateway() as client:
                        return await client.rpc('cron.recover', **params)
                if owner is not None:
                    state = asyncio.run_coroutine_threadsafe(observe(), owner[1]).result(timeout=20)
                else:
                    state = asyncio.run(observe())
            if state['status'] == 'missing':
                # The owner holds no admission for this fire: a definite non-admission, booked as
                # the same failed run the in-submit refusal books. Only ``unknown`` pauses.
                current = get_job(params['job_id'])
                if current is None:
                    journal.unlink(missing_ok=True)
                    continue
                error = 'Cron admission missing: the owner never admitted this fire'
                state = {'status': 'terminal', 'job': current,
                         'result': [False, f'# Cron Job: {params["job_id"]} (FAILED)\n\n{error}\n', '', error]}
            if state['status'] != 'terminal':
                if state['status'] == 'unknown' and not record.get('pause_recorded'):
                    reason = 'Canonical cron unknown; no automatic re-execution'
                    record['pause_recorded'] = _pause_identity(pause_job(params['job_id'], reason=reason))
                    atomic_json_write(journal, record, mode=0o600, fsync_dir=True)
                if state['status'] == 'unknown':
                    scans, first_seen = _expiry_state(journal, record)
                    if not _expired(scans, first_seen):
                        continue
                    # Permanently unknown past every bound: the dead owner can never answer,
                    # so book the uncertainty itself as the run's terminal outcome instead of
                    # deferring forever. Same refusal shape as a definite non-admission: the
                    # job's record keeps an honest failure, the schedule resumes (the pause
                    # recorded for THIS unknown is lifted by finish_completed_run), the ledger
                    # row settles failed, and the journal retires. Never re-fired.
                    current = get_job(params['job_id'])
                    if current is None:
                        journal.unlink(missing_ok=True)
                        continue
                    error = (f'Cron receipt expired: admission {params["request_id"]} stayed unknown '
                             f'for {scans} recovery scans; no re-execution. Whether side effects '
                             f'ran before the firer died is unknown.')
                    state = {'status': 'terminal', 'job': current,
                             'result': [False, f'# Cron Job: {params["job_id"]} (FAILED)\n\n{error}\n', '', error]}
                else:
                    continue
            success, output, answer, error = state['result']
            job = dict(state['job'], **(state.get('job_flags') or {}))
            job['execution_id'] = params['request_id']
            # The same result verdicts as the ordinary tail: an agent-declared [CRON_FAILURE] and a
            # blank answer are failures, whichever process books them.
            success, error, declared = _apply_agent_failure_marker(job, success, error, answer)
            delivery = _RunDelivery(job, success, error, agent_declared=declared)
            # The canonical receipt supplies the result; a dead scheduler's fire claim does not
            # authorize replay and must not prevent finishing its durable bookkeeping.
            fence = _FireOwnership(dict(job, fire_claim=None))
            # Receipt recovery is outside run_one_job's scoped execution context.
            # Install the owning profile scope while resolving delivery targets;
            # multiplex gateways must never fall back to another profile's env.
            with _fire_secret_scope():
                _save_compose_deliver(delivery, fence, answer, output, adapters=None, loop=None,
                                     verbose=False, execution_token=None)
            fail_empty_response(delivery, answer)
            if finish_completed_run(delivery, None, params['request_id'], recovered=True):
                _lift_pause(params['job_id'], record.get('pause_recorded'))
        except Exception:
            logging.getLogger(__name__).warning('Cron receipt recovery deferred: %s', journal, exc_info=True)
            _bound_deferred_retry(journal)
