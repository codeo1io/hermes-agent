"""Hermetic coverage for the OpenCode delegate backend client.

No network, no real ``opencode`` binary: the HTTP transport and the server
process are injected fakes.  Payload shapes mirror the opencode 1.18.x server
OpenAPI surface (probed live 2026-08-24): ``prompt_async`` returns HTTP 204,
messages are ``{info:{id,role,...}, parts:[{type:"text",text},...]}``, and
question replies are ``{answers:[[label], ...]}`` with one entry per question.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import threading
import time
from pathlib import Path

import pytest

import agent.opencode_client as oc
from agent.opencode_client import OpenCodeClient


class FakeTransport:
    """Scriptable HTTP transport recording requests in order."""

    def __init__(self, responses, default=None):
        # responses: list of (status, obj_or_text) or callables
        # default: repeatable (status, obj_or_text) served once scripted
        # responses run out — lets polling loops run without exhaustively
        # scripting every tick.
        self.responses = list(responses)
        self.default = default
        self.requests: list[tuple[str, str, dict | None]] = []

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if self.responses:
            nxt = self.responses.pop(0)
        elif self.default is not None:
            nxt = self.default
        else:
            raise AssertionError(f"unexpected request after scripted responses: {method} {path}")
        if callable(nxt):
            nxt = nxt(method, path, body)
        status, payload = nxt
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return status, text


def _msg(mid, role, text, created=1):
    return {
        "info": {"id": mid, "sessionID": "ses_x", "role": role, "time": {"created": created}},
        "parts": [{"id": f"prt_{mid}", "type": "text", "text": text}],
    }


def make_client(transport, answerer=None, preset_session=True):
    client = OpenCodeClient(
        persistent_session=True,
        session_id="hermes-test",
        session_name="Hermes test",
        acp_cwd="/tmp",
        question_answerer=answerer,
        transport_factory=lambda cwd: transport,
    )
    if preset_session:
        # Mirror the delegate-tool flow: the tool layer opens the native
        # session (start) before dispatching turns, so scripted responses
        # below begin at prompt_async.  The start test itself disables this.
        client.native_session_id = "ses_x"
    return client


def test_start_creates_session_and_returns_native_id():
    transport = FakeTransport([(200, {"id": "ses_abc", "title": "Hermes test"})])
    client = make_client(transport, preset_session=False)
    state = client.start(timeout=5.0)
    assert state["sessionId"] == "ses_abc"
    method, path, body = transport.requests[0]
    assert method == "POST" and path.startswith("/session")
    assert "directory" in path
    assert body == {"title": "Hermes test"}


def test_run_prompt_waits_for_new_assistant_text():
    final = [_msg("m1", "user", "hi", 1), _msg("m2", "assistant", "hello!", 2)]
    transport = FakeTransport(
        [
            (204, ""),  # prompt_async accepted
            (200, [_msg("m1", "user", "hi", 1)]),  # baseline snapshot
            (200, [_msg("m1", "user", "hi", 1)]),  # poll 1: nothing new
        ],
        default=lambda _m, _p, _b: (200, final if _p.startswith("/session") else []),
    )
    client = make_client(transport)
    result = client.run_session_prompt("hi", timeout_seconds=5.0)
    assert result["text"] == "hello!"
    assert result["state"]["sessionId"] == "ses_x"
    assert result["duration_s"] >= 0.0


def test_run_prompt_timeout_aborts_and_raises():
    transport = FakeTransport([(204, "")], default=(200, []))
    client = make_client(transport)
    with pytest.raises(TimeoutError):
        client.run_session_prompt("hi", timeout_seconds=0.2, poll_interval=0.05)
    methods = [r[0] for r in transport.requests]
    assert "POST" in methods and any("abort" in r[1] for r in transport.requests)


def _question_script(question, assistant_text="done", mid="m2"):
    """Scripted transport flow: prompt, pending question, then a reply-triggered
    assistant reply.  The assistant message only appears after the question
    reply/reject was actually POSTed, proving the answer path unblocked the turn."""
    state: dict = {"replied": False}
    empty_msgs = (200, [_msg("m1", "user", "hi", 1)])
    final_msgs = (200, [_msg("m1", "user", "hi", 1), _msg(mid, "assistant", assistant_text, 2)])
    qdir = "?" + urllib.parse.urlencode({"directory": "/tmp"})

    def questions(_m, path, _b):
        # Only answer the scoped listing; the completion check polls it too.
        return (200, [question]) if (not state["replied"] and path == f"/question{qdir}") else (200, [])

    def messages(_m, _p, _b):
        return final_msgs if state["replied"] else empty_msgs

    def capture(method, path, body):
        if method == "POST" and "/question/" in path and (f"/reply{qdir}" in path or f"/reject{qdir}" in path):
            state["replied"] = True
            return (204, "")
        raise AssertionError(f"unexpected POST in question script: {path}")

    def route(method, path, body):
        # Repeatable router served once the scripted list runs out: any number
        # of extra question/message polls is fine, shape follows state.
        if path.startswith("/question"):
            return questions(method, path, body)
        if path.startswith("/session"):
            return messages(method, path, body)
        raise AssertionError(f"unexpected request in question script: {method} {path}")

    return [
        (204, ""),  # prompt_async
        empty_msgs,  # baseline snapshot (taken before the poll loop)
        questions,  # tick 1: pending question found
        capture,  # reply/reject POST unblocks the turn
    ], route


def test_question_answered_with_reply_payload():
    question = {
        "id": "que_1",
        "sessionID": "ses_x",
        "questions": [
            {
                "question": "Which color?",
                "header": "Color",
                "options": [{"label": "red", "description": "r"}, {"label": "blue", "description": "b"}],
                "multiple": False,
                "custom": False,
            }
        ],
    }
    seen: dict = {}

    def answerer(method, question_text, options):
        seen["args"] = (method, question_text, list(options))
        return "blue"

    transport = scripted, router = _question_script(question)
    transport = FakeTransport(scripted, default=router)
    client = make_client(transport, answerer=answerer)
    result = client.run_session_prompt("hi", timeout_seconds=5.0, poll_interval=0.05)
    assert result["text"] == "done"
    assert seen["args"][0] == "select"
    assert seen["args"][1] == "Which color?"
    assert seen["args"][2] == ["red", "blue"]
    qdir = client._qdir()
    reply = [r for r in transport.requests if r[1] == f"/question/que_1/reply{qdir}"]
    assert reply and reply[0][2] == {"answers": [["blue"]]}


def test_question_unanswerable_rejected():
    question = {
        "id": "que_2",
        "sessionID": "ses_x",
        "questions": [{"question": "Q?", "header": "H", "options": [], "multiple": False, "custom": False}],
    }
    transport = scripted, router = _question_script(question, assistant_text="ok")
    transport = FakeTransport(scripted, default=router)
    client = make_client(transport, answerer=lambda *a: None)
    result = client.run_session_prompt("hi", timeout_seconds=5.0, poll_interval=0.05)
    assert result["text"] == "ok"
    qdir = client._qdir()
    assert any(r[1] == f"/question/que_2/reject{qdir}" for r in transport.requests)


def test_question_for_other_session_ignored():
    question = {"id": "que_3", "sessionID": "ses_OTHER", "questions": [{"question": "?", "header": "H", "options": []}]}
    final = [_msg("m1", "user", "hi", 1), _msg("m2", "assistant", "ok", 2)]

    def route(method, path, body):
        # Repeatable default: questions stay foreign, messages settle on the
        # final transcript so the completion convergence can trigger.
        if path.startswith("/question"):
            return (200, [question])
        return (200, final)

    transport = FakeTransport(
        [
            (204, ""),  # prompt_async
            (200, [_msg("m1", "user", "hi", 1)]),  # baseline snapshot
        ],
        default=route,
    )
    client = make_client(transport, answerer=lambda *a: pytest.fail("must not answer other sessions"))
    assert client.run_session_prompt("hi", timeout_seconds=5.0, poll_interval=0.05)["text"] == "ok"
    assert not any("/question/que_3/reply" in r[1] for r in transport.requests)


def test_abort_and_messages_and_close():
    transport = FakeTransport(
        [
            (204, ""),  # abort
            (200, [_msg("m1", "user", "hi", 1), _msg("m2", "assistant", "ok", 2)]),
        ],
        default=(200, []),
    )
    client = make_client(transport)
    client.abort(timeout=5.0)
    assert any("abort" in r[1] for r in transport.requests)
    messages = client.get_messages(timeout=5.0)
    assert messages[-1]["info"]["role"] == "assistant"
    client.close()  # no server ref -> no crash


def test_get_messages_missing_session_is_error():
    transport = FakeTransport([(404, json.dumps({"name": "NotFoundError", "data": {"message": "SessionNotFound"}}))])
    client = make_client(transport)
    with pytest.raises(RuntimeError):
        client.get_messages(timeout=5.0)


def test_server_singleton_spawn_readiness_and_release(tmp_path, monkeypatch):
    stub = tmp_path / "opencode-stub.py"
    stub.write_text(
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path.startswith('/session'):\n"
        "            self.send_response(200); self.end_headers(); self.wfile.write(b'[]')\n"
        "        else:\n"
        "            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')\n"
        "    def log_message(self, *a): pass\n"
        "HTTPServer(('127.0.0.1', port), H).serve_forever()\n"
    )
    monkeypatch.setenv("HERMES_OPENCODE_BIN", f"{sys.executable} {stub}")
    monkeypatch.delenv("HERMES_OPENCODE_SERVER_URL", raising=False)
    oc._reset_server_singleton()
    try:
        handle = oc.acquire_opencode_server(working_directory=str(tmp_path))
        assert handle.base_url.startswith("http://127.0.0.1:")
        # Acquires for DIFFERENT directories reuse the same single server.
        other = tmp_path / "other"
        other.mkdir()
        again = oc.acquire_opencode_server(working_directory=str(other))
        assert again is handle
        import urllib.request

        with urllib.request.urlopen(f"{handle.base_url}/session", timeout=5) as resp:
            assert resp.status == 200
        # Release does NOT terminate the shared server — it stays warm.
        oc.release_opencode_server(handle)
        oc.release_opencode_server(handle)
        time.sleep(0.3)
        assert handle.proc.poll() is None
        assert oc._server_state()
        # Explicit shutdown terminates it.
        oc.shutdown_opencode_server()
        deadline = time.time() + 10
        while handle.proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        assert handle.proc.poll() is not None
        assert not oc._server_state()
    finally:
        oc._reset_server_singleton()


def _write_opencode_stub(path):
    path.write_text(
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'[]')\n"
        "    def log_message(self, *a): pass\n"
        "HTTPServer(('127.0.0.1', port), H).serve_forever()\n"
    )


def test_config_fingerprint_tracks_xdg_and_inline_content(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    config_dir = xdg / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.jsonc"
    config.write_text('{"default_agent":"build"}')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)

    first = oc._opencode_config_fingerprint()
    config.write_text('{"default_agent":"plan"}')
    second = oc._opencode_config_fingerprint()
    assert first != second

    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model":"one"}')
    third = oc._opencode_config_fingerprint()
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model":"two"}')
    fourth = oc._opencode_config_fingerprint()
    assert third != fourth


def test_external_server_url_env_short_circuits_spawn(monkeypatch):
    monkeypatch.setenv("HERMES_OPENCODE_SERVER_URL", "http://127.0.0.1:9999")
    oc._reset_server_singleton()
    try:
        handle = oc.acquire_opencode_server()
        assert handle.base_url == "http://127.0.0.1:9999"
        assert handle.proc is None  # externally managed, never terminated by us
        oc.release_opencode_server(handle)
    finally:
        oc._reset_server_singleton()


def test_is_dead_tracks_server_process(monkeypatch):
    monkeypatch.delenv("HERMES_OPENCODE_SERVER_URL", raising=False)

    class DeadProc:
        returncode = 3

        def poll(self):
            return 3

    transport = FakeTransport([(200, {"id": "ses_x"})])
    client = make_client(transport)
    client._server_handle = type("H", (), {"proc": DeadProc(), "refcount": 1})()
    assert client.is_dead()
    client._server_handle = None
    assert not client.is_dead()


def test_server_recycles_idle_process_on_config_change(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    procs = []

    def fake_popen(*args, **kwargs):
        proc = FakeProc()
        procs.append(proc)
        return proc

    fingerprints = iter([("old",), ("new",), ("new",)])
    monkeypatch.setattr(oc, "_opencode_config_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(oc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(oc, "_free_port", iter([41000, 41001]).__next__)
    monkeypatch.setattr(oc, "_wait_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(oc, "_opencode_command", lambda: ["opencode"])
    monkeypatch.delenv("HERMES_OPENCODE_SERVER_URL", raising=False)
    oc._reset_server_singleton()
    try:
        first = oc.acquire_opencode_server()
        oc.release_opencode_server(first)
        second = oc.acquire_opencode_server()
        assert second is not first
        assert procs[0].terminated is True
        assert first not in oc._retired_servers
        oc.release_opencode_server(second)
    finally:
        oc.shutdown_opencode_server()
        oc._reset_server_singleton()


def test_server_rolls_over_on_config_change_without_interrupting_active_clients(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    procs = []

    def fake_popen(*args, **kwargs):
        proc = FakeProc()
        procs.append(proc)
        return proc

    fingerprints = iter([("old",), ("new",), ("new",)])
    monkeypatch.setattr(oc, "_opencode_config_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(oc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(oc, "_free_port", iter([41001, 41002]).__next__)
    monkeypatch.setattr(oc, "_wait_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(oc, "_opencode_command", lambda: ["opencode"])
    monkeypatch.delenv("HERMES_OPENCODE_SERVER_URL", raising=False)
    oc._reset_server_singleton()
    try:
        first = oc.acquire_opencode_server()
        assert first.refcount == 1

        second = oc.acquire_opencode_server()
        assert second is not first
        assert second.base_url != first.base_url
        assert first.retired is True
        assert first in oc._retired_servers
        assert procs[0].terminated is False

        oc.release_opencode_server(first)
        assert procs[0].terminated is True
        assert first not in oc._retired_servers

        oc.release_opencode_server(second)
        assert procs[1].terminated is False
    finally:
        oc.shutdown_opencode_server()
        oc._reset_server_singleton()


def test_server_reuses_warm_process_when_config_unchanged(monkeypatch):
    class FakeProc:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    proc = FakeProc()
    monkeypatch.setattr(oc, "_opencode_config_fingerprint", lambda: ("same",))
    monkeypatch.setattr(oc.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(oc, "_free_port", lambda: 41003)
    monkeypatch.setattr(oc, "_wait_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(oc, "_opencode_command", lambda: ["opencode"])
    monkeypatch.delenv("HERMES_OPENCODE_SERVER_URL", raising=False)
    oc._reset_server_singleton()
    try:
        first = oc.acquire_opencode_server()
        second = oc.acquire_opencode_server()
        assert second is first
        assert first.refcount == 2
        assert not oc._retired_servers
        oc.release_opencode_server(first)
        oc.release_opencode_server(second)
    finally:
        oc.shutdown_opencode_server()
        oc._reset_server_singleton()


def test_config_fingerprint_tracks_xdg_opencode_files(tmp_path, monkeypatch):
    config_home = tmp_path / "xdg"
    config_dir = config_home / "opencode"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "opencode.jsonc"
    config_file.write_text("{\"default_agent\":\"build\"}")
    monkeypatch.setattr(oc.os, "getenv", lambda name, default="": str(config_home) if name == "XDG_CONFIG_HOME" else default)

    first = oc._opencode_config_fingerprint()
    config_file.write_text("{\"default_agent\":\"plan\",\"plugin\":[\"systematic\"]}")
    second = oc._opencode_config_fingerprint()

    assert first != second
    assert first[0] == str(config_dir)
