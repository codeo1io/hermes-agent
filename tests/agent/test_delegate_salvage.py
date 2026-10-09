"""Abort-salvage envelope for delegated turns.

Finding family ``cognitive-continuity.prevention.6c3867f4ffd9`` (Maestro A4,
a2235ba78b24): when a delegated turn dies mid-flight — provider abort, stall
kill, transport death — the v4 durable metadata banked WHY the turn died but
not WHAT it produced. The 2026-10-07/08 abort specimens (delegate attempts
7befc774, 6ae29ca9: heartbeats flowing, then flat-timeout death) lost every
minute of work product, leaving only heartbeat events behind.

The contract under test, driven through the real ``_run_turn`` failure path
with a fake native client (no live child process):

- a dying turn banks a bounded ``salvage_tail`` (transcript tail + last tool
  calls) into the durable metadata file, alongside — never instead of — the
  failure evidence (``error_class``);
- the excerpt obeys its bounds (message count, per-message chars, total
  chars, tool-call arg excerpts) and flags when it truncated;
- a client whose salvage fetch raises or returns junk degrades silently: no
  salvage evidence, failure evidence intact, no exception escapes the turn
  handler.
"""

from __future__ import annotations

import json
import time

import pytest

from tools import delegate_session_tool
from tools.delegate_session_tool import _metadata_path, _run_turn

# Salvage tail bounds wired in _run_turn (agent/delegate_salvage.py
# defaults): 8 messages, 4000 chars per message, 24000 chars total.
TAIL_MESSAGES = 8
PER_MESSAGE_CHARS = 4000
TOTAL_CHARS = 24000
LONG_TEXT_LEN = 6000  # exceeds the per-message bound on purpose


class FakeLedger:
    """Hermetic stand-in for the delegate-health ledger (fail-open pins)."""

    def check(self, key):
        return None

    def record_success(self, key):
        pass

    def record_failure(self, key, error_class):
        pass


class FakeClient:
    """Native-client stand-in whose turn dies with a transcript behind it."""

    def __init__(self, transcript):
        self._transcript = transcript

    def run_session_prompt(self, message, timeout_seconds=None):
        raise RuntimeError("This operation was aborted")

    def get_messages(self, *, timeout=30.0, stages=None):
        return list(self._transcript)


@pytest.fixture(autouse=True)
def _fast_observer(monkeypatch):
    # The observer loop polls every 5s by default; pin it tight so the
    # daemon thread exits promptly after each turn (the module documents
    # this injection point).
    monkeypatch.setattr(delegate_session_tool, "_OBSERVER_POLL_S", 0.05)


def _record(tmp_path, client, session_id="salvage-t1"):
    now = time.time()
    return {
        "session_id": session_id,
        "native_session_id": session_id,
        "backend": "pi",
        "model": "",
        "client": client,
        "owner": "tests/agent/test_delegate_salvage.py",
        "owner_scope": "test",
        "cwd": str(tmp_path),
        "created_at": now,
        "updated_at": now,
        "status": "idle",
        "consecutive_failures": 0,
        # Pin the durable store + provider ledger to the test sandbox so
        # nothing resolves against a real profile home.
        "_scope_store_root": tmp_path,
        "_scope_ledger": FakeLedger(),
    }


def _durable_file(tmp_path, session_id="salvage-t1"):
    path = _metadata_path(session_id, root=tmp_path)
    return json.loads(path.read_text(encoding="utf-8"))


def test_failed_turn_banks_bounded_salvage_tail(tmp_path):
    """A turn that dies mid-flight banks its work product, bounded.

    The specimen: a transcript with more messages than the tail bound, one
    over-long message, and final tool calls — then the turn aborts. The
    durable file must carry the LAST messages and tool calls (never the
    head), every text within bounds, the truncation flagged, and the failure
    evidence still banked alongside.
    """
    transcript = [
        {"role": "user" if i % 2 else "assistant", "text": f"work product {i}"}
        for i in range(12)
    ]
    # Position 9 (survives inside the 8-message tail as index 4) carries
    # more text than the per-message bound allows.
    transcript[9]["text"] = "partial analysis " + "x" * LONG_TEXT_LEN
    transcript.append(
        {
            "role": "assistant",
            "tool_calls": [
                {"name": "edit", "arguments": {"path": "agent/x.py"}},
                {"function": {"name": "bash", "arguments": "git status"}},
            ],
        }
    )
    client = FakeClient(transcript)
    record = _record(tmp_path, client)

    before = time.time()
    _run_turn(record, "finish the phase", timeout=5.0)

    data = _durable_file(tmp_path)
    salvage = data.get("salvage_tail")
    assert isinstance(salvage, dict), "dying turn banked no salvage tail"
    # Salvage rides WITH the failure evidence, never instead of it.
    assert data["error_class"]
    assert data["last_turn_outcome"] == "error"
    assert isinstance(salvage["captured_at"], float)
    assert before <= salvage["captured_at"] <= time.time() + 5.0

    # Bounding relationship: the tail keeps the LAST 8 of 13 messages, so
    # the head is dropped and the excerpt is flagged truncated.
    messages = salvage["messages"]
    assert len(messages) == TAIL_MESSAGES
    assert salvage["truncated"] is True
    expected_roles = [
        "user" if i % 2 else "assistant" for i in range(5, 13)
    ]
    assert [m["role"] for m in messages] == expected_roles
    # The over-long message is cut at the per-message bound, head kept.
    assert messages[4]["text"] == transcript[9]["text"][:PER_MESSAGE_CHARS]
    assert len(messages[4]["text"]) == PER_MESSAGE_CHARS
    assert all(len(m["text"]) <= PER_MESSAGE_CHARS for m in messages)
    assert sum(len(m["text"]) for m in messages) <= TOTAL_CHARS
    # Work product actually survives — the whole point of the envelope.
    assert messages[3]["text"] == "work product 8"

    # Last tool calls: names plus bounded argument excerpts.
    calls = salvage["last_tool_calls"]
    assert [c["name"] for c in calls] == ["edit", "bash"]
    assert calls[0]["args"] == '{"path": "agent/x.py"}'
    assert calls[1]["args"] == "git status"
    assert all(len(c["args"]) <= 400 for c in calls)


@pytest.mark.parametrize(
    "salvage_result",
    [
        pytest.param(RuntimeError("pi get_messages failed"), id="raises"),
        pytest.param({"unexpected": "shape"}, id="junk-dict"),
        pytest.param([], id="empty-transcript"),
    ],
)
def test_salvage_degrades_silently(tmp_path, salvage_result):
    """A broken salvage fetch never masks the banked failure evidence."""

    class BrokenSalvageClient(FakeClient):
        def get_messages(self, *, timeout=30.0, stages=None):
            if isinstance(salvage_result, Exception):
                raise salvage_result
            return salvage_result

    record = _record(tmp_path, BrokenSalvageClient([]), session_id="salvage-t2")
    # The turn handler must return normally — no exception escapes it.
    _run_turn(record, "finish the phase", timeout=5.0)

    data = _durable_file(tmp_path, session_id="salvage-t2")
    assert data.get("salvage_tail") is None
    assert data["error_class"]
    assert data["last_turn_outcome"] == "error"
