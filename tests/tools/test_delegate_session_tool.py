"""Regression coverage for persistent Pi delegate_session semantics."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

import tools.delegate_session_tool as ds
from agent.delegate_errors import DelegateTurnStalled
from agent.delegate_health import reset_delegate_health_ledger


class Parent:
    def __init__(self, session_id: str = "parent-session") -> None:
        self.session_id = session_id


class FakePiClient:
    instances = []

    def __init__(
        self,
        *,
        persistent_session=False,
        session_id=None,
        session_name=None,
        acp_cwd=None,
        question_answerer=None,
        **_kwargs,
    ):
        self.persistent_session = persistent_session
        self.session_id = session_id
        self.session_name = session_name
        self.cwd = acp_cwd
        self.question_answerer = question_answerer
        self.is_closed = False
        self.messages = []
        self.steers = []
        self.turn_timeouts = []
        self.started_turn = threading.Event()
        self.release_turn = threading.Event()
        self.block_turns = False
        self.last_turn_activity_at = time.time()
        self._proc = None
        self.__class__.instances.append(self)

    def start(self, *, timeout=30.0):
        return {
            "sessionId": self.session_id,
            "sessionFile": f"/tmp/{self.session_id}.jsonl",
            "messageCount": len(self.messages),
            "isStreaming": False,
        }

    def run_session_prompt(self, message, *, timeout_seconds=900.0):
        self.messages.append(message)
        self.turn_timeouts.append(timeout_seconds)
        self.last_turn_activity_at = time.time()
        self.started_turn.set()
        if self.block_turns:
            assert self.release_turn.wait(timeout=5)
        return {
            "success": True,
            "text": f"done:{message}",
            "reasoning": "",
            "duration_s": 0.01,
            "state": {
                "sessionId": self.session_id,
                "messageCount": len(self.messages),
                "isStreaming": False,
            },
        }

    def get_messages(self, *, timeout=30.0):
        return [{"role": "user", "content": m} for m in self.messages]

    def steer(self, message, *, timeout=30.0):
        self.steers.append(message)
        return {"success": True, "command": "steer"}

    def abort(self, *, timeout=30.0):
        self.release_turn.set()
        return {"success": True, "command": "abort"}

    def close(self):
        self.is_closed = True
        self.release_turn.set()


@pytest.fixture(autouse=True)
def clean_sessions(monkeypatch, tmp_path):
    # T4: every test starts with a fresh provider breaker — turns now record
    # into the process-wide ledger, and a circuit opened by one test must not
    # gate dispatches in the next.
    reset_delegate_health_ledger()
    with ds._SESSION_LOCK:
        for record in ds._SESSIONS.values():
            try:
                record["client"].close()
            except Exception:
                pass
        ds._SESSIONS.clear()
    FakePiClient.instances.clear()
    monkeypatch.setattr(ds, "PiRPCClient", FakePiClient)
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: tmp_path)
    monkeypatch.setattr(
        ds, "_session_store_root", lambda: tmp_path / "delegate-session-store"
    )
    monkeypatch.setattr(ds, "pending_question_for_owner", lambda _client: None)
    yield
    with ds._SESSION_LOCK:
        for record in ds._SESSIONS.values():
            try:
                record["client"].close()
            except Exception:
                pass
        ds._SESSIONS.clear()


def payload(raw: str) -> dict:
    return json.loads(raw)


def wait_for_status(
    parent: Parent, sid: str, wanted: str, timeout: float = 2.0
) -> dict:
    deadline = time.time() + timeout
    latest = {}
    while time.time() < deadline:
        latest = payload(
            ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
        )
        if latest.get("status") == wanted:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"session {sid} never reached {wanted}: {latest}")


def test_start_creates_native_persistent_pi_session():
    parent = Parent()
    result = payload(ds.delegate_session(action="start", parent_agent=parent))

    assert result["success"] is True
    assert result["created"] is True
    assert result["status"] == "idle"
    assert result["session_id"] == result["pi_session_id"]
    client = FakePiClient.instances[-1]
    assert client.persistent_session is True
    assert client.session_id == result["session_id"]
    assert client.cwd == result["cwd"]


def test_start_installs_hermes_auto_question_answerer(monkeypatch):
    parent = Parent()
    seen = []

    def fake_answerer(parent_arg, method, title, options):
        seen.append((parent_arg, method, title, options))
        return "Hermes chose this"

    monkeypatch.setattr(ds, "_auto_answer_pi_question", fake_answerer)
    result = payload(ds.delegate_session(action="start", parent_agent=parent))
    client = FakePiClient.instances[-1]

    assert result["success"] is True
    assert callable(client.question_answerer)
    assert (
        client.question_answerer("input", "Which path?", ["A", "B"])
        == "Hermes chose this"
    )
    assert seen == [(parent, "input", "Which path?", ["A", "B"])]


def test_auto_answer_uses_supervising_context_and_main_runtime(monkeypatch):
    parent = Parent()
    parent._session_messages = [
        {"role": "user", "content": "Use PostgreSQL for this project."},
        {"role": "assistant", "content": "I will keep the existing database choice."},
        {"role": "tool", "content": "Detected database port 5432."},
    ]
    parent._current_main_runtime = lambda: {
        "provider": "test-provider",
        "model": "test-model",
        "base_url": "https://example.invalid/v1",
        "api_key": "secret-not-logged",
    }
    captured = {}

    def fake_oneshot(**kwargs):
        captured.update(kwargs)
        return "5432"

    monkeypatch.setattr("agent.oneshot.run_oneshot", fake_oneshot)
    answer = ds._auto_answer_pi_question(parent, "input", "Which DB port?", [])

    assert answer == "5432"
    assert "Use PostgreSQL for this project" in captured["user_input"]
    assert "Detected database port 5432" in captured["user_input"]
    assert "Never ask the user" in captured["instructions"]
    assert captured["task"] == "delegate_session_question"
    assert captured["main_runtime"]["model"] == "test-model"


def test_auto_answer_normalizes_confirm_and_select(monkeypatch):
    parent = Parent()
    answers = iter([
        "Proceed, yes.",
        "use grpc",
        "2",
        "not one of the options",
        "maybe",
    ])
    monkeypatch.setattr("agent.oneshot.run_oneshot", lambda **_kwargs: next(answers))

    assert ds._auto_answer_pi_question(parent, "confirm", "Continue?", []) == "yes"
    assert (
        ds._auto_answer_pi_question(
            parent, "select", "Transport?", ["Use REST", "Use gRPC"]
        )
        == "Use gRPC"
    )
    assert (
        ds._auto_answer_pi_question(
            parent, "select", "Transport?", ["Use REST", "Use gRPC"]
        )
        == "Use gRPC"
    )
    assert (
        ds._auto_answer_pi_question(
            parent, "select", "Transport?", ["Use REST", "Use gRPC"]
        )
        is None
    )
    assert ds._auto_answer_pi_question(parent, "confirm", "Continue?", []) is None


def test_send_reuses_same_client_and_preserves_followup_history():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    first = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="first", parent_agent=parent
        )
    )
    assert first["accepted"] is True
    wait_for_status(parent, sid, "idle")

    second = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="second", parent_agent=parent
        )
    )
    assert second["accepted"] is True
    final = wait_for_status(parent, sid, "idle")

    assert FakePiClient.instances == [client]
    assert client.messages == ["first", "second"]
    assert final["last_result"]["text"] == "done:second"


def test_start_on_live_session_with_goal_dispatches_followup_turn():
    """Re-start on a live session must run the goal, not drop it (conductor v5/v6)."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    wait_for_status(parent, sid, "idle")

    reused = payload(
        ds.delegate_session(
            action="start",
            session_id=sid,
            goal="phase two goal",
            parent_agent=parent,
        )
    )

    assert reused["reused"] is True
    assert reused.get("turn_dispatched") is True
    wait_for_status(parent, sid, "idle")
    assert any("phase two goal" in m for m in client.messages), client.messages


