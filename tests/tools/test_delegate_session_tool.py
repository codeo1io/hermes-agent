"""Regression coverage for persistent Pi delegate_session semantics."""

from __future__ import annotations

import json
import os
import stat
import sys
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
    # Send returns on accept; sync on the turn actually completing before
    # reading the client (same pattern as every sibling test here).
    wait_for_status(parent, sid, "idle")
    assert ds._SESSIONS[sid]["client"].messages == ["unaffected"]


def test_successful_probe_turn_closes_the_circuit(monkeypatch, tmp_path):
    """Half-open probe -> healthy turn -> circuit fully closed. After the
    cooldown the gate grants exactly one dispatch; if that turn succeeds the
    provider is healthy again and the next dispatch flows too (a success ends
    the outage for that (backend, model) pair, not just one turn)."""
    import agent.delegate_health as dh

    clock = {"t": 1000.0}
    monkeypatch.setattr(
        dh,
        "_LEDGERS",
        {dh.hermes_home_key(): dh.DelegateHealthLedger(now=lambda: clock["t"])},
    )
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


# ── Durable mid-turn liveness (observer) ─────────────────────────────────────
# Regression for the spool-lease starvation family (finding
# cognitive-continuity.prevention.d8fce7da, recurrence #7): during the
# incident, a healthy 30-90 min delegated turn was indistinguishable from a
# wedged one because durable metadata was only written at dispatch and
# terminal state — outside readers saw a stale pre-turn snapshot for the
# whole turn. The in-turn observer closes that blindness.


def _blocked_running_session(parent, message="blocked turn"):
    """Start a session, dispatch a turn the fake holds open, return handles."""
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    client = FakePiClient.instances[-1]
    client.block_turns = True
    sent = payload(
        ds.delegate_session(
            action="send", session_id=sid, message=message, parent_agent=parent
        )
    )
    assert sent["accepted"] is True
    wait_for_status(parent, sid, "running")
    # Status flips to running before the turn thread starts; the fake's
    # entry write of last_turn_activity_at must land before callers step it,
    # or the step races (and loses to) that assignment.
    assert client.started_turn.wait(timeout=5.0)
    return sid, client


def test_watcher_persists_mid_turn_running_evidence(monkeypatch):
    """T2: the in-turn refresh observer. While a turn is open, stepping the
    client's activity signal must advance the durable file on the observer's
    own — an outside reader sees status running and a fresh activity
    timestamp without the originating process persisting anything (the exact
    silence the incident supervisor hit)."""
    monkeypatch.setattr(ds, "_OBSERVER_POLL_S", 0.05)
    monkeypatch.setattr(ds, "_ACTIVITY_REFRESH_MIN_S", 0.05)
    parent = Parent()
    sid, client = _blocked_running_session(parent)
    try:
        first = client.last_turn_activity_at
        client.last_turn_activity_at = first + 1.0
        baseline = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            meta = ds._load_metadata(sid) or {}
            if meta.get("status") == "running":
                baseline = meta.get("last_turn_activity_at")
                break
            time.sleep(0.01)
        assert baseline is not None
        assert baseline >= first + 1.0

        client.last_turn_activity_at = baseline + 1.0
        advanced = None
        while time.time() < deadline:
            meta = ds._load_metadata(sid) or {}
            if (
                meta.get("status") == "running"
                and meta.get("last_turn_activity_at", 0.0) > baseline
            ):
                advanced = meta.get("last_turn_activity_at")
                break
            time.sleep(0.01)
        assert advanced is not None
        assert advanced >= baseline + 1.0
        # The turn is still open throughout: only the observer wrote this.
        with ds._SESSION_LOCK:
            assert ds._SESSIONS[sid]["status"] == "running"
    finally:
        client.release_turn.set()
    wait_for_status(parent, sid, "idle")


