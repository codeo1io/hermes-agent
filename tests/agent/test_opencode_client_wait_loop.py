"""OpenCode delegate-session client wait-loop regression tests.

Reproduces the orchestrator "turn ended without an assistant text reply"
failures (2026-08-30): with slow-thinking models (glm-5.3, 20-40s from message
row creation to first visible part), a fresh assistant message appears as a
BARE ``step-start`` row — no text, no tool call — for tens of seconds. The old
completion heuristic (transcript snapshot stable + any parts at all + nothing
running) fired inside that window and declared the turn empty while the model
was still generating. These tests pin the contract:

- a bare step-start row with no ``info.time.completed`` is NOT a reply and
  must keep the wait loop waiting;
- a reply that is only an injected ``<system-reminder>`` jail notice is NOT a
  reply either.

Hermetic: a scripted fake transport serves canned transcripts; no server.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pytest

from agent.opencode_client import OpenCodeClient


def _msg(mid: str, role: str, parts: list[dict], completed: bool = True) -> dict:
    info: dict[str, Any] = {
        "id": mid,
        "role": role,
        "time": {"created": int(mid[-6:])},
    }
    if completed:
        info["time"]["completed"] = int(mid[-6:]) + 1
    return {"info": info, "parts": parts}


class _ScriptedTransport:
    """Serves a scripted transcript; each state repeats for a wall-clock span.

    Entries are ``(state, hold_seconds)``: the state is served on every GET
    until its hold elapses (mimicking a slow-thinking model whose bare
    step-start row sits unchanged for tens of seconds), then the next entry
    becomes current. The final entry repeats forever.
    """

    def __init__(self, script: "list[tuple[list[dict], float]]"):
        self._script = list(script)
        self._t0: Optional[float] = None
        self._prompted = False
        self.requests: "list[tuple[str, str]]" = []

    def _current(self) -> "list[dict]":
        if self._t0 is None:
            # Pre-prompt: the baseline fetch always sees the first state.
            return self._script[0][0]
        elapsed = time.monotonic() - self._t0
        for state, hold in self._script:
            if elapsed <= hold:
                return state
            elapsed -= hold
        return self._script[-1][0]

    def request(self, method: str, path: str, body: Optional[dict] = None) -> "tuple[int, str]":
        import json as _json

        self.requests.append((method, path))
        base_path = path.split("?")[0]
        if base_path.startswith("/session/") and base_path.endswith("/message"):
            if method == "GET":
                state = self._current()
                if not self._prompted:
                    # Baseline fetch (pre-prompt): serve the first state only.
                    self._prompted = True
                return 200, _json.dumps(state)
            return 204, ""
        if base_path.startswith("/session/") and base_path.endswith("/prompt_async"):
            # POST prompt_async: drop the baseline state, start the clock.
            self._t0 = time.monotonic()
            self._script.pop(0)
            return 204, ""
        if base_path == "/session" and method == "POST":
            return 200, _json.dumps({"id": "ses_scripted1234"})
        if base_path.startswith("/question"):
            return 200, "[]"
        if base_path.startswith("/event"):
            return 200, ""
        return 200, "{}"


def _client(script: "list[tuple[list[dict], float]]") -> OpenCodeClient:
    transport = _ScriptedTransport(script)
    client = OpenCodeClient(
        session_id="sess-test",
        session_name="test",
        acp_cwd="/tmp",
        transport_factory=lambda cwd: transport,
    )
    client.native_session_id = "ses_scripted1234"
    return client


def test_bare_step_start_keeps_waiting_then_returns_late_reply():
    """The exact 14:29 failure: stable bare step-start row mid-generation.

    The bare (incomplete) assistant row persists 12s — far past the ~5s
    stability window — then the real reply lands. Pre-fix, the client
    declared the turn empty inside that window.
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    bare = base + [_msg("msg_live_000002", "assistant", [{"type": "step-start"}], completed=False)]
    done = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "Unit status: all green."},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        )
    ]
    script = [(base, 0.05), (bare, 12.0), (done, 999.0)]
    client = _client(script)
    result = client.run_session_prompt("go", timeout_seconds=60, poll_interval=0.02)
    assert result["text"] == "Unit status: all green."


def test_system_reminder_only_reply_is_not_a_reply():
    """Death 1: the guard jail made the model's only text a system-reminder."""
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    jailed = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {
                    "type": "text",
                    "text": "<system-reminder>\nOnly tools in the always-allowed set are permitted right now.\n</system-reminder>",
                },
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        )
    ]
    script = [(base, 0.05), (jailed, 999.0)]
    client = _client(script)
    with pytest.raises(RuntimeError, match="without an assistant text reply"):
        client.run_session_prompt("go", timeout_seconds=10, poll_interval=0.02)


def test_completed_tool_then_text_returns_text():
    """Normal dispatch step: tool part lands, then final text — returns text."""
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    with_tool = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "tool", "state": {"status": "completed"}, "tool": "task"},
                {"type": "step-finish", "reason": "tool-calls"},
            ],
            completed=True,
        )
    ]
    with_text = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "tool", "state": {"status": "completed"}, "tool": "task"},
                {"type": "step-finish", "reason": "tool-calls"},
            ],
            completed=True,
        ),
        _msg(
            "msg_live_000003",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "Done: 6 units implemented."},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        ),
    ]
    script = [(base, 0.05), (with_tool, 3.0), (with_text, 999.0)]
    client = _client(script)
    result = client.run_session_prompt("go", timeout_seconds=30, poll_interval=0.02)
    assert result["text"] == "Done: 6 units implemented."


def test_immediate_reply_returns_quickly():
    """Fast happy path: reply already there on first post-prompt fetch."""
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    done = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "OK."},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        )
    ]
    script = [(base, 0.05), (done, 999.0)]
    client = _client(script)
    result = client.run_session_prompt("go", timeout_seconds=15, poll_interval=0.02)
    assert result["text"] == "OK."