def test_start_with_goal_on_dead_client_reopens_and_dispatches():
    """R69 (2026-09-17): the spool server drives follow-up phase turns with
    action=start + session_id + goal. When the pi client behind that handle
    has died (is_closed — e.g. the RPC process crashed mid-run), the start
    must REOPEN the session on a fresh client and dispatch the goal there —
    never dispatch into the closed client, which raises "pi rpc client is
    closed" on every retry and strands the phase permanently."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    dead_client = FakePiClient.instances[-1]
    wait_for_status(parent, sid, "idle")

    # Simulate the RPC process dying: client closed but the session record
    # still live in the registry (exactly the spool server's view after a
    # crashed turn).
    dead_client.close()

    result = payload(
        ds.delegate_session(
            action="start",
            session_id=sid,
            goal="reland goal",
            parent_agent=parent,
        )
    )

    assert result["success"] is True
    fresh_client = FakePiClient.instances[-1]
    assert fresh_client is not dead_client
    assert fresh_client.is_closed is False
    # The goal is dispatched on the REOPENED client, and the dead client
    # never saw it.
    wait_for_status(parent, sid, "idle")
    assert any("reland goal" in m for m in fresh_client.messages), fresh_client.messages
    assert not any("reland goal" in m for m in dead_client.messages)


def test_pi_bootstrap_failure_recovers_with_fresh_native_session(monkeypatch):
    """A dead durable Pi native id must not strand every later retry.

    The logical delegate handle remains stable while recovery mints a fresh
    native Pi session. This is explicitly not an OpenCode failover.
    """
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]

    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    class BootstrapFailingPi(FakePiClient):
        instances = []

        def start(self, *, timeout=30.0):
            if self.session_id == sid:
                raise TimeoutError("pi did not answer command 'get_state'")
            return super().start(timeout=timeout)

    monkeypatch.setattr(ds, "PiRPCClient", BootstrapFailingPi)

    resumed = payload(
        ds.delegate_session(
            action="resume",
            session_id=sid,
            parent_agent=parent,
        )
    )

    assert resumed["success"] is True
    assert resumed["backend"] == "pi"
    assert resumed["session_id"] == sid
    assert resumed["native_session_id"] != sid
    assert resumed["native_session_id"].startswith(f"{sid}-recovery-")
    # One same-id retry before the mint (recovery-lineage fidelity): the
    # bound id is opened twice, then a fresh -recovery- native session.
    assert len(BootstrapFailingPi.instances) == 3
    assert BootstrapFailingPi.instances[0].session_id == sid
    assert BootstrapFailingPi.instances[1].session_id == sid
    assert BootstrapFailingPi.instances[2].session_id == resumed["native_session_id"]
    assert ds._load_metadata(sid)["native_session_id"] == resumed["native_session_id"]
    # The substitution is REPORTED, not silent.
    assert resumed["recovery_of_native_id"] == sid
    assert resumed["recovery_reason"]
    assert isinstance(resumed["recovered_at"], float)


def test_steer_on_idle_session_degrades_to_send_instead_of_erroring():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="first", parent_agent=parent
        )
    )
    wait_for_status(parent, sid, "idle")

    # Race window: turn already ended, but the caller tries to steer.
    steered = payload(
        ds.delegate_session(
            action="steer",
            session_id=sid,
            message="focus on tests",
            parent_agent=parent,
        )
    )
    assert steered["success"] is True
    assert steered["degraded_to_send"] is True
    assert "follow-up" in steered["note"]
    # No steer was attempted (session was idle); message became a new turn instead.
    assert client.steers == []
    final = wait_for_status(parent, sid, "idle")
    assert client.messages == ["first", "focus on tests"]
    assert final["last_result"]["text"] == "done:focus on tests"


def test_steer_on_closed_session_still_errors_with_resume_hint():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]

    payload(ds.delegate_session(action="stop", session_id=sid, parent_agent=parent))

    result = payload(
        ds.delegate_session(
            action="steer", session_id=sid, message="hello", parent_agent=parent
        )
    )
    assert result.get("error") or result.get("success") is not True


def test_steer_targets_live_session_instead_of_spawning_child_agent():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True

    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="long task", parent_agent=parent
        )
    )
    assert client.started_turn.wait(timeout=1)

    steered = payload(
        ds.delegate_session(
            action="steer",
            session_id=sid,
            message="focus on tests",
            parent_agent=parent,
        )
    )
    assert steered["success"] is True
    assert client.steers == ["focus on tests"]

    client.release_turn.set()
    wait_for_status(parent, sid, "idle")


def test_sessions_are_recoverable_by_new_supervisor_in_same_workspace():
    owner = Parent("owner")
    replacement = Parent("replacement")
    started = payload(ds.delegate_session(action="start", parent_agent=owner))
    sid = started["session_id"]

    status = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=replacement)
    )
    assert status["success"] is True
    assert status["session_id"] == sid

    replacement_list = payload(
        ds.delegate_session(action="list", parent_agent=replacement)
    )
    assert [row["session_id"] for row in replacement_list["sessions"]] == [sid]


def test_stop_closes_client_but_native_id_can_be_resumed():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    first_client = FakePiClient.instances[-1]

    stopped = payload(
        ds.delegate_session(action="stop", session_id=sid, parent_agent=parent)
    )
    assert stopped["closed"] is True
    assert first_client.is_closed is True

    # Simulate a gateway restart/process-local registry loss while Pi's native
    # session remains durable on disk, then reopen the same native session id.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid, None)
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["created"] is True
    assert resumed["session_id"] == sid
    assert resumed["pi_session_id"] == sid
    assert FakePiClient.instances[-1] is not first_client
    assert FakePiClient.instances[-1].session_id == sid


def test_stop_then_resume_reopens_in_same_gateway_process():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    first_client = FakePiClient.instances[-1]

    payload(ds.delegate_session(action="stop", session_id=sid, parent_agent=parent))
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )

    assert resumed["success"] is True
    assert resumed["created"] is True
    assert resumed["status"] == "idle"
    assert FakePiClient.instances[-1] is not first_client
    assert FakePiClient.instances[-1].is_closed is False
    assert callable(FakePiClient.instances[-1].question_answerer)


def test_resume_after_registry_loss_requires_same_workspace(monkeypatch, tmp_path):
    parent = Parent()
    original = tmp_path / "original"
    elsewhere = tmp_path / "elsewhere"
    original.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: original)

    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    assert FakePiClient.instances[-1].cwd == str(original.resolve())

    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: elsewhere)

    denied = ds.delegate_session(
        action="resume", session_id=sid, parent_agent=Parent("replacement")
    )
    assert "another profile or workspace" in denied.lower()

    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: original)
    resumed = payload(
        ds.delegate_session(
            action="resume", session_id=sid, parent_agent=Parent("replacement")
        )
    )
    assert resumed["cwd"] == str(original.resolve())
    assert FakePiClient.instances[-1].cwd == str(original.resolve())


def test_list_includes_offline_durable_sessions_after_registry_loss():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    listed = payload(ds.delegate_session(action="list", parent_agent=parent))
    row = next(row for row in listed["sessions"] if row["session_id"] == sid)
    assert row["status"] == "offline"
    assert row["cwd"] == started["cwd"]


def wait_for_progress_fields(sid: str, timeout: float = 2.0, **fields) -> dict:
    """Poll the durable metadata file on disk until it carries ``fields``.

    The terminal stamp is banked inside the turn thread and written by
    ``_persist_metadata`` only after the in-memory status flip has released
    ``wait_for_status`` observers, so disk assertions must poll.
    """
    deadline = time.time() + timeout
    meta: dict = {}
    while time.time() < deadline:
        meta = ds._load_metadata(sid) or {}
        if all(meta.get(key) == value for key, value in fields.items()):
            return meta
        time.sleep(0.01)
    raise AssertionError(f"durable metadata for {sid} never reached {fields}: {meta}")


def test_turn_progression_evidence_survives_registry_loss():
    """Regression: durable forward-progression evidence (Maestro A4,
    cognitive-continuity.supervisor-progression-evidence-source-failure) must
    survive the loss of the process-local session registry — the exact state
    a gateway restart leaves behind."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    # No turn has run yet: the evidence surfaces exist but are empty.
    assert started["turns_completed"] == 0
    assert started["last_line"] is None
    assert started["last_progress_at"] is None
    assert started["last_turn_outcome"] is None

    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="ship it", parent_agent=parent
        )
    )
    done = wait_for_status(parent, sid, "idle")
    assert done["turns_completed"] == 1
    assert done["last_line"] == "done:ship it"
    assert done["last_turn_outcome"] == "completed"
    assert done["last_progress_at"] > 0
    assert isinstance(done["last_turn_duration_s"], float)

    meta = wait_for_progress_fields(
        sid, turns_completed=1, last_line="done:ship it", last_turn_outcome="completed"
    )
    assert meta["last_progress_at"] > 0

    # Simulate the incident scenario: the hosting process died, the registry
    # is gone, only the durable metadata file remains. Offline reads must
    # report how far the session got and what it last said.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid)["client"].close()
    offline = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert offline["status"] == "offline"
    assert offline["turns_completed"] == 1
    assert offline["last_line"] == "done:ship it"
    assert offline["last_turn_outcome"] == "completed"
    assert offline["last_progress_at"] == meta["last_progress_at"]

    # Resume carries the evidence forward instead of zeroing it: the first
    # persist after reopen must not erase the counters it inherited.
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["created"] is True
    assert resumed["turns_completed"] == 1
    assert resumed["last_line"] == "done:ship it"
    assert resumed["last_turn_outcome"] == "completed"


