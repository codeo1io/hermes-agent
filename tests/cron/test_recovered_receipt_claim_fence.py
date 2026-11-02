"""A dead firer's receipt cannot clobber a newer canonical cron execution."""
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json

from cron import executions, jobs, scheduler_authority
from hermes_cli import gateway_client


def _terminal_peer(monkeypatch, job, answer="verified answer"):
    class Peer:
        async def rpc(self, method, **params):
            return {"status": "terminal", "job": job,
                    "result": [True, "document", answer, None]}

    @asynccontextmanager
    async def connected():
        yield Peer()

    monkeypatch.setattr(gateway_client, "connect_gateway", connected)


def _old_receipt(job):
    old = executions.create_execution(job["id"], source="test")
    executions.mark_execution_running(old["id"])
    with executions._transaction() as conn:
        conn.execute("UPDATE executions SET process_id=?,pid=? WHERE id=?",
                     ("dead-owner", 999999, old["id"]))
    journal = scheduler_authority.journal_path(job["id"], old["id"])
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({
        "params": {"job_id": job["id"], "request_id": old["id"], "extra_prompt": None},
        "receipt": None,
    }))
    return old, journal


def test_older_receipt_cannot_erase_newer_live_claim(tmp_path, monkeypatch):
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        old, journal = _old_receipt(job)
        executions.create_execution(job["id"], source="test")
        owner = "newer-live-owner"
        jobs.update_job(job["id"], {"fire_claim": {
            "by": owner, "at": datetime.now(UTC).isoformat()}})
        _terminal_peer(monkeypatch, job)
        before = jobs.get_job(job["id"])
        scheduler_authority.reconcile_pending()
        after = jobs.get_job(job["id"])
        assert after["fire_claim"]["by"] == owner
        assert after["repeat"]["completed"] == before["repeat"]["completed"]
        assert executions.get_execution(old["id"])["status"] == "completed"
        assert not journal.exists()


def test_recovery_defers_when_live_claim_precedes_new_execution_row(tmp_path, monkeypatch):
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        old, journal = _old_receipt(job)
        owner = "newer-claim-before-ledger-row"
        jobs.update_job(job["id"], {"fire_claim": {
            "by": owner, "at": datetime.now(UTC).isoformat()}})
        _terminal_peer(monkeypatch, job)
        scheduler_authority.reconcile_pending()
        assert jobs.get_job(job["id"])["fire_claim"]["by"] == owner
        assert executions.get_execution(old["id"])["status"] == "running"
        assert journal.exists()


def test_claim_created_during_recovery_delivery_is_fenced(tmp_path, monkeypatch):
    from cron import scheduler
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        old, journal = _old_receipt(job)
        _terminal_peer(monkeypatch, job)
        owner = "new-owner-during-delivery"

        def acquire_claim(*args, **kwargs):
            jobs.update_job(job["id"], {"fire_claim": {
                "by": owner, "at": datetime.now(UTC).isoformat()}})

        monkeypatch.setattr(scheduler, "_save_compose_deliver", acquire_claim)
        scheduler_authority.reconcile_pending()
        assert jobs.get_job(job["id"])["fire_claim"]["by"] == owner
        assert executions.get_execution(old["id"])["status"] == "running"
        assert journal.exists()


def test_superseded_blank_receipt_is_failed_not_success(tmp_path, monkeypatch):
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        old, journal = _old_receipt(job)
        executions.create_execution(job["id"], source="test")
        _terminal_peer(monkeypatch, job, answer=" ")
        scheduler_authority.reconcile_pending()
        assert executions.get_execution(old["id"])["status"] == "failed"
        assert jobs.get_job(job["id"])["repeat"]["completed"] == 0
        assert not journal.exists()


def test_older_receipt_cannot_override_newer_terminal_status(tmp_path, monkeypatch):
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        old, journal = _old_receipt(job)
        newer = executions.create_execution(job["id"], source="test")
        owner = "newer-live-owner"
        jobs.update_job(job["id"], {"fire_claim": {
            "by": owner, "at": datetime.now(UTC).isoformat()}})
        assert jobs.mark_job_run(job["id"], False, "newer failed",
                                 expected_fire_owner=owner, execution_id=newer["id"])
        executions.finish_execution(newer["id"], success=False, error="newer failed")
        _terminal_peer(monkeypatch, job)
        before = jobs.get_job(job["id"])
        scheduler_authority.reconcile_pending()
        after = jobs.get_job(job["id"])
        assert after["last_status"] == "error"
        assert after["repeat"]["completed"] == before["repeat"]["completed"]
        assert executions.get_execution(old["id"])["status"] == "completed"
        assert not journal.exists()
