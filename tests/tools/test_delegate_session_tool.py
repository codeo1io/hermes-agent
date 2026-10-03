"""Regression coverage for persistent Pi delegate_session semantics."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

import tools.delegate_session_tool as ds


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
    assert len(BootstrapFailingPi.instances) == 2
    assert BootstrapFailingPi.instances[0].session_id == sid
    assert BootstrapFailingPi.instances[1].session_id == resumed["native_session_id"]
    assert ds._load_metadata(sid)["native_session_id"] == resumed["native_session_id"]


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


# ---------------------------------------------------------------------------
# Provider-health surface: typed failure classes + (backend, model)-keyed
# fail-fast breaker (2026-10-02 storm regression).
# ---------------------------------------------------------------------------


class StormPiClient(FakePiClient):
    """pi backend mid provider-storm: armed turns fail with storm text.

    Each armed failure raises ``<failure_text> (attempt N)`` where N is the
    1-based ordinal among the armed failures — the async dispatch makes a
    specific turn's failure observable only through the status payload's
    bounded error text, so tests wait on that ordinal.
    """

    fail_next = 0
    armed = 0
    failure_text = (
        "429 rate_limit_error: All credentials for model glm-4.6 are cooling down"
    )

    def run_session_prompt(self, message, *, timeout_seconds=900.0):
        cls = type(self)
        if cls.fail_next > 0:
            ordinal = cls.armed - cls.fail_next + 1
            cls.fail_next -= 1
            raise Exception(f"{cls.failure_text} (attempt {ordinal})")
        return super().run_session_prompt(message, timeout_seconds=timeout_seconds)


def _arm_storm(monkeypatch, failures: int, text: str | None = None) -> None:
    """Point the tool at ``StormPiClient`` and arm ``failures`` failing turns.

    Armed through monkeypatch so the class state (including the failure
    text) is restored after each test — a bare class assignment would leak
    the storm into later tests sharing this file's process.
    """
    monkeypatch.setattr(ds, "PiRPCClient", StormPiClient)
    monkeypatch.setattr(StormPiClient, "fail_next", failures)
    monkeypatch.setattr(StormPiClient, "armed", failures)
    if text is not None:
        monkeypatch.setattr(StormPiClient, "failure_text", text)


def _start(parent: Parent, *, goal: str | None = None) -> dict:
    return payload(
        ds.delegate_session(action="start", goal=goal, parent_agent=parent)
    )


def wait_for_error_text(
    parent: Parent, sid: str, needle: str, timeout: float = 2.0
) -> dict:
    deadline = time.time() + timeout
    latest: dict = {}
    while time.time() < deadline:
        latest = payload(
            ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
        )
        if needle in str(latest.get("error") or ""):
            return latest
        time.sleep(0.01)
    raise AssertionError(f"session error never contained {needle!r}: {latest}")


def test_start_fails_fast_when_provider_circuit_opens(monkeypatch):
    """2026-10-02 storm regression: after two provider-class turn failures the
    next dispatch must fail fast instead of paying the full spawn + turn +
    stall-timeout cost again — retries amplified the storm into host
    thread/fork/ENOSPC exhaustion."""
    parent = Parent()
    _arm_storm(monkeypatch, 2)

    first = _start(parent, goal="first dispatch")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "(attempt 1)")

    second = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="second dispatch", parent_agent=parent
        )
    )
    assert second["success"] is True
    wait_for_error_text(parent, sid, "(attempt 2)")

    # Circuit open: a third start must fail fast BEFORE spawning any client.
    gate = _start(parent, goal="third dispatch")
    assert "provider_unavailable: pi/" in gate["error"], gate
    assert len(StormPiClient.instances) == 1

    # The health action is itself part of the evidence plane: it reports the
    # open circuit while the outage is in progress.
    health = payload(ds.delegate_session(action="health", parent_agent=parent))
    assert health["providers"]["pi/"]["state"] == "open"
    assert health["providers"]["pi/"]["error_class"] == "rate_limit"
    assert health["providers"]["pi/"]["retry_after_s"] >= 1

    # D4 invariant: read actions stay available while the circuit is open —
    # the evidence plane must never be gated by the outage it describes.
    readable = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert readable["success"] is True
    assert readable["error_class"] == "rate_limit"
    listed = payload(ds.delegate_session(action="list", parent_agent=parent))
    assert listed["success"] is True
    assert any(row.get("session_id") == sid for row in listed["sessions"])

    # The same lane's follow-up paths are gated too.
    steer = payload(
        ds.delegate_session(
            action="steer", session_id=sid, message="redirect", parent_agent=parent
        )
    )
    assert "provider_unavailable: pi/" in steer["error"], steer
    send = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="another", parent_agent=parent
        )
    )
    assert "provider_unavailable: pi/" in send["error"], send


def test_followup_start_on_live_session_respects_provider_gate(monkeypatch):
    parent = Parent()
    _arm_storm(monkeypatch, 2)

    stormy = _start(parent, goal="will fail once")
    sid_a = stormy["session_id"]
    wait_for_error_text(parent, sid_a, "(attempt 1)")
    idle = _start(parent)
    sid_b = idle["session_id"]

    payload(
        ds.delegate_session(
            action="send", session_id=sid_a, message="second failure", parent_agent=parent
        )
    )
    wait_for_error_text(parent, sid_a, "(attempt 2)")

    follow = payload(
        ds.delegate_session(
            action="start", session_id=sid_b, goal="follow-up turn", parent_agent=parent
        )
    )
    assert "provider_unavailable: pi/" in follow["error"], follow
    # No prompt was delivered to the idle session's client.
    client_b = StormPiClient.instances[-1]
    assert client_b.messages == []


def test_health_action_reports_provider_rows(monkeypatch):
    parent = Parent()
    _arm_storm(monkeypatch, 1)
    first = _start(parent, goal="single provider failure")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "(attempt 1)")

    health = payload(ds.delegate_session(action="health", parent_agent=parent))
    assert health["success"] is True
    row = health["providers"]["pi/"]
    assert row["error_class"] == "rate_limit"
    # One provider failure is evidence, not an outage: no circuit opened.
    assert row["state"] == "closed"

    status = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert status["error_class"] == "rate_limit"


def test_successful_turn_clears_error_class(monkeypatch):
    parent = Parent()
    _arm_storm(monkeypatch, 1)
    first = _start(parent, goal="fail once")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "(attempt 1)")

    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="now succeed", parent_agent=parent
        )
    )
    wait_for_status(parent, sid, "idle")
    status = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert status["error_class"] is None
    # The ledger row keeps the last failure class as durable evidence (the
    # storm story must survive recovery) but reports health: counters reset.
    health = payload(ds.delegate_session(action="health", parent_agent=parent))
    row = health["providers"]["pi/"]
    assert row["state"] == "closed"
    assert row["consecutive_failures"] == 0
    assert row["opens"] == 0


def test_host_pressure_failure_is_evidence_but_never_gates(monkeypatch):
    """Host-resource casualties of a storm (thread/fork/ENOSPC) are typed
    evidence but must not gate dispatch: gating on them would amplify the
    very outage being survived."""
    parent = Parent()
    _arm_storm(monkeypatch, 2, "can't start new thread")

    first = _start(parent, goal="fails")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "(attempt 1)")
    payload(
        ds.delegate_session(
            action="send", session_id=sid, message="fails again", parent_agent=parent
        )
    )
    wait_for_error_text(parent, sid, "(attempt 2)")

    health = payload(ds.delegate_session(action="health", parent_agent=parent))
    assert health["providers"]["pi/"]["error_class"] == "resource_exhausted"
    assert health["providers"]["pi/"]["state"] == "closed"

    # Even after two host-pressure failures a fresh dispatch still runs.
    third = _start(parent, goal="still allowed")
    assert third["success"] is True, third
    sid3 = third["session_id"]
    wait_for_status(parent, sid3, "idle")


def test_bootstrap_failure_is_classified_without_gating(monkeypatch):
    """A start that cannot even bootstrap its client is typed evidence
    (transport) with today's bounded error text unchanged — and never opens
    the provider circuit: a spawn hiccup must not strand the lane."""
    parent = Parent()

    class NeverStartingPi(FakePiClient):
        instances = []

        def start(self, *, timeout=30.0):
            raise TimeoutError("pi did not answer command 'get_state'")

    monkeypatch.setattr(ds, "PiRPCClient", NeverStartingPi)

    result = _start(parent)
    assert result["error"] == (
        "Could not start pi delegate session: pi did not answer command 'get_state'"
    )

    health = payload(ds.delegate_session(action="health", parent_agent=parent))
    row = health["providers"]["pi/"]
    assert row["error_class"] == "transport"
    assert row["state"] == "closed"


def test_dead_process_failure_is_transport_evidence_not_gating(monkeypatch):
    """A pi RPC process that died mid-session surfaces the existing
    dead-client error plus error_class='transport' — evidence only, never a
    provider-circuit opening (process death is not provider health)."""
    parent = Parent()
    started = _start(parent)
    sid = started["session_id"]
    wait_for_status(parent, sid, "idle")
    client = FakePiClient.instances[-1]

    class _DeadProc:
        returncode = 1

        def poll(self):
            return 1

    client._proc = _DeadProc()

    send = payload(
        ds.delegate_session(
            action="send", session_id=sid, message="into the void", parent_agent=parent
        )
    )
    assert "exited with code 1" in send["error"], send

    status = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert status["error_class"] == "transport"
    health = payload(ds.delegate_session(action="health", parent_agent=parent))
    assert health["providers"]["pi/"]["error_class"] == "transport"
    assert health["providers"]["pi/"]["state"] == "closed"


def test_unknown_action_message_lists_health():
    parent = Parent()
    result = payload(ds.delegate_session(action="bogus", parent_agent=parent))
    assert "health" in result["error"]


def test_prune_never_deletes_provider_health_ledger(tmp_path, monkeypatch):
    """The provider-health ledger lives in cache/ OUTSIDE the pruned
    delegate-sessions store: durable health memory must survive the 500-file
    metadata cap."""
    from pathlib import Path as _Path

    import agent.delegate_provider_health as dph
    from hermes_constants import get_hermes_home

    parent = Parent()
    _arm_storm(monkeypatch, 1)
    first = _start(parent, goal="one recorded failure")
    wait_for_error_text(parent, first["session_id"], "(attempt 1)")

    ledger = _Path(get_hermes_home()) / "cache" / "delegate-provider-health.json"
    deadline = time.monotonic() + 5.0
    while not ledger.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ledger.is_file(), "ledger must be recorded on turn failure"

    store = ds._session_store_root()
    store.mkdir(parents=True, exist_ok=True)
    for i in range(505):
        (store / f"s{i:04d}.json").write_text("{}", encoding="utf-8")
    ds._prune_durable_metadata(store)

    remaining = sorted(p.name for p in store.glob("*.json"))
    assert len(remaining) == 500
    assert ledger.is_file()


# -- durable failure evidence (v4 metadata; 2026-10-02 storm) -----------------


def wait_for_durable(sid, predicate, timeout=5.0):
    """Wait until the persisted metadata reflects ``predicate``.

    The turn thread updates the live record before its final
    ``_persist_metadata`` write; waiting on the durable file is what proves
    persistence actually happened (not just the in-memory state).
    """
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = ds._load_metadata(sid) or {}
        if predicate(last):
            return last
        time.sleep(0.01)
    return last


def test_durable_metadata_persists_failure_evidence(monkeypatch):
    """v4 metadata snapshot: status/error_class/error/consecutive_failures
    persist durably so a restarted supervisor inherits the failure diagnosis
    instead of rediscovering it by paying the spawn + stall cost again."""
    parent = Parent()
    _arm_storm(monkeypatch, 1)
    first = _start(parent, goal="storm goal prompt text")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "(attempt 1)")

    meta = wait_for_durable(
        sid, lambda m: m.get("status") == "error" and m.get("error_class") == "rate_limit"
    )
    assert meta["version"] == 4
    assert "(attempt 1)" in str(meta["error"])
    assert meta["consecutive_failures"] == 1
    assert isinstance(meta["pi_model"], str)
    assert isinstance(meta["last_turn_activity_at"], float)
    # Evidence, never conversation: durable metadata still stores no prompt
    # text (the module's authorization surface stays IDs/cwd/workspace).
    raw = ds._metadata_path(sid).read_text(encoding="utf-8")
    assert "storm goal prompt text" not in raw


def test_durable_error_text_is_bounded(monkeypatch):
    parent = Parent()
    _arm_storm(monkeypatch, 1, text="x" * 5000)
    first = _start(parent, goal="long failure text")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "xxx")

    meta = wait_for_durable(
        sid, lambda m: m.get("status") == "error" and len(str(m.get("error"))) > 2000
    )
    assert len(str(meta["error"])) <= 2000


def test_offline_status_survives_registry_loss(monkeypatch):
    """The storm diagnosis must survive a gateway restart: after registry
    loss, offline status/list rows report the persisted error state and
    error_class instead of a bare "offline"."""
    parent = Parent()
    _arm_storm(monkeypatch, 1)
    first = _start(parent, goal="will fail once")
    sid = first["session_id"]
    wait_for_error_text(parent, sid, "(attempt 1)")
    wait_for_durable(
        sid, lambda m: m.get("status") == "error" and m.get("error_class") == "rate_limit"
    )

    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    offline = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert offline["success"] is True
    assert offline["status"] == "error"
    assert offline["error_class"] == "rate_limit"
    assert "(attempt 1)" in str(offline["error"])
    assert "resume" in (offline.get("note") or "").lower()

    listed = payload(ds.delegate_session(action="list", parent_agent=parent))
    row = next(r for r in listed["sessions"] if r["session_id"] == sid)
    assert row["status"] == "error"
    assert row["error_class"] == "rate_limit"


def test_offline_rows_report_liveness_not_last_idle_state():
    """Liveness does not survive a restart: an unloaded idle session stays
    "offline" rather than masquerading as a live idle row; only durable
    terminal facts (error/closed) are reflected in offline rows."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()
    idle = payload(
        ds.delegate_session(action="status", session_id=sid, parent_agent=parent)
    )
    assert idle["status"] == "offline"

    stopped = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid2 = stopped["session_id"]
    payload(ds.delegate_session(action="stop", session_id=sid2, parent_agent=parent))
    with ds._SESSION_LOCK:
        stale2 = ds._SESSIONS.pop(sid2)
    closed = payload(
        ds.delegate_session(action="status", session_id=sid2, parent_agent=parent)
    )
    assert closed["status"] == "closed"


def test_clean_turn_persists_clean_durable_state():
    parent = Parent()
    started = _start(parent, goal="succeeds")
    sid = started["session_id"]
    wait_for_status(parent, sid, "idle")

    meta = wait_for_durable(
        sid, lambda m: m.get("version") == 4 and m.get("status") == "idle"
    )
    assert meta["error"] is None
    assert meta["error_class"] is None
    assert meta["consecutive_failures"] == 0