def test_progress_stamp_moves_only_on_terminal_turn_content():
    """Anti-whitewash invariant: ``last_progress_at`` advances only when a
    turn reaches a terminal outcome — never on dispatch, status transitions,
    polls, or persistence re-writes."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="first", parent_agent=parent
        )
    )
    first = wait_for_status(parent, sid, "idle")
    t_first = first["last_progress_at"]
    assert t_first > 0
    # The in-memory flip releases wait_for_status before the terminal persist
    # lands on disk; pin the file to the first turn's state before holding
    # the next turn open.
    wait_for_progress_fields(sid, turns_completed=1)

    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="second", parent_agent=parent
        )
    )
    assert client.started_turn.wait(timeout=5)

    running = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert running["status"] == "running"
    # Dispatching a new turn does not move the stamp.
    assert running["last_progress_at"] == t_first

    # Polls of every read surface leave the stamp — and the durable file —
    # untouched while the turn is still running.
    for _ in range(3):
        payload(
            ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
        )
        payload(
            ds.delegate_session(action="messages", session_id=sid, parent_agent=parent)
        )
        timed_out = payload(
            ds.delegate_session(
                action="wait", session_id=sid, wait_seconds=0, parent_agent=parent
            )
        )
        assert timed_out["timed_out"] is True
        assert timed_out["last_progress_at"] == t_first
    meta = ds._load_metadata(sid)
    assert meta["last_progress_at"] == t_first
    assert meta["turns_completed"] == 1

    client.release_turn.set()
    second = wait_for_status(parent, sid, "idle")
    assert second["turns_completed"] == 2
    assert second["last_line"] == "done:second"
    assert second["last_progress_at"] > t_first
    durable = wait_for_progress_fields(sid, turns_completed=2, last_line="done:second")
    assert durable["last_progress_at"] > t_first


def test_failed_turn_banks_error_outcome_and_keeps_last_line():
    """A failed turn is durable evidence of activity: the outcome stamp
    advances exactly once with an ``error`` outcome, while completed-turn
    evidence (count, last line) is left untouched."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="good", parent_agent=parent
        )
    )
    ok = wait_for_status(parent, sid, "idle")
    assert ok["turns_completed"] == 1
    assert ok["last_line"] == "done:good"
    t_ok = ok["last_progress_at"]
    wait_for_progress_fields(sid, turns_completed=1)

    client = FakePiClient.instances[-1]

    def boom(message, *, timeout_seconds=900.0):
        raise RuntimeError("provider exploded")

    client.run_session_prompt = boom
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="bad", parent_agent=parent
        )
    )
    failed = wait_for_status(parent, sid, "error")
    assert failed["last_turn_outcome"] == "error"
    # A failure is evidence of activity, not forward content.
    assert failed["turns_completed"] == 1
    assert failed["last_line"] == "done:good"
    assert failed["last_progress_at"] > t_ok

    meta = wait_for_progress_fields(sid, last_turn_outcome="error")
    assert meta["turns_completed"] == 1
    assert meta["last_line"] == "done:good"
    # (U1/predecessor adoption additionally persists bounded error prose and
    # error_class here; its own tests cover that union.)

    # The stamp advanced exactly once: later reads do not move it again.
    after = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert after["last_progress_at"] == failed["last_progress_at"]

    # The failure evidence is exactly what an offline supervisor reads back.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid)["client"].close()
    offline = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert offline["last_turn_outcome"] == "error"
    assert offline["turns_completed"] == 1
    assert offline["last_line"] == "done:good"


def test_durable_metadata_cache_prunes_oldest_files(monkeypatch, tmp_path):
    root = ds._session_store_root()
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ds, "_MAX_DURABLE_SESSIONS", 3)
    created = []
    for index in range(5):
        path = root / f"session-{index}.json"
        path.write_text(json.dumps({"session_id": str(index)}))
        os.utime(path, (100 + index, 100 + index))
        created.append(path)

    ds._prune_durable_metadata(root)

    assert [path.name for path in ds._metadata_files_newest(root)] == [
        "session-4.json",
        "session-3.json",
        "session-2.json",
    ]
    assert not created[0].exists()
    assert not created[1].exists()


def test_durable_resume_metadata_allows_replacement_supervisor_in_same_workspace():
    owner = Parent("owner")
    replacement = Parent("replacement")
    started = payload(ds.delegate_session(action="start", parent_agent=owner))
    sid = started["session_id"]
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=replacement)
    )
    assert resumed["success"] is True
    assert resumed["session_id"] == sid


def _write_metadata(sid: str, **fields) -> None:
    """Craft durable metadata directly (as written by an older Hermes)."""
    data = {
        "version": 2,
        "backend": "pi",
        "session_id": sid,
        "native_session_id": sid,
        "pi_session_id": sid,
        "owner": "legacy-supervisor",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    data.update(fields)
    path = ds._metadata_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_legacy_v2_metadata_migrates_on_same_workspace_resume(tmp_path, monkeypatch):
    workspace = tmp_path / "legacy"
    workspace.mkdir()
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: workspace)
    sid = "legacy-v2-session"
    _write_metadata(sid, cwd=str(workspace.resolve()))

    resumed = payload(
        ds.delegate_session(
            action="resume", session_id=sid, parent_agent=Parent("new-supervisor")
        )
    )

    assert resumed["success"] is True
    assert resumed["session_id"] == sid
    assert FakePiClient.instances[-1].session_id == sid
    upgraded = json.loads(ds._metadata_path(sid).read_text(encoding="utf-8"))
    assert upgraded["version"] == 4
    assert upgraded["owner_scope"] == ds._scope_for_workspace(workspace)


def test_legacy_v2_metadata_denied_across_workspaces(tmp_path, monkeypatch):
    here = tmp_path / "here"
    elsewhere = tmp_path / "elsewhere"
    here.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: here)
    sid = "legacy-v2-foreign"
    _write_metadata(sid, cwd=str(elsewhere.resolve()))

    denied = ds.delegate_session(
        action="resume", session_id=sid, parent_agent=Parent("new-supervisor")
    )

    assert "another profile or workspace" in denied.lower()
    assert not FakePiClient.instances


def test_offline_control_actions_fail_closed_until_resumed():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    for action, extra in (
        ("send", {"message": "hello"}),
        ("steer", {"message": "hello"}),
        ("stop", {}),
    ):
        result = payload(
            ds.delegate_session(
                action=action, session_id=sid, parent_agent=parent, **extra
            )
        )
        assert result.get("error"), action
        assert "offline" in result["error"].lower()
        assert "resume" in result["error"].lower()

    status = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert status["success"] is True
    assert status["status"] == "offline"
    assert "resume" in (status.get("note") or "").lower()

    messages = payload(
        ds.delegate_session(action="messages", session_id=sid, parent_agent=parent)
    )
    assert messages["success"] is True
    assert messages["messages_json"] == "[]"
    assert "resume" in (messages.get("note") or "").lower()


def test_summary_preserves_structured_trailer_from_long_last_result():
    trailer = '{"phase_result":{"run_id":"r","phase_id":"p","action_id":"a","attempt_id":"x","status":"succeeded"}}'
    record = {
        "session_id": "s",
        "backend": "pi",
        "status": "idle",
        "client": FakePiClient(session_id="s"),
        "last_result": {"text": ("prefix-" * 2200) + trailer, "duration_s": 1.0},
    }

    summary = ds._summary(record)

    assert len(summary["last_result"]["text"]) <= ds._MAX_TEXT
    assert trailer in summary["last_result"]["text"]


def test_messages_remain_valid_json_when_history_exceeds_bound():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.messages = [(f"message-{i}-" + ("x" * 2500)) for i in range(40)]

    result = payload(
        ds.delegate_session(action="messages", session_id=sid, parent_agent=parent)
    )
    parsed = json.loads(result["messages_json"])

    assert len(result["messages_json"]) <= 40_000
    assert parsed
    assert parsed[-1]["content"].startswith("message-39-")


