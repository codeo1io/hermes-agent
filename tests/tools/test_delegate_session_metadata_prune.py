"""Fail-closed pruning of durable native delegate-session metadata."""

import json
import os

import tools.delegate_session_tool as ds


def test_durable_metadata_prune_preserves_live_and_unknown_records(monkeypatch, tmp_path):
    """A busy cache must not erase a resumable native session's identity."""
    root = tmp_path / "delegate-sessions"
    root.mkdir()
    monkeypatch.setattr(ds, "_MAX_DURABLE_SESSIONS", 2)
    records = []
    for index, status in enumerate(("running", "idle", "closed", "closed")):
        path = root / f"session-{index}.json"
        path.write_text(json.dumps({"session_id": str(index), "status": status}))
        os.utime(path, (100 + index, 100 + index))
        records.append(path)

    ds._prune_durable_metadata(root)
    assert all(path.exists() for path in records)

    # A newer terminal record displaces only a terminal; active bindings
    # remain resumable even after the nominal cache count is exceeded.
    newer = root / "session-4.json"
    newer.write_text(json.dumps({"session_id": "4", "status": "closed"}))
    os.utime(newer, (104, 104))
    ds._prune_durable_metadata(root)
    assert records[0].exists() and records[1].exists()
    assert not records[2].exists()
    assert records[3].exists() and newer.exists()

    unknown = root / "session-unknown.json"
    unknown.write_text("not-json")
    os.utime(unknown, (99, 99))
    ds._prune_durable_metadata(root)
    assert unknown.exists()
