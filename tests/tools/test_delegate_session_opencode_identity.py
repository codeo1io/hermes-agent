"""Fail-closed native OpenCode session identity across delegate restart.

This lives in a topical sibling because the original delegate_session test
module is above the repository's file-size health ratchet.
"""

import tools.delegate_session_tool as ds
from tests.tools.test_delegate_session_tool import (
    FakeOpenCodeClient,
    Parent,
    clean_sessions,
    payload,
)

__all__ = ["clean_sessions"]  # expose the imported autouse fixture to pytest


def test_opencode_new_session_and_restart_resume_keep_exact_native_identity(monkeypatch):
    """Fresh OpenCode handles are not native IDs; persisted resumes are."""

    class IdentityCheckingOpenCode(FakeOpenCodeClient):
        seen_native_at_start = []

        def start(self, *, timeout=30.0, stages=None):
            self.seen_native_at_start.append(self.native_session_id)
            if self.native_session_id is None:
                self.native_session_id = "ses_real_opencode_1"
            return {"sessionId": self.native_session_id}

    monkeypatch.setattr(ds, "OpenCodeClient", IdentityCheckingOpenCode)
    parent = Parent("opencode-restart-owner")
    first = payload(
        ds.delegate_session(action="start", backend="opencode", parent_agent=parent)
    )
    assert first["success"] is True
    assert first["native_session_id"] == "ses_real_opencode_1"
    assert IdentityCheckingOpenCode.seen_native_at_start == [None]
    sid = first["session_id"]
    assert ds._load_metadata(sid)["native_session_id"] == "ses_real_opencode_1"

    with ds._SESSION_LOCK:
        ds._SESSIONS.clear()  # simulate supervisor replacement, not a live process
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["success"] is True
    assert resumed["native_session_id"] == "ses_real_opencode_1"
    assert IdentityCheckingOpenCode.seen_native_at_start == [
        None,
        "ses_real_opencode_1",
    ]
