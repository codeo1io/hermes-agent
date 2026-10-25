"""Step-boundary idle ghost regression tests (2026-10-25).

Live repro ses_e8f34b567ffeJgNa9V0gy6Ibmb (glmplus/glm-5.3, native Hermes
delegate_session -> OpenCode, dev-003 2026-10-25T02:04:13Z): a multi-step
turn's step 2 completed (text + bash tool calls, ``step-finish`` reason
``tool-calls``, completion stamp present) and OpenCode fired
``session.idle`` at the step boundary — BEFORE creating step 3's row
(the row appears only when the provider responds). At that instant:

- every fresh assistant row is stamped  -> ``generating`` veto idle;
- no row is open                        -> stamped-turn veto (#518) idle;
- step 2's text exists                  -> ``has_reply_text`` true.

The pre-fix client therefore returned step 2's intermediate text as the
FINAL result at 131s while step 3 was ~11s from opening — a ghost
completion the spool then banked (and, in dev-003's case, a settle-path
messages-fetch swallow turned into a false "zero assistant output").

Root premise fixed: ``step-finish`` reason ``tool-calls`` on the newest
fresh assistant row means the turn CONTINUES — OpenCode idles between
steps. Exit signals (idle or transcript stability) observed while that
row is younger than the step-boundary quiet window are premature; the
poll loop holds, and terminates normally when the final text-only row
(``reason: stop``) lands. A genuinely finished turn never trips the
guard, and a turn that truly ends on a tool-call step still terminates
once the quiet window lapses (stability re-accumulates) — no infinite
hold.

Hermetic: scripted fake transport, no server.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import agent.opencode_client as oc
from agent.opencode_client import OpenCodeClient


def _msg(mid: str, role: str, parts: list[dict], completed: bool = True) -> dict:
    # created defaults to wall-clock now (ms) like the real server; a created
    # near epoch 0 would make boundary_age look ancient and release the guard.
    info: dict[str, Any] = {
        "id": mid,
        "role": role,
        "time": {"created": int(time.time() * 1000)},
    }
    if completed:
        info["time"]["completed"] = int(time.time() * 1000) + 1
    return {"info": info, "parts": parts}


class _BoundaryScriptedTransport:
    """Serves a timed transcript script: list of (messages, hold_seconds)."""

    def __init__(self, script: list[tuple[list[dict], float]]):
        self._script = list(script)
        self._t0: Optional[float] = None

    def _state_index(self) -> int:
        if self._t0 is None:
            return 0
        elapsed = time.monotonic() - self._t0
        for idx, (_state, hold) in enumerate(self._script):
            if elapsed <= hold:
                return idx
            elapsed -= hold
        return len(self._script) - 1

    def request(
        self, method: str, path: str, body: Optional[dict] = None
    ) -> tuple[int, str]:
        import json as _json

        base_path = path.split("?")[0]
        if base_path.startswith("/session/") and base_path.endswith("/message"):
            if method == "GET":
                return 200, _json.dumps(self._script[self._state_index()][0])
            return 204, ""
        if base_path.startswith("/session/") and base_path.endswith("/prompt_async"):
            self._t0 = time.monotonic()
            self._script.pop(0)
            return 204, ""
        if base_path == "/session" and method == "POST":
            return 200, _json.dumps({"id": "ses_scripted1234"})
        if base_path == "/question":
            return 200, "[]"
        if base_path.startswith("/event"):
            return 200, ""
        return 200, "{}"


def _client(transport: _BoundaryScriptedTransport) -> OpenCodeClient:
    client = OpenCodeClient(
        session_id="sess-test",
        session_name="test",
        acp_cwd="/tmp",
        transport_factory=lambda cwd: transport,
    )
    client.native_session_id = "ses_scripted1234"
    return client


def _stamped_tool_step(mid: str, text: str) -> dict:
    """A COMPLETED intermediate step: text + tool + ``tool-calls`` finish.

    This is the exact 02:04 shape: stamped, so the generating veto is
    idle; no open row follows yet, so the #518 stamped-turn veto is idle
    too. Only the step-boundary quiet guard recognizes it as mid-turn.
    """
    return _msg(
        mid,
        "assistant",
        [
            {"type": "step-start"},
            {"type": "text", "text": text},
            {"type": "tool", "state": {"status": "completed"}, "tool": "bash"},
            {"type": "step-finish", "reason": "tool-calls"},
        ],
        completed=True,
    )


def _final_text_step(mid: str, text: str) -> dict:
    return _msg(
        mid,
        "assistant",
        [
            {"type": "step-start"},
            {"type": "text", "text": text},
            {"type": "step-finish", "reason": "stop"},
        ],
        completed=True,
    )


def test_step_boundary_quiet_holds_idle_until_final_step():
    """THE 02:04 ghost: quiet boundary state held past the stable window.

    Step 2 (stamped, tool-bearing) is the newest row with NO open row
    after it, held 8s — far past the 5s stability window. The pre-fix
    client returned step 2's text as the final result at ~5s. Post-fix it
    holds through the quiet window and returns step 3's real final text.
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    boundary = base + [
        _stamped_tool_step("msg_live_000002", "step2-progress-run-tests"),
    ]
    final = base + [
        _stamped_tool_step("msg_live_000002", "step2-progress-run-tests"),
        _final_text_step("msg_live_000003", "DONE-final-summary-abc123"),
    ]
    transport = _BoundaryScriptedTransport(
        [(base, 0.05), (boundary, 8.0), (final, 999.0)]
    )
    client = _client(transport)
    result = client.run_session_prompt("go", timeout_seconds=40, poll_interval=0.02)
    assert result["text"].endswith("DONE-final-summary-abc123")


def test_boundary_hold_expires_bounded_when_turn_really_ends_there(monkeypatch):
    """No infinite hold: a turn that truly ends on a tool-call step must
    still terminate once the quiet window lapses (stability accumulates
    again) — returning the accumulated text, not hanging to the deadline.
    """
    monkeypatch.setattr(oc, "_OPENCODE_STEP_BOUNDARY_QUIET_SECONDS", 3.0)
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    boundary = base + [_stamped_tool_step("msg_live_000002", "tool-only-terminal-step")]
    transport = _BoundaryScriptedTransport([(base, 0.05), (boundary, 999.0)])
    client = _client(transport)
    started = time.monotonic()
    result = client.run_session_prompt("go", timeout_seconds=30, poll_interval=0.02)
    assert result["text"] == "tool-only-terminal-step"
    # Held past the quiet window (3s), then released by stability — never
    # anywhere near the 30s deadline.
    assert time.monotonic() - started < 25.0


def test_final_text_only_row_is_never_held():
    """A text-only ``reason: stop`` final row never trips the guard: the
    client returns immediately once stability confirms, same as before.
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    final_only = base + [_final_text_step("msg_live_000002", "instant-final")]
    transport = _BoundaryScriptedTransport([(base, 0.05), (final_only, 999.0)])
    started = time.monotonic()
    result = _client(transport).run_session_prompt(
        "go", timeout_seconds=20, poll_interval=0.02
    )
    assert result["text"] == "instant-final"
    # No 75s quiet hold: text-only rows release the guard by construction.
    assert time.monotonic() - started < 20.0
