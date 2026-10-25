"""Receipt recovery delivery must execute inside the owning profile scope."""
from contextlib import asynccontextmanager, contextmanager
import json

from cron import executions, jobs, scheduler, scheduler_authority
from hermes_cli import gateway_client


def test_terminal_receipt_delivery_reinstalls_profile_scope(tmp_path, monkeypatch):
    active = []
    delivered = []

    @contextmanager
    def owning_scope():
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    def save_delivery(*args, **kwargs):
        assert active, "recovered delivery ran outside its profile context"
        delivered.append(args[0].job["id"])

    class Peer:
        async def rpc(self, method, **params):
            return {
                "status": "terminal",
                "job": jobs.get_job(params["job_id"]),
                "result": [True, "recovered output", "recovered answer", None],
            }

    @asynccontextmanager
    async def connect():
        yield Peer()

    monkeypatch.setattr(gateway_client, "connect_gateway", connect)
    monkeypatch.setattr(scheduler, "_fire_secret_scope", owning_scope)
    monkeypatch.setattr(scheduler, "_save_compose_deliver", save_delivery)
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="telegram")
        fire = executions.create_execution(job["id"], source="test")["id"]
        with executions._transaction() as conn:
            conn.execute("UPDATE executions SET process_id=?,pid=? WHERE id=?",
                         ("departed-owner", 999999, fire))
        journal = scheduler_authority.journal_path(job["id"], fire)
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({
            "params": {"job_id": job["id"], "request_id": fire,
                       "extra_prompt": None},
            "receipt": None,
        }))
        scheduler_authority.reconcile_pending()
        assert delivered == [job["id"]]
        assert not active
        assert not journal.exists()
