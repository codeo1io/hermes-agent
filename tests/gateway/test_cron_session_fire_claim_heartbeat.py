"""The gateway session keeps its admitted fire's claim alive for the whole turn.

A gateway-admitted cron fire is executed by the OWNER session process, not by the firing
scheduler: the firer heartbeats ``job["fire_claim"]`` only while its own process lives. If the
firer dies (2026-11-28 specimen: the 4h15m turn of job 9817d7ce4a90), the claim's TTL is the
only thing standing between the in-flight turn and a takeover firing of the same job — a
turn that outlives the TTL gets double-run (once mid-flight, once by the successor fire)
unless its process keeps the lease fresh.

The session side must therefore (a) heartbeat the frozen claim for the WHOLE admitted turn,
and (b) surface a genuine ownership takeover through the same cancel seam an operator's
``cron.cancel`` reaches — the turn is interrupted, not silently orphaned.
"""
import asyncio
import json
import threading
import time
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest

from cron import jobs
from gateway import run, session_cron
from gateway.session_authority import LiveSession, SessionAuthority, admission_row
from gateway.session_contract import SessionRef
from tests.fixtures.storage_seed import seed_session
from tests.gateway.fixtures.storage_handles import close_storage_handles, storage_handle


def _install_claim(jid, claim):
    jobs._with_job(jid, lambda jobs_list, _i, record: (
        record.__setitem__("fire_claim", claim), jobs.save_jobs(jobs_list))[1])
    return jobs.get_job(jid)["fire_claim"]


@pytest.fixture
def cadence(monkeypatch):
    """Shrink the heartbeat constants so takeover is observed in milliseconds, not minutes."""
    from cron import scheduler
    monkeypatch.setattr(scheduler, "_RUN_CLAIM_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(scheduler, "_FIRE_CLAIM_MISS_CONFIRM_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "_FIRE_CLAIM_HEARTBEAT_GRACE_SECONDS", 1.0)
    return scheduler


def test_session_run_heartbeats_its_fire_claim_and_aborts_on_takeover(
        tmp_path, monkeypatch, cadence):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    db = storage_handle(tmp_path)
    seed_session(db, "s", "cron")
    authority = SessionAuthority(
        SimpleNamespace(_draining=False), profile_id="p", instance_id="test",
        epoch=db.runtime.begin_epoch(instance_id="test"), persistence=storage_handle(tmp_path))
    authority.sessions["s"] = LiveSession(
        SimpleNamespace(platform=None, user_id="cron-owner"), "route")
    ref = SessionRef("p", "s")
    monkeypatch.setattr(run, "_profile_runtime_scope", lambda home: nullcontext())

    job = jobs.create_job(prompt="report", schedule="every 30m", name="r")
    jid = job["id"]
    firer_owner = "firer-owner:17:aaa"
    installed_at = (jobs._hermes_now() - timedelta(seconds=60)).isoformat()
    _install_claim(jid, {"at": installed_at, "by": firer_owner})

    entered = threading.Event()
    observed = {}

    def run_job(job, *, extra_prompt, execution_id, cancel_event):
        entered.set()
        deadline = time.monotonic() + 10.0
        while not cancel_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.02)
        observed["cancelled"] = cancel_event.is_set()
        return (True, "doc", "answer", None)

    monkeypatch.setattr(cadence, "run_job", run_job)

    with db:
        db.admissions.admit(epoch=authority.epoch, principal_id="cron-owner", session_id="s",
                            request_id="cron:" + jid + ":fire", payload={"text": ""})
        row = admission_row(db.admissions.claim(epoch=authority.epoch, session_id="s"))
    frozen_job = {"id": jid, "prompt": "report", "name": "r",
                  "schedule": {"kind": "interval", "minutes": 30},
                  "fire_claim": {"at": installed_at, "by": firer_owner}}
    policy = SimpleNamespace(request_json=json.dumps({
        "extra_prompt": None, "request_id": "cron:" + jid + ":fire", "cron_job": frozen_job}))

    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.__setitem__(
            "final", asyncio.run(session_cron.execute(authority, ref, row, policy))),
        daemon=True)
    worker.start()
    try:
        assert entered.wait(10), "owner-side run never started"

        # (a) the lease is refreshed while the turn runs, far past the age the frozen claim had.
        refreshed = None
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            claim_now = jobs.get_job(jid)["fire_claim"]
            if claim_now and claim_now.get("at") != installed_at:
                refreshed = claim_now["at"]
                break
            time.sleep(0.02)
        assert refreshed, "the fire claim was never refreshed while the turn ran"
        assert claim_now["by"] == firer_owner

        # (b) a genuine takeover rewrites the owner; the turn must see it through the cancel seam.
        _install_claim(jid, {"at": refreshed, "by": "successor-owner:22:bbb"})
        worker.join(15)
        assert not worker.is_alive(), "the turn was not interrupted by the takeover"
        assert outcome["final"] == "answer"
        assert observed["cancelled"] is True
    finally:
        worker.join(10)


def test_session_run_without_a_fire_claim_still_runs_plain(tmp_path, monkeypatch, cadence):
    """Fires admitted without a durable claim (single-machine) run unchanged."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    db = storage_handle(tmp_path)
    seed_session(db, "s", "cron")
    authority = SessionAuthority(
        SimpleNamespace(_draining=False), profile_id="p", instance_id="test",
        epoch=db.runtime.begin_epoch(instance_id="test"), persistence=storage_handle(tmp_path))
    authority.sessions["s"] = LiveSession(
        SimpleNamespace(platform=None, user_id="cron-owner"), "route")
    ref = SessionRef("p", "s")
    monkeypatch.setattr(run, "_profile_runtime_scope", lambda home: nullcontext())

    seen = {}

    def run_job(job, *, extra_prompt, execution_id, cancel_event):
        seen["cancel_initially_set"] = cancel_event.is_set()
        seen["claim"] = job.get("fire_claim")
        return (True, "doc", "answer", None)

    monkeypatch.setattr(cadence, "run_job", run_job)

    with db:
        db.admissions.admit(epoch=authority.epoch, principal_id="cron-owner", session_id="s",
                            request_id="cron:job:fire", payload={"text": ""})
        row = admission_row(db.admissions.claim(epoch=authority.epoch, session_id="s"))
    policy = SimpleNamespace(request_json=json.dumps({
        "extra_prompt": None, "request_id": "cron:job:fire", "cron_job": {"id": "job", "prompt": "x"}}))

    assert asyncio.run(session_cron.execute(authority, ref, row, policy)) == "answer"
    assert seen == {"cancel_initially_set": False, "claim": None}