def test_owner_grant_survives_workspace_move(tmp_path, monkeypatch):
    original = tmp_path / "original"
    moved = tmp_path / "moved"
    original.mkdir()
    moved.mkdir()
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: original)
    owner = Parent("owner")
    started = payload(ds.delegate_session(action="start", parent_agent=owner))
    sid = started["session_id"]

    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: moved)

    # The conversation that owns the session keeps control after its cwd moves.
    sent = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="still mine", parent_agent=owner
        )
    )
    assert sent["accepted"] is True
    wait_for_status(owner, sid, "idle")

    # The scope grant does not extend to a replacement supervisor in the moved-to workspace.
    denied = payload(
        ds.delegate_session(
            action="send",
            session_id=sid,
            message="mine now",
            parent_agent=Parent("replacement"),
        )
    )
    assert denied.get("error")
    assert not denied.get("success")


def test_process_local_owner_never_authorizes_durable_metadata(tmp_path, monkeypatch):
    here = tmp_path / "here"
    elsewhere = tmp_path / "elsewhere"
    here.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: here)
    parent = Parent("")  # no conversation id -> process-local owner key
    owner_key = ds._owner_key(parent)
    assert owner_key.startswith("agent:")
    sid = "proc-local-owner"
    # Foreign workspace, but the owner string matches the caller exactly.
    _write_metadata(sid, owner=owner_key, cwd=str(elsewhere.resolve()))

    denied = ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)

    assert "another profile or workspace" in denied.lower()
    assert not FakePiClient.instances


def test_runtime_dispatch_passes_parent_agent(monkeypatch):
    """invoke_tool must pass parent_agent to delegate_session (regression).

    The generic dispatch path never forwards parent_agent, so delegate_session
    used to fail with "requires a parent agent context" on every live call.
    """
    from agent.agent_runtime_helpers import invoke_tool

    calls = {}

    def fake_delegate_session(**kwargs):
        calls.update(kwargs)
        return '{"ok": true}'

    monkeypatch.setattr(
        "tools.delegate_session_tool.delegate_session", fake_delegate_session
    )

    agent = Parent("dispatch-agent")
    # Attributes the dispatch chain touches before reaching the tool.
    setattr(agent, "_memory_manager", None)
    setattr(agent, "_subagent_lifecycle", None)

    raw = invoke_tool(
        agent,
        "delegate_session",
        {"action": "list"},
        effective_task_id="task-1",
    )

    assert calls.get("parent_agent") is agent
    assert calls.get("action") == "list"
    assert raw == '{"ok": true}'


def test_registry_dispatch_resolves_bound_parent(monkeypatch):
    """Registry dispatch (no explicit parent_agent) must fall back to the
    turn-bound active parent instead of failing with 'requires a parent
    agent context'."""
    from agent.subagent_lifecycle import bind_subagent_parent
    from tools import registry as reg

    entry = reg.registry.get_entry("delegate_session")
    owner = Parent("registry-owner")
    with bind_subagent_parent(owner):
        result = entry.handler({"action": "list"})
    payload_result = json.loads(result)
    assert payload_result.get("success") is True, payload_result

    # Without a bound parent the explicit error is preserved.
    err = entry.handler({"action": "list"})
    assert "requires a parent agent context" in err.lower()


# ---------------------------------------------------------------------------
# Backend-configurable sessions (Pi default + OpenCode)
# ---------------------------------------------------------------------------


class FakeOpenCodeClient(FakePiClient):
    """Fake OpenCode backend client mirroring agent.opencode_client surface."""

    instances = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.native_session_id = None

    def pending_question_payload(self):
        return None

    def is_dead(self):
        return False


def test_default_backend_is_pi():
    parent = Parent()
    result = payload(ds.delegate_session(action="start", parent_agent=parent))
    assert result["backend"] == "pi"
    assert (
        result["pi_session_id"] == result["native_session_id"] == result["session_id"]
    )
    assert isinstance(FakePiClient.instances[-1], FakePiClient)


def test_backend_env_var_selects_opencode(monkeypatch):
    monkeypatch.setattr(ds, "OpenCodeClient", FakeOpenCodeClient)
    monkeypatch.setenv("HERMES_DELEGATE_SESSION_BACKEND", "opencode")
    parent = Parent()
    result = payload(ds.delegate_session(action="start", parent_agent=parent))
    assert result["backend"] == "opencode"
    assert result["native_session_id"]
    assert result["pi_session_id"] == result["native_session_id"]  # compatibility alias


def test_backend_arg_routes_to_opencode_client(monkeypatch):
    monkeypatch.setattr(ds, "OpenCodeClient", FakeOpenCodeClient)
    parent = Parent()
    result = payload(
        ds.delegate_session(action="start", backend="opencode", parent_agent=parent)
    )
    assert result["backend"] == "opencode"
    client = FakeOpenCodeClient.instances[-1]
    assert client.cwd  # opened in resolved cwd
    # follow-up send reaches the same client
    sid = result["session_id"]
    accepted = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    assert accepted["accepted"] is True
    done = wait_for_status(parent, sid, "idle")
    assert done["last_result"]["text"].startswith("done:")


def test_unknown_backend_is_bounded_error():
    parent = Parent()
    err = ds.delegate_session(action="start", backend="claude", parent_agent=parent)
    assert "unknown backend" in err.lower()


def test_control_action_with_mismatched_backend_errors(monkeypatch):
    monkeypatch.setattr(ds, "OpenCodeClient", FakeOpenCodeClient)
    parent = Parent()
    started = payload(
        ds.delegate_session(action="start", backend="opencode", parent_agent=parent)
    )
    sid = started["session_id"]
    err = ds.delegate_session(
        action="send", session_id=sid, message="x", backend="pi", parent_agent=parent
    )
    assert "is a opencode delegate session" in err.lower()


def test_resume_of_live_session_with_other_backend_errors(monkeypatch):
    monkeypatch.setattr(ds, "OpenCodeClient", FakeOpenCodeClient)
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))  # pi
    sid = started["session_id"]
    err = ds.delegate_session(
        action="resume", session_id=sid, backend="opencode", parent_agent=parent
    )
    assert "cannot be reopened as a opencode session" in err.lower()


def test_metadata_v2_roundtrip_reopens_correct_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "OpenCodeClient", FakeOpenCodeClient)
    parent = Parent()
    started = payload(
        ds.delegate_session(action="start", backend="opencode", parent_agent=parent)
    )
    sid = started["session_id"]
    native = started["native_session_id"]
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    meta = ds._load_metadata(sid)
    assert meta["version"] == 4
    assert meta["backend"] == "opencode"
    assert meta["native_session_id"] == native

    # metadata snapshot keeps the pi_session_id alias for one release
    assert meta["pi_session_id"] == native

    # resume without an explicit backend reopens the stored backend
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["backend"] == "opencode"
    client = FakeOpenCodeClient.instances[-1]
    assert client.native_session_id == native