def test_watcher_write_amplitude_is_capped_mid_turn(monkeypatch):
    """T2: five activity steps inside one refresh window must not multiply
    durable writes — the observer persists at most once per refresh window
    (contract, not change-detector: amplitude stays bounded as activity
    frequency grows)."""
    monkeypatch.setattr(ds, "_OBSERVER_POLL_S", 0.05)
    monkeypatch.setattr(ds, "_ACTIVITY_REFRESH_MIN_S", 0.05)
    parent = Parent()
    sid, client = _blocked_running_session(parent)
    try:
        client.last_turn_activity_at = client.last_turn_activity_at + 1.0
        baseline = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            meta = ds._load_metadata(sid) or {}
            if meta.get("status") == "running":
                baseline = meta.get("last_turn_activity_at")
                break
            time.sleep(0.01)
        assert baseline is not None
        with ds._SESSION_LOCK:
            # The watermark contract makes the cap exact: the last successful
            # write's snapshot activity is what the next refresh compares to.
            assert ds._SESSIONS[sid]["last_persisted_activity"] == baseline

        # Five activity steps, all inside one refresh window of the baseline.
        for step in range(1, 6):
            client.last_turn_activity_at = baseline + 0.001 * step

        path = ds._metadata_path(sid)
        writes = 0
        last_mtime = path.stat().st_mtime_ns
        observed: set[float] = set()
        stop = time.time() + 0.4  # ~8 observer poll windows
        while time.time() < stop:
            meta = ds._load_metadata(sid) or {}
            mtime = path.stat().st_mtime_ns
            if mtime != last_mtime:
                writes += 1
                last_mtime = mtime
            if meta.get("status") == "running":
                activity = meta.get("last_turn_activity_at")
                if activity is not None:
                    observed.add(activity)
            time.sleep(0.002)

        assert observed, "observer never advertised mid-turn activity"
        assert writes <= 2
        assert len(observed) <= 2
    finally:
        client.release_turn.set()
    wait_for_status(parent, sid, "idle")


def test_watcher_stops_writing_after_turn_ends(monkeypatch):
    """T2: the observer dies with the turn. After the terminal persist there
    are no further durable writes for >= 3 poll windows and the turn thread
    is joinable. A regression guard for the observer mechanism itself (an
    unbounded observer would churn the store after every turn)."""
    monkeypatch.setattr(ds, "_OBSERVER_POLL_S", 0.05)
    monkeypatch.setattr(ds, "_ACTIVITY_REFRESH_MIN_S", 0.05)
    parent = Parent()
    sid, client = _blocked_running_session(parent)
    client.release_turn.set()
    wait_for_status(parent, sid, "idle")
    record = ds._SESSIONS[sid]
    deadline = time.time() + 5.0
    while time.time() < deadline and record["thread"].is_alive():
        time.sleep(0.01)
    assert not record["thread"].is_alive()

    while time.time() < deadline:
        meta = ds._load_metadata(sid) or {}
        if meta.get("status") == "idle":
            break
        time.sleep(0.01)

    path = ds._metadata_path(sid)
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    time.sleep(0.3)  # >= 3 observer poll windows
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime


