"""Inter-step generation veto regression tests (2026-10-24).

Live repro ses_e8fbd486bffeEijK4IE6BKLPDg (glmplus/glm-5.3, native Hermes
delegate_session -> OpenCode): a multi-step turn went QUIET BETWEEN STEPS —
step 1 completed (text + bash tool call, ``finish=tool-calls``, stamped),
OpenCode created step 2's empty assistant row while the provider call was in
flight, and the transcript sat unchanged past the 5s stability window. The
pre-fix client treated that stability as turn-end and returned step 1's
"Starting on the task..." text as the FINAL result — a ghost completion: the
delegate reported success while the workspace had no files, no test run, no
commit.

Root premise fixed: "transcript stable for the window" is NOT evidence the
turn ended while any fresh assistant message still lacks its
``info.time.completed`` stamp. The veto releases when the stamp lands
(glmplus/OpenCode 1.19.4 stamps every finished message — verified in
opencode.db for the owner's good sessions), or after
HERMES_OPENCODE_STAMPLESS_FALLBACK_SECONDS of full stability on transports
that never stamp (bounded legacy fallback, preserves old termination).

Hermetic: scripted fake transport, no server.
"""

from __future__ import annotations

import time
from typing import Any, Optional


import agent.opencode_client as oc
from agent.opencode_client import OpenCodeClient


def _msg(mid: str, role: str, parts: list[dict], completed: bool = True) -> dict:
    # created defaults to wall-clock now (ms) like the real server; a created
    # near epoch 0 would make open_since look ancient and release the veto.
    info: dict[str, Any] = {
        "id": mid,
        "role": role,
        "time": {"created": int(time.time() * 1000)},
    }
    if completed:
        info["time"]["completed"] = int(time.time() * 1000) + 1
    return {"info": info, "parts": parts}


class _InterStepScriptedTransport:
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


def _client(transport: _InterStepScriptedTransport) -> OpenCodeClient:
    client = OpenCodeClient(
        session_id="sess-test",
        session_name="test",
        acp_cwd="/tmp",
        transport_factory=lambda cwd: transport,
    )
    client.native_session_id = "ses_scripted1234"
    return client


def _step1_done() -> dict:
    return _msg(
        "msg_live_000002",
        "assistant",
        [
            {"type": "step-start"},
            {"type": "text", "text": "Starting on the task"},
            {"type": "tool", "state": {"status": "completed"}, "tool": "bash"},
            {"type": "step-finish", "reason": "tool-calls"},
        ],
        completed=True,
    )


def test_interstep_quiet_gap_waits_for_step2_not_ghost():
    """THE live ghost: stability lapses while step 2 is open mid-provider-call.

    Pre-fix the client returned step 1's text ("Starting on the task") as the
    final result the moment the 5s stability window lapsed with step 2 still
    open — a ghost completion. Post-fix it keeps polling and returns step 2's
    real final text.
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    # Step 1 done + step 2 OPEN (no completion stamp), held past the
    # stability window while the provider call is in flight.
    quiet_gap = base + [
        _step1_done(),
        _msg("msg_live_000003", "assistant", [], completed=False),
    ]
    # Step 2 lands: stamped, with the real final text.
    step2_done = base + [
        _step1_done(),
        _msg(
            "msg_live_000003",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "DONE-files-created-commit-abc123"},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        ),
    ]
    transport = _InterStepScriptedTransport(
        [(base, 0.05), (quiet_gap, 10.0), (step2_done, 999.0)]
    )
    client = _client(transport)
    result = client.run_session_prompt("go", timeout_seconds=40, poll_interval=0.02)
    # The client returns the joined fresh-turn text; the step-2 content in it
    # is the proof the loop kept polling through the quiet gap instead of
    # returning step 1's text as terminal.
    assert result["text"].endswith("DONE-files-created-commit-abc123")


def test_midturn_idle_with_open_message_not_completed():
    """A session.idle AT the step boundary must not complete the turn.

    The scripted /event stream never delivers idle events (hermetic), so the
    idle flag cannot trip here; this test pins the stable-exit twin of the
    same veto: an open assistant message blocks exit even after the grace
    window, until its stamp lands or the legacy fallback expires.
    Covered jointly with test_stampless_transport_falls_back below.
    """
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    quiet_gap = base + [
        _step1_done(),
        _msg("msg_live_000003", "assistant", [], completed=False),
    ]
    step2_done = base + [
        _step1_done(),
        _msg(
            "msg_live_000003",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "final-answer"},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        ),
    ]
    transport = _InterStepScriptedTransport(
        [(base, 0.05), (quiet_gap, 7.0), (step2_done, 999.0)]
    )
    client = _client(transport)
    result = client.run_session_prompt("go", timeout_seconds=40, poll_interval=0.02)
    assert result["text"].endswith("final-answer")


def test_stampless_transport_falls_back(monkeypatch):
    """Transports that never stamp still terminate: bounded legacy fallback.

    After the fallback window of full stability with nothing running, the
    client accepts the stable exit (returning the best text so far) instead
    of holding the veto until the caller's deadline.
    """
    monkeypatch.setattr(oc, "_STAMPLESS_GENERATION_FALLBACK_SECONDS", 3.0)
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    # Step 1 carries text but NO completion stamp and none ever arrives.
    stampless = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "legacy-partial-answer"},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=False,
        )
    ]
    transport = _InterStepScriptedTransport([(base, 0.05), (stampless, 999.0)])
    client = _client(transport)
    result = client.run_session_prompt("go", timeout_seconds=25, poll_interval=0.02)
    assert result["text"] == "legacy-partial-answer"
