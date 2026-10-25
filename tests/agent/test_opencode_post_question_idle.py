"""Post-question idle continuation regression tests (2026-10-23).

Reproduces the failure that killed every question-bearing OpenCode
delegation (msn-m3-opencode-dev-001..005, msn-auto05 at 17:26): OpenCode
fires ``session.idle`` at the question/step boundary and the transcript
snapshot goes stable there, while the model — resumed by the auto-answer —
is still generating its real continuation text. The pre-fix client treated
that premature signal as turn-end and raised "OpenCode turn ended without
an assistant text reply".

These tests pin the post-question continuation contract:

- an idle/stable completion signal WITHOUT reply text inside the grace
  window is premature: the client keeps polling and returns the
  continuation text when it lands;
- once the grace window lapses with no continuation, the turn still fails
  visibly (no infinite wait);
- a turn whose question was REJECTED gets the same grace (the model still
  continues after a rejection).

Hermetic: scripted fake transport, no server.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pytest

import agent.opencode_client as oc
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


class _QuestionScriptedTransport:
    """Serves a scripted transcript AND a question lifecycle.

    ``question_at_step`` names the state index at which one pending
    question exists; the first ``/question/{id}/reply`` (or ``/reject``)
    consumes it. GET /question returns the question only at that state.
    """

    def __init__(
        self,
        script: list[tuple[list[dict], float]],
        question_at_step: int,
        question_id: str = "que_scripted001",
    ):
        self._script = list(script)
        self._question_at_step = question_at_step
        self._qid = question_id
        self._t0: Optional[float] = None
        self._prompted = False
        self.question_consumed = False
        self.requests: list[tuple[str, str]] = []

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

        self.requests.append((method, path))
        base_path = path.split("?")[0]
        if base_path.startswith("/session/") and base_path.endswith("/message"):
            if method == "GET":
                return 200, _json.dumps(self._script[self._state_index()][0])
            return 204, ""
        if base_path.startswith("/session/") and base_path.endswith("/prompt_async"):
            self._t0 = time.monotonic()
            self._script.pop(0)
            self._question_at_step -= 1
            return 204, ""
        if base_path == "/session" and method == "POST":
            return 200, _json.dumps({"id": "ses_scripted1234"})
        if base_path == "/question" and method == "GET":
            if (
                not self.question_consumed
                and self._state_index() == self._question_at_step
            ):
                return 200, _json.dumps(
                    [
                        {
                            "id": self._qid,
                            "sessionID": "ses_scripted1234",
                            "questions": [
                                {
                                    "question": "pick one",
                                    "options": [
                                        {"label": "A) red"},
                                        {"label": "B) blue"},
                                    ],
                                }
                            ],
                        }
                    ]
                )
            return 200, "[]"
        if base_path.startswith(f"/question/{self._qid}") and method == "POST":
            self.question_consumed = True
            return 200, "{}"
        if base_path.startswith("/event"):
            return 200, ""
        return 200, "{}"


def _client(transport: _QuestionScriptedTransport) -> OpenCodeClient:
    client = OpenCodeClient(
        session_id="sess-test",
        session_name="test",
        acp_cwd="/tmp",
        transport_factory=lambda cwd: transport,
    )
    client.native_session_id = "ses_scripted1234"
    return client


def test_post_question_idle_returns_continuation(monkeypatch):
    """The exact auto05 shape: idle + stable at the question boundary."""
    monkeypatch.setattr(oc, "_POST_QUESTION_GRACE_SECONDS", 30.0)
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    # Step 1 (becomes baseline on prompt): question pending; assistant row
    # already shows the completed question step — this is the snapshot the
    # pre-fix client declared terminal.
    question_step = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "tool", "state": {"status": "completed"}, "tool": "question"},
                {"type": "step-finish", "reason": "tool-calls"},
            ],
            completed=True,
        )
    ]
    # Step 2: continuation lands (25s later — inside the 30s grace).
    continuation = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "tool", "state": {"status": "completed"}, "tool": "question"},
                {"type": "step-finish", "reason": "tool-calls"},
            ],
            completed=True,
        ),
        _msg(
            "msg_live_000003",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "DONE-red"},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        ),
    ]
    transport = _QuestionScriptedTransport(
        [(base, 0.05), (question_step, 8.0), (continuation, 999.0)],
        question_at_step=1,
    )
    client = _client(transport)
    result = client.run_session_prompt("go", timeout_seconds=60, poll_interval=0.02)
    assert result["text"] == "DONE-red"
    assert transport.question_consumed


def test_grace_expiry_still_fails_visibly(monkeypatch):
    """No continuation ever lands: the turn must fail, not hang forever."""
    monkeypatch.setattr(oc, "_POST_QUESTION_GRACE_SECONDS", 3.0)
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    question_step = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [{"type": "step-start"}, {"type": "step-finish", "reason": "tool-calls"}],
            completed=True,
        )
    ]
    transport = _QuestionScriptedTransport(
        [(base, 0.05), (question_step, 999.0)],
        question_at_step=1,
    )
    client = _client(transport)
    with pytest.raises(
        (RuntimeError, oc.DelegateTurnStalled),
        match="without an assistant text reply|timed out",
    ):
        client.run_session_prompt("go", timeout_seconds=12, poll_interval=0.02)


def test_rejected_question_gets_same_grace(monkeypatch):
    """A rejected question also resumes the model; grace must apply too.

    The scripted transport's answerer returns None (no answerer wired at
    the client level here), so the question is REJECTED; the continuation
    still lands and must be returned.
    """
    monkeypatch.setattr(oc, "_POST_QUESTION_GRACE_SECONDS", 30.0)
    base = [_msg("msg_base_000001", "user", [{"type": "text", "text": "go"}])]
    question_step = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [{"type": "step-start"}, {"type": "step-finish", "reason": "tool-calls"}],
            completed=True,
        )
    ]
    continuation = base + [
        _msg(
            "msg_live_000002",
            "assistant",
            [{"type": "step-start"}, {"type": "step-finish", "reason": "tool-calls"}],
            completed=True,
        ),
        _msg(
            "msg_live_000003",
            "assistant",
            [
                {"type": "step-start"},
                {"type": "text", "text": "fallback-used"},
                {"type": "step-finish", "reason": "stop"},
            ],
            completed=True,
        ),
    ]
    transport = _QuestionScriptedTransport(
        [(base, 0.05), (question_step, 8.0), (continuation, 999.0)],
        question_at_step=1,
    )
    client = _client(transport)  # NO question_answerer -> reject path
    result = client.run_session_prompt("go", timeout_seconds=60, poll_interval=0.02)
    assert result["text"] == "fallback-used"
    assert transport.question_consumed