def test_v1_metadata_loads_as_pi(monkeypatch, tmp_path):
    parent = Parent()
    sid = "legacy-v1-session"
    root = ds._session_store_root()
    root.mkdir(parents=True, exist_ok=True)
    legacy = {
        "version": 1,
        "session_id": sid,
        "pi_session_id": "pi_native_123",
        "owner": "parent-session",
        "cwd": str(tmp_path),
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    ds._metadata_path(sid).write_text(json.dumps(legacy))

    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["backend"] == "pi"
    # pi session id is reused as the native session on resume
    assert resumed["native_session_id"] == "pi_native_123"
    # re-persisted using the current metadata schema
    assert ds._load_metadata(sid)["version"] == 4


# ------------------------- metadata v4: failure evidence (A4 remediation)
# A failed delegate turn must persist WHY it died (class + provider retry
# hint + streak) so a restarted supervisor resumes with the evidence instead
# of re-entering the same dead provider blind.


def wait_for_metadata(
    sid: str, *, error_class: str | None, timeout: float = 2.0
) -> dict:
    """Poll durable metadata until the persisted outcome matches.

    `wait_for_status` observes the in-memory flip, which precedes the
    `_persist_metadata` file write; polling the file itself closes that gap.
    """
    deadline = time.time() + timeout
    meta: dict = {}
    while time.time() < deadline:
        meta = ds._load_metadata(sid)
        if error_class is not None and meta.get("error_class") == error_class:
            return meta
        time.sleep(0.02)
    return meta


def test_failed_turn_persists_v4_failure_evidence():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    def rate_limited_turn(message, *, timeout_seconds=900.0):
        raise RuntimeError(
            "Rate limit: disabling model glm-4.6 for 1800 seconds (cooling down)"
        )

    client.run_session_prompt = rate_limited_turn
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    meta = wait_for_metadata(sid, error_class="rate_limit")
    assert meta["status"] == "error"
    assert meta["version"] == 4
    assert meta["error_class"] == "rate_limit"
    assert meta["retry_after"] == 1800.0
    assert meta["consecutive_failures"] == 1

    # The class survives registry loss: offline rows still say WHY.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid, None)
    rows = payload(
        ds.delegate_session(action="list", parent_agent=parent)
    )["sessions"]
    row = next(r for r in rows if r["session_id"] == sid)
    assert row["status"] == "offline"
    assert row["error_class"] == "rate_limit"
    assert row["retry_after"] == 1800.0


def test_typed_stall_turn_keeps_class_and_streak_survives_restart():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    def stalled_turn(message, *, timeout_seconds=900.0):
        raise DelegateTurnStalled(
            "pi session turn timed out: stalled after 1800s "
            "without observable progress",
            error_class="provider_stall",
            zero_activity=True,
        )

    client.run_session_prompt = stalled_turn
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    meta = wait_for_metadata(sid, error_class="provider_stall")
    assert meta["retry_after"] is None
    assert meta["consecutive_failures"] == 1

    # Supervisor replacement: the resumed session inherits the durable streak
    # until a turn completes successfully.
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["success"] is True
    with ds._SESSION_LOCK:
        record = ds._SESSIONS[sid]
        assert record["consecutive_failures"] == 1
        assert record["error_class"] == "provider_stall"

    # The resumed fake client is unpatched, so the next turn succeeds and
    # clears the streak. The resumed session starts idle, so poll the durable
    # outcome (not a status transition) for the clear.
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    deadline = time.time() + 2.0
    while time.time() < deadline:
        meta = ds._load_metadata(sid)
        if meta["error_class"] == "" and meta["consecutive_failures"] == 0:
            break
        time.sleep(0.02)
    else:
        pytest.fail("resumed successful turn did not clear the failure streak")
    assert meta["status"] == "idle"
    assert meta["retry_after"] is None


def test_v4_metadata_with_unknown_fields_round_trips(tmp_path):
    sid = "v4-forward-compatible"
    data = {
        "version": 4,
        "backend": "pi",
        "session_id": sid,
        "native_session_id": sid,
        "pi_session_id": sid,
        "owner": "legacy-supervisor",
        "cwd": str(tmp_path),
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "error",
        "error_class": "rate_limit",
        "retry_after": 1800.0,
        "last_turn_activity_at": 1.0,
        "consecutive_failures": 2,
        "future_field": {"anything": True},
    }
    path = ds._metadata_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")

    meta = ds._load_metadata(sid)
    # Tolerant load: newer unknown fields pass through untouched.
    assert meta["version"] == 4
    assert meta["error_class"] == "rate_limit"
    assert meta["future_field"] == {"anything": True}


def test_failed_turn_persists_union_error_text_and_pi_model(monkeypatch):
    # U5 (D5-amendment): the durable v4 snapshot unions the parallel
    # campaigns' field sets — bounded ``error`` prose plus the ``pi_model``
    # the failure streak was counted under — so a restarted supervisor (or
    # the sibling campaign's loader) sees why AND on which provider the
    # session died, without replaying logs.
    monkeypatch.setenv("HERMES_PI_MODEL", "union-test/model-x")
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    def rate_limited_turn(message, *, timeout_seconds=900.0):
        raise RuntimeError(
            "Rate limit: disabling model glm-4.6 for 1800 seconds (cooling down)"
        )

    client.run_session_prompt = rate_limited_turn
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    meta = wait_for_metadata(sid, error_class="rate_limit")
    assert meta["pi_model"] == "union-test/model-x"
    assert "Rate limit: disabling model glm-4.6" in meta["error"]

    # Offline rows stay symmetric with the snapshot's evidence fields.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid, None)
    rows = payload(
        ds.delegate_session(action="list", parent_agent=parent)
    )["sessions"]
    row = next(r for r in rows if r["session_id"] == sid)
    assert row["pi_model"] == "union-test/model-x"
    assert "Rate limit: disabling model glm-4.6" in row["error"]


def test_v4_error_field_is_bounded_and_clears_on_success(monkeypatch):
    monkeypatch.setenv("HERMES_PI_MODEL", "union-bounds/model")
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    def exploding_turn(message, *, timeout_seconds=900.0):
        raise RuntimeError("Rate limit: cooling down " + "x" * 5000)

    client.run_session_prompt = exploding_turn
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    meta = wait_for_metadata(sid, error_class="rate_limit")
    assert 0 < len(meta["error"]) <= 2000
    assert meta["error"].endswith("...")

    # A later successful turn clears the prose along with the class/streak.
    def healthy_turn(message, *, timeout_seconds=900.0):
        return {
            "success": True,
            "text": "done",
            "reasoning": "",
            "duration_s": 0.01,
            "state": {
                "sessionId": client.session_id,
                "messageCount": 1,
                "isStreaming": False,
            },
        }

    client.run_session_prompt = healthy_turn
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="again", parent_agent=parent
        )
    )
    deadline = time.time() + 2.0
    while time.time() < deadline:
        meta = ds._load_metadata(sid)
        if meta.get("error_class") == "":
            break
        time.sleep(0.02)
    else:
        pytest.fail("successful turn did not clear the failure evidence")
    assert meta["error"] is None
    assert meta["pi_model"] == "union-bounds/model"


def test_v4_sibling_schema_fields_load_without_retry_after(tmp_path):
    # The sibling campaign's v4 snapshot claims the same version with a
    # different field emphasis (``error``/``pi_model``, no ``retry_after``).
    # Both loaders stay field-tolerant until the schemas reconcile.
    sid = "v4-sibling-schema"
    data = {
        "version": 4,
        "backend": "pi",
        "session_id": sid,
        "native_session_id": sid,
        "pi_session_id": sid,
        "owner": "legacy-supervisor",
        "cwd": str(tmp_path),
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "error",
        "error": "Rate limit: cooling down",
        "error_class": "rate_limit",
        "pi_model": "custom/glm-4.6",
        "consecutive_failures": 2,
        "last_turn_activity_at": 2.0,
    }
    path = ds._metadata_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")

    meta = ds._load_metadata(sid)
    assert meta["pi_model"] == "custom/glm-4.6"
    assert meta["error"].startswith("Rate limit")
    assert meta.get("retry_after") is None


def test_list_includes_backend_field(monkeypatch):
    monkeypatch.setattr(ds, "OpenCodeClient", FakeOpenCodeClient)
    parent = Parent()
    pi_row = payload(ds.delegate_session(action="start", parent_agent=parent))
    oc_row = payload(
        ds.delegate_session(action="start", backend="opencode", parent_agent=parent)
    )

    listed = payload(ds.delegate_session(action="list", parent_agent=parent))
    by_id = {row["session_id"]: row for row in listed["sessions"]}
    assert by_id[pi_row["session_id"]]["backend"] == "pi"
    assert by_id[oc_row["session_id"]]["backend"] == "opencode"
    assert "native_session_id" in by_id[pi_row["session_id"]]
    assert "pi_session_id" in by_id[oc_row["session_id"]]

    # offline durable rows also carry the backend
    for sid in (pi_row["session_id"], oc_row["session_id"]):
        with ds._SESSION_LOCK:
            stale = ds._SESSIONS.pop(sid)
        stale["client"].close()
    listed2 = payload(ds.delegate_session(action="list", parent_agent=parent))
    by_id2 = {row["session_id"]: row for row in listed2["sessions"]}
    assert by_id2[pi_row["session_id"]]["backend"] == "pi"
    assert by_id2[oc_row["session_id"]]["backend"] == "opencode"


def test_registry_handler_forwards_backend(monkeypatch):
    from tools import registry as reg

    entry = reg.registry.get_entry("delegate_session")
    from agent.subagent_lifecycle import bind_subagent_parent

    owner = Parent("backend-forward")
    with bind_subagent_parent(owner):
        err = entry.handler({"action": "start", "backend": "bogus"})
    assert "unknown backend" in err.lower()


def test_wait_returns_immediately_when_session_is_idle():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))

    before = time.monotonic()
    waited = payload(
        ds.delegate_session(
            action="wait",
            session_id=started["session_id"],
            wait_seconds=1,
            parent_agent=parent,
        )
    )

    assert waited["success"] is True
    assert waited["status"] == "idle"
    assert waited["timed_out"] is False
    assert time.monotonic() - before < 0.25