def test_wedge_e2e_real_pi_client_durable_running_evidence(monkeypatch, tmp_path):
    """T5: end-to-end wedge repro on the REAL client boundary. While a live
    pi turn streams observable progress, durable metadata alone must show a
    running session with an advancing activity signal — the evidence the
    incident supervisor lacked when it could not tell a healthy long turn
    from a wedged one. Union v4 schema: the provider key replaces the
    observer branch's pid field."""
    from agent.pi_rpc_client import PiRPCClient as RealPiRPCClient

    script = tmp_path / "fake-pi-slow-turn"
    script.write_text(
        "#!%s\n" % sys.executable
        + "import json, sys, time\n"
        + "def send(o): print(json.dumps(o), flush=True)\n"
        + "send({'type':'ready'})\n"
        + "for line in sys.stdin:\n"
        + "    msg = json.loads(line)\n"
        + "    typ = msg.get('type')\n"
        + "    if typ == 'get_state':\n"
        + "        send({'type':'response','id':msg['id'],'success':True,'data':{'sessionId':'native-wedge-e2e'}})\n"
        + "    elif typ == 'prompt':\n"
        + "        send({'type':'response','id':msg['id'],'success':True})\n"
        + "        for i in range(200):\n"
        + "            time.sleep(0.02)\n"
        + "            send({'type':'message_update','assistantMessageEvent':{'type':'thinking_delta','delta':'tick %d' % i}})\n"
        + "    elif typ == 'abort':\n"
        + "        send({'type':'response','id':msg['id'],'success':True})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(ds, "PiRPCClient", RealPiRPCClient)
    monkeypatch.setenv("HERMES_PI_BIN", str(script))
    # The bare-parent shape must not inherit the deployment-wide assist
    # model (HERMES_ASSIST_MODEL/PROVIDER) a production host exports —
    # _pi_model_for_parent's last-resort branch would then derive a
    # non-empty pi_model and the "" assertion below would fail on any
    # host that runs the suite inside a configured Hermes deployment.
    monkeypatch.delenv("HERMES_PI_MODEL", raising=False)
    monkeypatch.delenv("HERMES_ASSIST_MODEL", raising=False)
    monkeypatch.delenv("HERMES_ASSIST_PROVIDER", raising=False)

    parent = Parent()
    started = payload(
        ds.delegate_session(action="start", parent_agent=parent, goal="slow turn")
    )
    sid = started["session_id"]
    wait_for_status(parent, sid, "running", timeout=30.0)

    with ds._SESSION_LOCK:
        ds._persist_metadata(ds._SESSIONS[sid])
    meta1 = ds._load_metadata(sid)
    assert meta1["version"] == ds._METADATA_VERSION
    assert meta1["status"] == "running"
    assert isinstance(meta1["last_turn_activity_at"], float)
    assert meta1["last_turn_activity_at"] > 0.0

    # Observable progress keeps advancing the durable activity signal.
    time.sleep(0.25)
    with ds._SESSION_LOCK:
        ds._persist_metadata(ds._SESSIONS[sid])
    meta2 = ds._load_metadata(sid)
    assert meta2["status"] == "running"
    assert meta2["last_turn_activity_at"] > meta1["last_turn_activity_at"]

    # Registry-loss equivalent: a fresh observer reads only durable state,
    # and the offline summary stays well-formed v4 (no error invented).
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    status = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert status["status"] == "offline"
    assert status["error"] is None
    assert status["native_session_id"] == "native-wedge-e2e"
    assert status["pi_model"] == ""

    stale["client"].close()


def test_open_circuit_storm_burst_fails_fast_without_taking_capacity(
    monkeypatch, tmp_path
):
    """Incident shape (d8fce7da recurrence #7): the 44-order injection
    storm kept re-dispatching into a provider that was already dead, and
    every doomed order occupied a delegate worker for its full stall
    window — the capacity-starvation amplifier. Once the circuit is open,
    a storm-sized burst of re-dispatches (live-session sends AND fresh
    starts) must be refused up front in bounded wall-clock, with zero
    turns reaching any client and nothing spawned."""
    monkeypatch.delenv("HERMES_PI_MODEL", raising=False)
    monkeypatch.setattr(ds, "_pi_model_for_parent", lambda _parent: "glm-4.6")
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    assert str(ds._SESSIONS[sid]["model"]) == "glm-4.6"
    _open_circuit("pi", "glm-4.6")

    burst_started = time.monotonic()
    for i in range(44):  # the incident's order count
        send = payload(
            ds.delegate_session(
                action="send",
                session_id=sid,
                message=f"storm order {i}",
                parent_agent=parent,
            )
        )
        assert "error" in send, i
        assert "circuit open" in send["error"], i
        fresh = payload(
            ds.delegate_session(
                action="start",
                goal=f"storm order {i}",
                parent_agent=parent,
            )
        )
        assert "error" in fresh, i
        assert "circuit open" in fresh["error"], i
    elapsed = time.monotonic() - burst_started

    # Refusals are ledger checks, not stall windows: 88 gated dispatches
    # complete in wall-clock a single doomed turn would have burned ~900x
    # over, and each error still names the remaining cooldown.
    assert elapsed < 2.0
    assert "retry after" in send["error"]
    # Zero delegate capacity consumed: the live session never ran a turn,
    # and no new client was spawned for any of the 44 fresh orders.
    assert ds._SESSIONS[sid]["client"].messages == []
    assert len(FakePiClient.instances) == 1
    with ds._SESSION_LOCK:
        assert ds._SESSIONS[sid]["status"] == "idle"


def test_turn_evidence_lands_in_dispatching_profile_home(monkeypatch, tmp_path):
    """F1 regression (A→B→A multiplex): worker threads do not inherit the
    home-override contextvar, so the durable evidence a turn produces —
    session metadata and the provider-health ledger update — must be pinned
    to the DISPATCHING profile at dispatch time. Without the pins the turn
    thread resolves the launch/default home and writes cross-profile, and a
    provider failure in profile B poisons the default profile's breaker."""
    from hermes_constants import (
        get_hermes_home,
        reset_hermes_home_override,
        set_hermes_home_override,
    )
    class RateLimitedClient(FakePiClient):
        """Fails with a provider-class error (classifies as 'rate_limit') so
        the turn records a provider failure in the health ledger."""

        def run_session_prompt(self, *args, **kwargs):
            raise Exception("429 Too Many Requests: rate limit exceeded")

    default_home = tmp_path / "default-home"
    home_b = tmp_path / "profile-b"
    home_c = tmp_path / "profile-c"
    for home in (default_home, home_b, home_c):
        home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(default_home))
    reset_delegate_health_ledger()
    # Re-bind the store root to the LIVE home so a pinned root discriminates
    # profiles (the autouse fixture otherwise pins one shared tmp store).
    monkeypatch.setattr(
        ds,
        "_session_store_root",
        lambda: get_hermes_home() / "cache" / "delegate-sessions",
    )

    class NoStartThread:
        """Capture the dispatch without running it — the worker body is
        driven synchronously below with the contextvar unset, which is
        exactly the view a plain threading.Thread gets."""

        def __init__(self, *, target, args, name, daemon):
            pass

        def start(self):
            pass

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(ds.threading, "Thread", NoStartThread)

    def durable_session_ids(home):
        store = home / "cache" / "delegate-sessions"
        return {
            json.loads(p.read_text())["session_id"] for p in store.glob("*.json")
        }

    # Dispatch under profile B with a provider that fails rate-limited: the
    # pins are captured in the parent (override active), then the worker
    # body runs with NO override — the exact environment of a real thread.
    token_b = set_hermes_home_override(home_b)
    try:
        parent_b = Parent("parent-b")
        started_b = payload(
            ds.delegate_session(
                action="start", parent_agent=parent_b, goal="fail fast"
            )
        )
        sid_b = started_b["session_id"]
        record_b = ds._SESSIONS[sid_b]
        record_b["client"] = RateLimitedClient()
    finally:
        reset_hermes_home_override(token_b)
    ds._run_turn(record_b, "fail fast", 30.0)

    assert record_b["_scope_store_root"] == home_b / "cache" / "delegate-sessions"
    assert sid_b in durable_session_ids(home_b)
    assert (home_b / "cache" / "delegate-provider-health.json").exists()

    # The worker had NO contextvar; the ledger pin is what routed the
    # failure to B's registry — prove the identity both ways.
    token = set_hermes_home_override(home_b)
    try:
        ledger_b = ds.get_delegate_health_ledger()
    finally:
        reset_hermes_home_override(token)
    assert record_b["_scope_ledger"] is ledger_b
    assert ds.get_delegate_health_ledger() is not ledger_b

    # A→B→A: a healthy turn under profile C pins C's scope too; the
    # launch/default home never receives anything from either worker.
    token_c = set_hermes_home_override(home_c)
    try:
        parent_c = Parent("parent-c")
        started_c = payload(
            ds.delegate_session(
                action="start", parent_agent=parent_c, goal="healthy work"
            )
        )
        sid_c = started_c["session_id"]
        record_c = ds._SESSIONS[sid_c]
        record_c["client"] = FakePiClient()
    finally:
        reset_hermes_home_override(token_c)
    ds._run_turn(record_c, "healthy work", 30.0)

    assert record_c["_scope_store_root"] == home_c / "cache" / "delegate-sessions"
    assert sid_c in durable_session_ids(home_c)
    assert sid_c not in durable_session_ids(home_b)

    assert not durable_session_ids(default_home)
    assert not (default_home / "cache" / "delegate-provider-health.json").exists()


