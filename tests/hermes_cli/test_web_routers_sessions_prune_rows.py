"""REST prune dry-run rows must carry the dimensions the filter selected on.

``POST /api/sessions/prune`` with ``min_cost``/``min_tokens`` selected rows on cost/token
budgets, but the response rows exposed neither — the dashboard confirm dialog was asked to
approve a cost-budget deletion without a single cost figure (upstream #133013, REST half).
Mirrors the CLI-side contract in ``test_sessions_prune_preview_dims.py``.
"""

import pytest


class _StubDB:
    """Just enough of the session store for the prune dry-run path; serves fixed rows."""

    def __init__(self, rows):
        self._rows = rows

    def count_open_prune_matches(self, **_filters):
        return 0

    def list_prune_candidates(self, **_filters):
        return self._rows

    def prune_sessions(self, **_kwargs):
        return 0

    def delete_sessions(self, ids):
        return len(ids)

    def delete_empty_sessions(self):
        return 0

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")
    from hermes_cli import web_server, web_server_sessions

    rows = [{
        "id": "20260101_000000_aaaaaa", "source": "cli", "title": "budget run",
        "model": "openrouter/auto", "started_at": 1_700_000_000.0,
        "last_active": 1_700_000_100.0, "message_count": 7,
        "tokens": 12_345, "cost_usd": 5.25,
    }]
    monkeypatch.setattr(
        web_server_sessions, "_open_session_db_for_profile",
        lambda profile, *, read_only: _StubDB(rows))
    c = TestClient(web_server.app)
    c.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return c


def test_prune_dry_run_rows_expose_tokens_and_cost(client):
    resp = client.post("/api/sessions/prune", json={"dry_run": True, "min_cost": 1.0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["removed"] == 0
    assert body["matched"] == 1
    (row,) = body["sessions"]
    assert row["tokens"] == 12_345  # the value the min_tokens/max_tokens filters select on
    assert row["cost_usd"] == pytest.approx(5.25)  # the value the min_cost/max_cost filters select on