def test_wait_wakes_on_running_to_idle_transition():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(ds.delegate_session(action="send", session_id=sid, message="long task", parent_agent=parent))
    assert client.started_turn.wait(timeout=1)

    def release():
        time.sleep(0.05)
        client.release_turn.set()

    thread = threading.Thread(target=release)
    thread.start()
    waited = payload(ds.delegate_session(action="wait", session_id=sid, wait_seconds=1, parent_agent=parent))
    thread.join(timeout=1)

    assert waited["success"] is True
    assert waited["status"] == "idle"
    assert waited["timed_out"] is False
    assert waited["state_changed"] is True


def test_wait_timeout_is_nonfatal_and_does_not_stop_worker():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(ds.delegate_session(action="send", session_id=sid, message="long task", parent_agent=parent))
    assert client.started_turn.wait(timeout=1)

    waited = payload(ds.delegate_session(action="wait", session_id=sid, wait_seconds=0.05, parent_agent=parent))

    assert waited["success"] is True
    assert waited["status"] == "running"
    assert waited["timed_out"] is True
    assert client.is_closed is False
    assert client.release_turn.is_set() is False

    client.release_turn.set()
    assert payload(ds.delegate_session(action="wait", session_id=sid, wait_seconds=1, parent_agent=parent))["status"] == "idle"


def test_wait_seconds_is_separate_from_turn_timeout(monkeypatch):
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    observed = {}
    original = client.run_session_prompt

    def capture(message, *, timeout_seconds=900.0):
        observed["timeout_seconds"] = timeout_seconds
        return original(message, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(client, "run_session_prompt", capture)
    payload(ds.delegate_session(action="send", session_id=sid, message="task", timeout=777, parent_agent=parent))
    assert client.started_turn.wait(timeout=1)

    waited = payload(ds.delegate_session(action="wait", session_id=sid, wait_seconds=0.01, timeout=11, parent_agent=parent))
    assert waited["timed_out"] is True
    assert observed["timeout_seconds"] == 777

    client.release_turn.set()
    wait_for_status(parent, sid, "idle")


def test_turn_timeout_is_not_clamped_to_3600():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    payload(
        ds.delegate_session(
            action="send",
            session_id=sid,
            message="long task",
            timeout=7200,
            parent_agent=parent,
        )
    )
    wait_for_status(parent, sid, "idle")
    assert client.turn_timeouts[-1] == 7200


def test_timeout_schema_has_no_absolute_upper_bound():
    timeout_schema = ds.DELEGATE_SESSION_SCHEMA["parameters"]["properties"]["timeout"]
    assert timeout_schema["minimum"] == 10
    assert "maximum" not in timeout_schema
    assert "inactivity" in timeout_schema["description"]
    assert "not an absolute" in timeout_schema["description"]


def test_status_exposes_backend_activity_timestamp():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    status = payload(
        ds.delegate_session(
            action="status",
            session_id=started["session_id"],
            parent_agent=parent,
        )
    )
    assert isinstance(status["last_activity_at"], float)
    assert status["last_activity_at"] > 0


def test_check_requirements_accepts_opencode_only(monkeypatch, tmp_path):
    monkeypatch.setattr(ds.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ds.Path, "home", lambda: tmp_path)  # no ~/.local/bin binaries
    assert ds.check_delegate_session_requirements() is False
    monkeypatch.setenv("HERMES_OPENCODE_SERVER_URL", "http://127.0.0.1:1")
    assert ds.check_delegate_session_requirements() is True


def test_dispatch_turn_uses_non_daemon_thread(monkeypatch):
    captured = {}

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            captured.update(target=target, args=args, name=name, daemon=daemon)

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(ds.threading, "Thread", FakeThread)
    record = {"session_id": "session-1234", "status": "idle"}

    ds._dispatch_turn(record, "work", 30.0)

    assert captured["started"] is True
    assert captured["daemon"] is False
    assert record["status"] == "running"


# --- T4 (D3/D4): provider circuit gates + ledger recording -----------------


class RateLimitPiClient(FakePiClient):
    """Every turn fails with a typed provider-class stall (rate_limit)."""

    def run_session_prompt(self, message, *, timeout_seconds=900.0):
        self.messages.append(message)
        self.last_turn_activity_at = time.time()
        raise DelegateTurnStalled(
            "pi session turn timed out: stalled after 900s without observable progress",
            error_class="rate_limit",
            provider_signal="Rate limit: disabling model glm-4.6 for 1800 seconds",
            retry_after=1800.0,
        )


def _open_circuit(backend: str = "pi", model: str = "glm-4.6") -> None:
    ledger = reset_delegate_health_ledger()
    for _ in range(3):
        ledger.record_failure((backend, model), "rate_limit")


def test_open_circuit_refuses_fresh_dispatch_before_spawn(monkeypatch, tmp_path):
    """Gate site 1: an open (backend, model) circuit refuses the turn before
    any child process is spawned — no client, no stall window, structured
    error with the retry hint."""
    _open_circuit()
    monkeypatch.delenv("HERMES_PI_MODEL", raising=False)
    monkeypatch.setattr(ds, "_pi_model_for_parent", lambda _parent: "glm-4.6")
    parent = Parent()

    result = payload(
        ds.delegate_session(action="start", parent_agent=parent, goal="do work")
    )

    assert "error" in result  # tool_error body, not a success payload
    assert "circuit open" in result["error"]
    assert "error_class=provider_unavailable" in result["error"]
    assert "retry after" in result["error"]
    assert FakePiClient.instances == []  # refused pre-bootstrap, nothing spawned


def test_open_circuit_refuses_followup_send_and_degraded_steer(monkeypatch, tmp_path):
    """Gate sites 2-4: an open circuit refuses live-session follow-ups (start
    with goal), sends, and steers that would degrade to a fresh dispatch."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    model = str(ds._SESSIONS[sid]["model"])
    _open_circuit("pi", model)

    send = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="again", parent_agent=parent
        )
    )
    assert "error" in send
    assert "circuit open" in send["error"]

    followup = payload(
        ds.delegate_session(
            action="start", session_id=sid, parent_agent=parent, goal="next phase"
        )
    )
    assert "error" in followup
    assert "circuit open" in followup["error"]

    steer = payload(
        ds.delegate_session(
            action="steer", session_id=sid, message="redirect", parent_agent=parent
        )
    )
    assert "error" in steer
    assert "circuit open" in steer["error"]

    # No turn was dispatched through any of the three paths.
    assert ds._SESSIONS[sid]["client"].messages == []


def test_provider_failures_from_turns_open_the_circuit(monkeypatch, tmp_path):
    """Recording (A2): three provider-class turn failures on the same
    (backend, model) key open the circuit; the fourth dispatch is refused
    without ever reaching the client, and a healthy turn closes it again."""
    monkeypatch.setattr(ds, "PiRPCClient", RateLimitPiClient)
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]

    for expected_streak in (1, 2, 3):
        payload(
            ds.delegate_session(
                action="send", session_id=sid, message=f"go {expected_streak}",
                parent_agent=parent,
            )
        )
        summary = wait_for_status(parent, sid, "error")
        assert summary["error_class"] == "rate_limit"
        assert summary["retry_after"] == 1800.0
        assert summary["consecutive_failures"] == expected_streak

    # record_failure lands right after the last status transition (same
    # pattern as record_success) — wait for the breaker to actually open
    # before probing the gate: the 3rd failure must be durable when dispatch
    # #4 arrives, or the gate would still see only two.
    ledger = ds.get_delegate_health_ledger()
    key = ("pi", str(ds._SESSIONS[sid]["model"]))
    deadline = time.time() + 2.0
    circuit = ledger.check(key)
    while circuit is None and time.time() < deadline:
        time.sleep(0.01)
        circuit = ledger.check(key)
    assert circuit is not None  # 3 provider failures opened it

    fourth = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="doomed", parent_agent=parent
        )
    )
    assert "error" in fourth
    assert "circuit open" in fourth["error"]
    # State-level: the circuit is open for this exact key (half-open probing
    # and success-closing are covered by the ledger's own unit tests).
    assert circuit.last_error_class == "rate_limit"


@pytest.mark.parametrize(
    "error_class", ["agent_stall", "resource_exhausted", "unknown"]
)
def test_non_provider_failures_do_not_open_the_circuit(error_class, monkeypatch, tmp_path):
    """Non-provider classes are not the provider's fault: any number of them
    must not stop delegate traffic on that key (fail-open, no shadow gating).
    agent_stall = the delegate wedged; resource_exhausted = the local host;
    unknown = unclassified noise."""

    class StallingPiClient(FakePiClient):
        def run_session_prompt(self, message, *, timeout_seconds=900.0):
            self.messages.append(message)
            raise DelegateTurnStalled(
                "pi session turn timed out: stalled after 900s without observable progress",
                error_class=error_class,
            )

    monkeypatch.setattr(ds, "PiRPCClient", StallingPiClient)
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]

    for i in range(4):
        payload(
            ds.delegate_session(
                action="send", session_id=sid, message=f"go {i}", parent_agent=parent
            )
        )
        wait_for_status(parent, sid, "error")

    accepted = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="still trying", parent_agent=parent
        )
    )
    assert accepted["success"] is True
    assert accepted["accepted"] is True


def test_open_circuit_is_keyed_per_model(monkeypatch, tmp_path):
    """The breaker key is (backend, model): a circuit opened for one model
    never gates dispatches to a different model on the same backend — a dead
    glm-4.6 must not take delegation to other providers down with it."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    session_model = str(ds._SESSIONS[sid]["model"])
    other_model = "totally-other-model"
    assert other_model != session_model
    _open_circuit("pi", other_model)

    send = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="unaffected", parent_agent=parent
        )
    )

    assert send["success"] is True
    assert ds._SESSIONS[sid]["client"].messages == ["unaffected"]


