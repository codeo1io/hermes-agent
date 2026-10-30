"""Regression: delegated subprocesses must not inherit the gateway stdin."""

import subprocess
from types import SimpleNamespace


def test_pi_git_snapshot_uses_devnull_stdin(monkeypatch, tmp_path):
    from agent import pi_rpc_client

    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=" M changed.py\n")

    monkeypatch.setattr(pi_rpc_client.subprocess, "run", fake_run)
    client = object.__new__(pi_rpc_client.PiRPCClient)
    client._cwd = str(tmp_path)
    assert client._git_status_snapshot() == {"changed.py": " M changed.py"}
    assert observed["stdin"] == subprocess.DEVNULL


def test_opencode_server_spawn_uses_devnull_stdin(monkeypatch, tmp_path):
    from agent import opencode_client

    observed = {}
    proc = SimpleNamespace(poll=lambda: None)

    def fake_popen(*args, **kwargs):
        observed.update(kwargs)
        return proc

    monkeypatch.delenv("HERMES_OPENCODE_SERVER_URL", raising=False)
    monkeypatch.setattr(opencode_client, "_servers", {})
    monkeypatch.setattr(opencode_client, "_free_port", lambda: 12345)
    monkeypatch.setattr(opencode_client, "_opencode_command", lambda: ["opencode"])
    monkeypatch.setattr(opencode_client, "Path_home", lambda: str(tmp_path))
    monkeypatch.setattr(opencode_client, "_opencode_config_fingerprint", lambda: "test")
    monkeypatch.setattr(opencode_client, "_wait_ready", lambda *args: None)
    monkeypatch.setattr(opencode_client, "_ensure_shutdown_hook", lambda: None)
    monkeypatch.setattr(opencode_client.subprocess, "Popen", fake_popen)

    handle = opencode_client.acquire_opencode_server()
    assert handle.proc is proc
    assert observed["stdin"] == subprocess.DEVNULL
    assert observed["start_new_session"] is True
