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
  reply either;
- a text part that EXISTS but is EMPTY (glm-5.3 creates it before streaming
  content into it) is NOT a reply either — the stable-window exit must not
  fire while the only text evidence is an empty part (the 2026-10-24
  01:02:59Z dev-002 failure: the client raised 3.7s before the text filled);
- a turn that genuinely ends with no assistant text must ABORT the native
  session on exit so the server-side agent stops spending on a detached
  session (dev-002 kept generating for 12+ minutes after the client left).

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

    def __init__(self, script: list[tuple[list[dict], float]]):
        self._script = list(script)
        self._t0: Optional[float] = None
        self._prompted = False
        self.prompt_body: Optional[dict] = None
        self.requests: list[tuple[str, str]] = []

    def _current(self) -> list[dict]:
        if self._t0 is None:
            # Pre-prompt: the baseline fetch always sees the first state.
            return self._script[0][0]
        elapsed = time.monotonic() - self._t0
        for state, hold in self._script:
            if elapsed <= hold:
                return state
            elapsed -= hold
        return self._script[-1][0]

    def request(self, method: str, path: str, body: Optional[dict] = None) -> tuple[int, str]:
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
            self.prompt_body = body
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


def _client(script: list[tuple[list[dict], float]]) -> OpenCodeClient:
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


def test_stable_window_empty_text_part_waits_for_fill():
    """The exact dev-002 2026-10-24 01:02:59Z failure, byte-level.

    glm-5.3 creates the assistant text part EMPTY (01:02:46.367Z), then goes
    quiet while a subagent tool runs; the transcript is stable from
    01:02:48.709Z, so the ~10s stability window elapsed at 01:02:58.7Z and the
    old loop raised at 01:02:59.052Z — 3.7s before the text content streamed
    into the SAME part at 01:03:02.901Z. An empty text part is a streaming
    placeholder, NOT a reply: the stable exit must not fire while the only
    text evidence is empty.
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    empty = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "reasoning", "text": "Parsing the dispatch."},
                {"type": "text", "text": ""},
                {"type": "tool", "state": {"status": "completed"}, "tool": "ctx_search"},
            ],
            completed=False,
        )
    ]
    filled = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "reasoning", "text": "Parsing the dispatch."},
                {"type": "text", "text": "Dispatch received. Reading the work-order contract."},
                {"type": "tool", "state": {"status": "completed"}, "tool": "ctx_search"},
                {"type": "tool", "state": {"status": "pending"}, "tool": "task"},
            ],
            completed=False,
        )
    ]
    script = [(base, 0.05), (empty, 12.0), (filled, 999.0)]
    client = _client(script)
    result = client.run_session_prompt("go", timeout_seconds=60, poll_interval=0.02)
    assert result["text"].startswith("Dispatch received.")


def test_empty_reply_exit_aborts_native_session():
    """A turn that ends with no assistant text must abort the native session.

    dev-002 kept generating server-side for 12+ minutes after the client
    detached with RuntimeError: the bare raise left the OpenCode agent
    spending on a session nobody was watching (it eventually asked a native
    question no client would ever answer).
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    dead = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": ""},
                {"type": "tool", "state": {"status": "completed"}, "tool": "ctx_search"},
                {"type": "step-finish", "reason": "tool-calls"},
            ],
            completed=True,
        )
    ]
    script = [(base, 0.05), (dead, 999.0)]
    transport = _ScriptedTransport(script)
    client = OpenCodeClient(
        session_id="sess-test",
        session_name="test",
        acp_cwd="/tmp",
        transport_factory=lambda cwd: transport,
    )
    client.native_session_id = "ses_scripted1234"
    with pytest.raises(RuntimeError):
        client.run_session_prompt("go", timeout_seconds=8, poll_interval=0.02)
    assert any(
        method == "POST" and path.split("?")[0] == "/session/ses_scripted1234/abort"
        for method, path in transport.requests
    ), "expected an abort POST for the native session before detaching"


@pytest.mark.parametrize("agent", ["fixer", "custom-write-agent"])
def test_hermes_delegate_selects_write_capable_agent(monkeypatch, agent):
    """Never inherit an OpenCode default coordinator unable to edit code."""
    if agent == "fixer":
        monkeypatch.delenv("HERMES_OPENCODE_DELEGATE_AGENT", raising=False)
    else:
        monkeypatch.setenv("HERMES_OPENCODE_DELEGATE_AGENT", agent)
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "start"}])]
    answer = base + [_msg(
        "msg_live_000002", "assistant",
        [{"type": "text", "text": "OK."}, {"type": "step-finish", "reason": "stop"}],
        completed=True,
    )]
    client = _client([(base, 0.05), (answer, 999.0)])
    client.run_session_prompt("fix this", timeout_seconds=15, poll_interval=0.02)
    assert client._transport.prompt_body["agent"] == agent
    assert client._transport.prompt_body["parts"][0]["text"] == "fix this"