def test_successful_probe_turn_closes_the_circuit(monkeypatch, tmp_path):
    """Half-open probe -> healthy turn -> circuit fully closed. After the
    cooldown the gate grants exactly one dispatch; if that turn succeeds the
    provider is healthy again and the next dispatch flows too (a success ends
    the outage for that (backend, model) pair, not just one turn)."""
    import agent.delegate_health as dh

    clock = {"t": 1000.0}
    # One shared fake for gate, dispatch capture and banking: the accessor
    # seam must return the SAME instance every call (a fresh-per-call
    # lambda would lazily reload the circuit from the state file, where
    # age rebasing under the fake clock makes it look just-opened).
    fake = dh.DelegateHealthLedger(now=lambda: clock["t"])
    monkeypatch.setattr(ds, "get_delegate_health_ledger", lambda: fake)
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    key = ("pi", str(ds._SESSIONS[sid]["model"]))
    ledger = ds.get_delegate_health_ledger()
    for _ in range(3):
        ledger.record_failure(key, "rate_limit")  # opened_at == 1000, cooldown 900

    clock["t"] = 1500.0  # still cooling down: the gate must refuse
    assert ledger.check(key) is not None

    clock["t"] = 1000.0 + 901.0  # cooldown elapsed: the gate grants the probe
    probe = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="probe", parent_agent=parent
        )
    )
    assert probe["success"] is True
    summary = wait_for_status(parent, sid, "idle")
    assert summary["error_class"] is None  # success cleared the failure state

    # record_success lands right after the status transition — wait for it
    # (bounded positive wait; a probe still in flight keeps refusing).
    deadline = time.time() + 2.0
    circuit = ledger.check(key)
    while circuit is not None and time.time() < deadline:
        time.sleep(0.01)
        circuit = ledger.check(key)
    # Closed, not still probing: a probe-in-flight would refuse the check; a
    # closed circuit answers None.
    assert circuit is None

    followup = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="after recovery", parent_agent=parent
        )
    )
    assert followup["success"] is True


# ------------------------- U7: running-guard at start/resume-with-goal
# A supervisor retry racing its own in-flight turn used to stack a second
# run_session_prompt call onto the same client (concurrent-dispatch wedge of
# the A4 continuity storms). The refusal must be typed (branchable
# error_class), must reach no prompt, and must not be sticky: once idle,
# the same call is still a follow-up.


def test_start_with_goal_on_running_session_refuses_second_turn():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="first", parent_agent=parent
        )
    )
    assert client.started_turn.wait(timeout=2)

    busy = payload(
        ds.delegate_session(
            action="start", session_id=sid, goal="second", parent_agent=parent
        )
    )
    assert "error" in busy
    assert "session_busy" in busy["error"]
    # No second concurrent turn: exactly one prompt ever reached the client.
    assert len(client.messages) == 1

    # The refusal is not sticky: once idle, the same call dispatches a
    # follow-up turn as before.
    client.release_turn.set()
    wait_for_status(parent, sid, "idle")
    followup = payload(
        ds.delegate_session(
            action="start", session_id=sid, goal="second", parent_agent=parent
        )
    )
    assert followup["success"] is True
    assert followup["turn_dispatched"] is True
    wait_for_status(parent, sid, "idle")
    assert len(client.messages) == 2


def test_resume_with_goal_on_running_session_refuses_second_turn():
    # start and resume normalize into the same follow-up branch, but the
    # contract is pinned per action so a future special-case cannot regress
    # one while keeping the other guarded.
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="first", parent_agent=parent
        )
    )
    assert client.started_turn.wait(timeout=2)

    busy = payload(
        ds.delegate_session(
            action="resume", session_id=sid, goal="retry now", parent_agent=parent
        )
    )
    assert "error" in busy
    assert "session_busy" in busy["error"]
    assert len(client.messages) == 1

    client.release_turn.set()
    wait_for_status(parent, sid, "idle")


# ------------------------- U9: turn-liveness truth in status
# `status` can lie (a turn thread that dies abnormally leaves it "running"),
# and "running" alone cannot distinguish a quiet-but-alive turn from a wedged
# one. The summary now carries the thread's actual liveness plus time
# anchors; live-only fields are never fabricated for offline rows.


def test_status_reports_turn_liveness_and_anchors():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    assert client.started_turn.wait(timeout=2)

    live = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert live["turn_running"] is True
    assert isinstance(live["turn_started_at"], float)
    assert isinstance(live["inactive_for_s"], float)
    # Observer contract unchanged: last_activity_at keeps mirroring the
    # client's streamed-activity timestamp (never the new turn anchor).
    assert live["last_activity_at"] == client.last_turn_activity_at

    client.release_turn.set()
    idle = wait_for_status(parent, sid, "idle")
    assert idle["turn_running"] is False
    # turn_started_at survives the turn as last-turn-start evidence.
    assert idle["turn_started_at"] == live["turn_started_at"]


def test_inactive_for_s_grows_during_quiet_turn():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    assert client.started_turn.wait(timeout=2)

    first = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    time.sleep(0.05)
    second = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    # A quiet turn is measurable: with no streamed activity between reads,
    # the inactivity window strictly grows (relationship, not a wall-clock
    # pin — any scheduler delay only widens it).
    assert second["inactive_for_s"] > first["inactive_for_s"]
    assert second["turn_running"] is True

    client.release_turn.set()
    wait_for_status(parent, sid, "idle")


def test_status_exposes_dead_thread_as_not_running():
    """The wedge the A4 family blinded supervisors to: an abnormally dead
    turn thread leaves status stuck at "running", so a supervisor kept
    waiting on a turn that no longer exists. turn_running must report the
    thread's actual liveness, not the stale lifecycle flag."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]

    def crashing_turn(message, *, timeout_seconds=900.0):
        raise SystemExit(9)  # BaseException: escapes _run_turn's except

    client.run_session_prompt = crashing_turn
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    with ds._SESSION_LOCK:
        thread = ds._SESSIONS[sid]["thread"]
    thread.join(timeout=2)
    summary = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    # The lifecycle flag is stuck; the liveness field tells the truth.
    assert summary["status"] == "running"
    assert summary["turn_running"] is False


def test_v4_snapshot_persists_turn_liveness_evidence():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    # The creation-time persist already says error_class="" — poll for the
    # post-turn file (idle + a turn anchor), not just the outcome class.
    wait_for_status(parent, sid, "idle")
    deadline = time.time() + 2.0
    meta = {}
    while time.time() < deadline:
        meta = ds._load_metadata(sid)
        if meta.get("status") == "idle" and isinstance(
            meta.get("turn_started_at"), float
        ):
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"post-turn v4 snapshot never landed: {meta}")
    assert meta["version"] == 4
    assert isinstance(meta["turn_started_at"], float)
    # Key always present once v4 liveness ships; nothing banked yet.
    assert meta["last_turn_triage"] is None

    # Offline rows carry the persisted anchors but never fabricate
    # live-only liveness.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid, None)
    rows = payload(
        ds.delegate_session(action="list", parent_agent=parent)
    )["sessions"]
    row = next(r for r in rows if r["session_id"] == sid)
    assert row["status"] == "offline"
    assert row["turn_started_at"] == meta["turn_started_at"]
    assert row["last_turn_triage"] is None
    assert "turn_running" not in row
    assert "inactive_for_s" not in row


def test_banked_last_turn_triage_surfaces_and_survives_restart():
    """The record -> summary -> v4 -> resume chain for stall-time triage
    evidence. The banking itself (probe at stall time on the typed-stall
    path) is authored by the even-numbered unit; this pins the surfacing
    contract it feeds, in the shape that unit banks."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    triage = {
        "client_alive": True,
        "probe_latency_s": 0.31,
        "observed_at": time.time(),
        "verdict": "provider_stall",
    }
    with ds._SESSION_LOCK:
        ds._SESSIONS[sid]["last_turn_triage"] = triage

    # A later transition persists the v4 snapshot carrying the triage. The
    # creation-time persist predates the banking, so poll for the file that
    # actually carries it.
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="go", parent_agent=parent
        )
    )
    wait_for_status(parent, sid, "idle")
    deadline = time.time() + 2.0
    meta = {}
    while time.time() < deadline:
        meta = ds._load_metadata(sid)
        if meta.get("last_turn_triage") == triage:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"banked triage never persisted: {meta}")
    summary = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert summary["last_turn_triage"] == triage

    # Restart: the resumed session inherits the banked evidence, like the
    # failure streak.
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["success"] is True
    with ds._SESSION_LOCK:
        assert ds._SESSIONS[sid]["last_turn_triage"] == triage


