"""Dashboard REST surface of the routing-neutral per-task owner field.

Covers POST /tasks `owner`, PATCH /tasks/:id `owner` + `clear_owner`, the bulk
endpoints, the GET serialization, the archived refusal (400), and that a
transfer under a live claim leaves routing state untouched. The DB-layer
contracts live in ``tests/hermes_cli/test_kanban_owner.py``; the CLI surface in
``tests/hermes_cli/test_kanban_owner_cli.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


@pytest.fixture
def conn(kanban_home):
    c = kbc.connect()
    yield c
    c.close()


def _load_plugin_router():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_file = repo_root / "plugins" / "kanban" / "dashboard" / "plugin_api.py"
    assert plugin_file.exists(), f"plugin file missing: {plugin_file}"
    spec = importlib.util.spec_from_file_location(
        "hermes_dashboard_plugin_kanban_owner_test", plugin_file,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.router


@pytest.fixture
def client(kanban_home):
    app = FastAPI()
    app.include_router(_load_plugin_router(), prefix="/api/plugins/kanban")
    return TestClient(app)


def _create(client, **kwargs):
    body = {"title": "task", "assignee": "worker"}
    body.update(kwargs)
    r = client.post("/api/plugins/kanban/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()["task"]


def _get(client, tid: str) -> dict:
    r = client.get(f"/api/plugins/kanban/tasks/{tid}")
    assert r.status_code == 200, r.text
    return r.json()["task"]


# --- POST /tasks --------------------------------------------------------------


def test_create_accepts_and_returns_owner(client):
    task = _create(client, owner="alice")
    assert task["owner"] == "alice"


def test_create_without_owner_defaults_to_creator(client, conn):
    task = _create(client)
    # The dashboard creates as created_by="dashboard"; the write-time default
    # stamps the creator, so no lazy COALESCE is involved.
    assert task["owner"] == "dashboard"


# --- PATCH /tasks/:id ---------------------------------------------------------


def test_patch_transfers_owner_and_audits(client, conn):
    task = _create(client, owner="alice")
    r = client.patch(f"/api/plugins/kanban/tasks/{task['id']}", json={"owner": "bob"})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["owner"] == "bob"
    ev = [e for e in kb.list_events(conn, task["id"]) if e.kind == "owner_transferred"]
    assert ev and ev[-1].payload == {"from": "alice", "to": "bob"}


def test_patch_clear_owner_and_empty_string_both_clear(client):
    task = _create(client, owner="alice")
    r = client.patch(f"/api/plugins/kanban/tasks/{task['id']}", json={"clear_owner": True})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["owner"] is None

    r = client.patch(f"/api/plugins/kanban/tasks/{task['id']}", json={"owner": "carol"})
    assert r.status_code == 200, r.text
    # "" is the same explicit-clear signal as on assignee.
    r = client.patch(f"/api/plugins/kanban/tasks/{task['id']}", json={"owner": ""})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["owner"] is None


def test_patch_without_owner_leaves_it_alone(client):
    task = _create(client, owner="alice")
    r = client.patch(f"/api/plugins/kanban/tasks/{task['id']}", json={"priority": 3})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["owner"] == "alice"


def test_patch_owner_under_a_live_claim_is_routing_neutral(client, conn):
    task = _create(client, owner="alice")
    tid = task["id"]
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status = 'running', claim_lock = ?, consecutive_failures = 2, "
            "last_failure_error = 'boom' WHERE id = ?", ("cl-123", tid))
    r = client.patch(f"/api/plugins/kanban/tasks/{tid}", json={"owner": "bob"})
    assert r.status_code == 200, r.text
    row = conn.execute(
        "SELECT assignee, claim_lock, consecutive_failures, last_failure_error, status "
        "FROM tasks WHERE id = ?", (tid,)).fetchone()
    # Transfer succeeds mid-run AND every routing column is untouched.
    assert r.json()["task"]["owner"] == "bob"
    assert row["assignee"] == "worker"
    assert row["claim_lock"] == "cl-123"
    assert row["consecutive_failures"] == 2
    assert row["last_failure_error"] == "boom"
    assert row["status"] == "running"


def test_patch_owner_on_archived_task_is_a_400(client, conn):
    task = _create(client, owner="alice")
    assert kb.archive_task(conn, task["id"])
    r = client.patch(f"/api/plugins/kanban/tasks/{task['id']}", json={"owner": "bob"})
    assert r.status_code == 400
    assert "archived" in r.json()["detail"]


# --- POST /tasks/bulk ---------------------------------------------------------


def test_bulk_sets_and_clears_owner(client):
    t1, t2 = _create(client, owner="alice"), _create(client)
    r = client.post(
        "/api/plugins/kanban/tasks/bulk",
        json={"ids": [t1["id"], t2["id"]], "owner": "team-a"},
    )
    assert r.status_code == 200, r.text
    assert all(entry["ok"] for entry in r.json()["results"])
    assert _get(client, t1["id"])["owner"] == "team-a"
    assert _get(client, t2["id"])["owner"] == "team-a"

    r = client.post(
        "/api/plugins/kanban/tasks/bulk",
        json={"ids": [t1["id"]], "clear_owner": True},
    )
    assert r.status_code == 200, r.text
    assert _get(client, t1["id"])["owner"] is None
    assert _get(client, t2["id"])["owner"] == "team-a"


def test_bulk_owner_refusal_on_archived_is_reported_not_raised(client, conn):
    task = _create(client, owner="alice")
    assert kb.archive_task(conn, task["id"])
    r = client.post(
        "/api/plugins/kanban/tasks/bulk",
        json={"ids": [task["id"]], "owner": "bob"},
    )
    assert r.status_code == 200, r.text
    entry = r.json()["results"][0]
    assert entry["ok"] is False
    assert "archived" in entry["error"]
