"""An unfenced ``mark_job_run`` must never clear a LIVE fire claim.

2026-11-28 defect specimen (execution 72b2fef174f5477394e2218509e91272, job 9817d7ce4a90):
the receipt-recovery path (``reconcile_pending`` -> ``finish_completed_run(fire_owner=None)``)
and the stale-inflight sweep (``_record_stale_release``) mark the job WITHOUT owning the
current fire claim. While a successor fire was legitimately in flight — its claim refreshed
every 60s by the firer's heartbeat — the recovered receipt of a long-dead earlier fire landed
an unfenced ``mark_job_run``, which sets ``job["fire_claim"] = None`` and stamps
``last_status``/``last_run_at``/``next_run_at`` under the live run. The firer's next heartbeat
then read "claim gone", latched ``fire claim ownership lost; interrupting stale run``,
forwarded a cancel into the owning gateway session, and the healthy 4h15m turn was aborted
mid-tool and its result discarded ('Fire claim ownership lost; stale result was discarded.').

The owner-fenced form (``expected_fire_owner``) is the authority; an UNFENCED mark is a
non-owning writer and must refuse to touch a job whose claim is still live.
"""
from datetime import timedelta

import pytest


@pytest.fixture
def temp_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME so jobs.json never touches the real store."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


def test_unfenced_mark_cannot_clear_a_live_fire_claim(temp_home):
    from cron import jobs

    job = jobs.create_job(prompt="x", schedule="every 5m", name="t")
    jid = job["id"]
    claimed = jobs.claim_job_for_fire(jid, return_job=True)
    assert isinstance(claimed, dict)
    before = jobs.get_job(jid)
    live_owner = before["fire_claim"]["by"]
    assert live_owner

    marked = jobs.mark_job_run(jid, True, None)

    assert marked is False
    after = jobs.get_job(jid)
    assert isinstance(after["fire_claim"], dict)
    assert after["fire_claim"]["by"] == live_owner
    assert after["last_status"] == before["last_status"]
    assert after["last_run_at"] == before["last_run_at"]


def test_unfenced_mark_still_lands_once_no_live_claim_holds(temp_home):
    """Receipt recovery for a dead firer must keep booking once nothing live owns the job."""
    from cron import jobs

    job = jobs.create_job(prompt="x", schedule="every 5m", name="t")
    jid = job["id"]
    stale_at = (jobs._hermes_now() - timedelta(seconds=3600)).isoformat()

    def _install_dead_claim(jobs_list, _i, record):
        record["fire_claim"] = {"at": stale_at, "by": "dead-firer:1:abc"}
        jobs.save_jobs(jobs_list)
        return True

    assert jobs._with_job(jid, _install_dead_claim) is True

    assert jobs.mark_job_run(jid, True, None) is True
    settled = jobs.get_job(jid)
    assert settled["fire_claim"] is None
    assert settled["last_status"] == "ok"


def test_reconcile_receipt_recovery_keeps_a_live_successor_fire_claim(temp_home, monkeypatch):
    """The exact incident path, end to end: an orphan admission journal whose firer is dead is
    recovered while a successor fire legitimately holds the claim. Recovery retires the orphan
    receipt but must leave the successor's claim — and its job state — untouched."""
    from contextlib import asynccontextmanager
    import json

    from cron import executions, jobs, scheduler_authority
    from hermes_cli import gateway_client

    job = jobs.create_job(prompt="report", schedule="every 30m", deliver="local")
    jid = job["id"]
    # The successor fire: claimed now, its firer heartbeats while the session-side turn runs.
    claimed = jobs.claim_job_for_fire(jid, return_job=True)
    assert isinstance(claimed, dict)
    live_owner = jobs.get_job(jid)["fire_claim"]["by"]

    # The orphan: an earlier fire of the same job whose firer process is long dead and whose
    # receipt journal still awaits recovery.
    orphan = executions.create_execution(jid, source="test")
    executions.mark_execution_running(orphan["id"])
    with executions._transaction() as conn:
        conn.execute(
            "UPDATE executions SET process_id=?,pid=? WHERE id=?",
            ("old-owner", 999999, orphan["id"]))
    params = {"job_id": jid, "request_id": orphan["id"], "extra_prompt": None}
    journal = scheduler_authority.journal_path(jid, orphan["id"])
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({"params": params, "receipt": None}))

    class Peer:
        async def rpc(self, method, **p):
            assert method == "cron.recover"
            return {"status": "terminal", "job": job,
                    "result": [True, "document", "answer", None]}

    @asynccontextmanager
    async def connected():
        yield Peer()

    monkeypatch.setattr(gateway_client, "connect_gateway", connected)

    scheduler_authority.reconcile_pending()

    survived = jobs.get_job(jid)["fire_claim"]
    assert isinstance(survived, dict) and survived["by"] == live_owner
    # The orphan receipt itself still retires: recovery is deferred only for the job record.
    assert not journal.exists()