# ------------------- recovery lineage + stall triage banking (A4, U6/U8)


class StallWithTriagePiClient(FakePiClient):
    """Every turn raises a typed stall carrying a liveness triage dict —
    the shape agent.pi_rpc_client produces at stall time."""

    def run_session_prompt(self, message, *, timeout_seconds=900.0):
        self.messages.append(message)
        self.last_turn_activity_at = time.time()
        raise DelegateTurnStalled(
            "pi session turn timed out: stalled after 900s without observable progress",
            error_class="provider_stall",
            liveness_triage={
                "process_alive": True,
                "rpc_responsive": None,
                "probe_latency_ms": None,
                "message_count": 0,
                "last_event_age_s": 912.5,
                "probed_at": 1790000000.0,
            },
        )


def test_stall_triage_from_typed_exception_banks_to_session(monkeypatch):
    """U8 banking: a typed stall carrying `liveness_triage` lands verbatim in
    the session record, surfaces in status, persists to the v4 snapshot, and
    survives registry loss — a supervisor never re-derives liveness from
    prose."""
    monkeypatch.setattr(ds, "PiRPCClient", StallWithTriagePiClient)
    parent = Parent()
    started = payload(
        ds.delegate_session(action="start", parent_agent=parent, goal="do work")
    )
    sid = started["session_id"]

    row = wait_for_status(parent, sid, "error")
    triage = row["last_turn_triage"]
    assert triage["process_alive"] is True
    assert triage["rpc_responsive"] is None
    assert triage["probe_latency_ms"] is None
    assert triage["message_count"] == 0
    assert triage["last_event_age_s"] == 912.5
    assert triage["probed_at"] == 1790000000.0
    assert row["error_class"] == "provider_stall"

    # v4 snapshot persisted the evidence. The turn thread flips status to
    # `error` under the condition lock but persists AFTER releasing it, so
    # poll the file instead of assuming the write raced ahead of us.
    deadline = time.time() + 2.0
    meta = {}
    while time.time() < deadline:
        meta = json.loads(ds._metadata_path(sid).read_text(encoding="utf-8"))
        if meta.get("last_turn_triage") == triage:
            break
        time.sleep(0.01)
    assert meta.get("last_turn_triage") == triage

    # Registry loss: the evidence rides the durable metadata.
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert resumed["success"] is True
    assert resumed["last_turn_triage"] == triage


def _flaky_start_client(fail_ids=(), always_fail_ids=()):
    """FakePiClient whose start() wedges for scripted native ids.

    `fail_ids` fail their FIRST start() (the same-id retry then succeeds);
    `always_fail_ids` fail EVERY start() (a -recovery- mint is required).
    """

    class _FlakyStartPiClient(FakePiClient):
        fail_once = set(fail_ids)
        fail_always = set(always_fail_ids)

        def start(self, *, timeout=30.0):
            if self.session_id in type(self).fail_always:
                raise RuntimeError(
                    "pi rpc process exited before ready: simulated wedge"
                )
            if self.session_id in type(self).fail_once:
                type(self).fail_once.discard(self.session_id)
                raise RuntimeError(
                    "pi rpc process exited before ready: simulated wedge"
                )
            return super().start(timeout=timeout)

    return _FlakyStartPiClient


def _drop_session(sid):
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()


def test_failed_reopen_retries_same_native_id_before_any_recovery_mint(monkeypatch):
    """U6: a bound native id whose first reopen wedges gets ONE same-id
    retry (fresh client, same native session) before any -recovery- mint.
    A dead child process is the common cause — the delegated identity must
    not be silently substituted on a single failure."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    bound = started["native_session_id"]
    _drop_session(sid)

    monkeypatch.setattr(ds, "PiRPCClient", _flaky_start_client({bound}))
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )

    assert resumed["success"] is True
    assert resumed["native_session_id"] == bound  # identity preserved
    opens = [c.session_id for c in FakePiClient.instances[1:]]
    assert opens == [bound, bound]  # failed open + same-id retry, no third
    assert all("-recovery-" not in str(c.session_id) for c in FakePiClient.instances)
    # No lineage: nothing was substituted.
    assert resumed["recovery_of_native_id"] is None
    assert resumed["recovery_reason"] is None
    assert resumed["recovered_at"] is None
    meta = json.loads(ds._metadata_path(sid).read_text(encoding="utf-8"))
    assert meta["recovery_of_native_id"] is None


def test_confirmed_unopenable_native_id_mints_recovery_with_lineage(monkeypatch):
    """U6: when the bound id fails BOTH the first open and the same-id
    retry, a -recovery- native session is minted and REPORTED — the summary
    and the v4 snapshot name the original binding, why it was substituted,
    and when."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    bound = started["native_session_id"]
    _drop_session(sid)

    monkeypatch.setattr(
        ds, "PiRPCClient", _flaky_start_client(always_fail_ids={bound})
    )
    resumed = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )

    assert resumed["success"] is True
    minted = resumed["native_session_id"]
    assert minted != bound and "-recovery-" in minted
    opens = [c.session_id for c in FakePiClient.instances[1:]]
    assert opens == [bound, bound, minted]

    assert resumed["recovery_of_native_id"] == bound
    assert resumed["recovery_reason"]  # bounded reason, not empty
    assert len(resumed["recovery_reason"]) <= 400
    assert "simulated wedge" in resumed["recovery_reason"]
    assert isinstance(resumed["recovered_at"], float)
    assert resumed["recovered_at"] <= time.time()

    # v4 snapshot + offline rows carry the same lineage.
    meta = json.loads(ds._metadata_path(sid).read_text(encoding="utf-8"))
    assert meta["recovery_of_native_id"] == bound
    assert meta["recovery_reason"] == resumed["recovery_reason"]
    assert meta["recovered_at"] == resumed["recovered_at"]

    listing = payload(ds.delegate_session(action="list", parent_agent=parent))
    row = next(r for r in listing["sessions"] if r["session_id"] == sid)
    assert row["recovery_of_native_id"] == bound
    assert row["recovered_at"] == resumed["recovered_at"]


def test_recovery_lineage_survives_restart_and_keeps_chain_root(monkeypatch):
    """U6 immutability: after a mint, a LATER loss of the minted session
    re-mints again — recovery_of_native_id stays the ORIGINAL bound id
    (chain root), while reason and timestamp describe the latest mint."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    bound = started["native_session_id"]
    _drop_session(sid)

    monkeypatch.setattr(
        ds, "PiRPCClient", _flaky_start_client(always_fail_ids={bound})
    )
    first = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )
    assert first["recovery_of_native_id"] == bound
    first_minted = first["native_session_id"]
    first_recovered_at = first["recovered_at"]

    # The minted session is now the binding; lose the registry and wedge it.
    _drop_session(sid)
    monkeypatch.setattr(
        ds, "PiRPCClient",
        _flaky_start_client(always_fail_ids={first_minted}),
    )
    second = payload(
        ds.delegate_session(action="resume", session_id=sid, parent_agent=parent)
    )

    assert second["success"] is True
    assert "-recovery-" in second["native_session_id"]
    assert second["native_session_id"] != first_minted
    # Chain root is immutable; reason/time name the LATEST mint.
    assert second["recovery_of_native_id"] == bound
    assert second["recovered_at"] >= first_recovered_at
    meta = json.loads(ds._metadata_path(sid).read_text(encoding="utf-8"))
    assert meta["recovery_of_native_id"] == bound
    assert meta["recovered_at"] == second["recovered_at"]