def test_stale_persist_cannot_overwrite_terminal_evidence(monkeypatch):
    """F3 regression: an observer persist that snapshots the record as
    'running' but is descheduled before its write must never overwrite the
    terminal evidence a later persist installed. The write is dropped on a
    sequence mismatch, so a crashed delegate's durable status stays the
    last-writer-ordered terminal truth, not a resurrected 'running'."""
    record = {
        "session_id": "stale-persist-probe",
        "parent_session_id": "p",
        "backend": "pi",
        "model": "glm-4.6",
        "status": "running",
        "created_at": time.time(),
        "last_turn_activity_at": time.time(),
    }

    real_snapshot = ds._metadata_snapshot
    observer_snapshotted = threading.Event()
    release_observer = threading.Event()

    def gated_snapshot(rec):
        snapshot = real_snapshot(rec)
        if snapshot.get("status") == "running" and not observer_snapshotted.is_set():
            observer_snapshotted.set()
            # Hold the observer between its snapshot and its write while the
            # terminal evidence is persisted by the session thread.
            release_observer.wait(10)
        return snapshot

    monkeypatch.setattr(ds, "_metadata_snapshot", gated_snapshot)

    observer = threading.Thread(target=ds._persist_metadata, args=(record,))
    observer.start()
    assert observer_snapshotted.wait(10)

    record["status"] = "idle"
    record["outcome"] = "completed"
    ds._persist_metadata(record)

    path = ds._metadata_path("stale-persist-probe")
    assert json.loads(path.read_text())["status"] == "idle"

    release_observer.set()
    observer.join(10)
    after = json.loads(path.read_text())
    assert after["status"] == "idle", (
        "a stale observer persist must be dropped, not overwrite the "
        f"terminal evidence (got {after['status']!r})"
    )
