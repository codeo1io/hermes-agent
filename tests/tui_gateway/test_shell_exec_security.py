"""Security-boundary regressions for the TUI ``shell.exec`` RPC.

The RPC crosses the JSON-RPC boundary and its output can be persisted in the
transcript, so it must never echo credentials back or hand them to the child
process environment (the long-lived TUI server process holds every API key in
``os.environ``).
"""

from __future__ import annotations

import subprocess

import tui_gateway.server as srv
from agent import redact


def _call(method: str, params: dict) -> dict:
    """Invoke a registered RPC method and return its result dict."""
    envelope = srv._methods[method](1, params)
    return envelope["result"]


def test_shell_exec_scrubs_child_env_and_force_redacts_rpc_output(monkeypatch):
    secret = "sk-shell-exec-secret-1234567890"
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"visible\n{secret}\n",
            stderr=f"diagnostic {secret}",
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    # Prove the safety boundary holds even when profile redaction is disabled.
    monkeypatch.setattr(redact, "_redact_enabled", lambda: False)
    monkeypatch.setattr(srv.subprocess, "run", fake_run)

    response = _call("shell.exec", {"command": "echo safe"})

    # The child env must not inherit provider credentials from the server process.
    assert "OPENROUTER_API_KEY" not in captured["env"]
    # Output crossing the RPC boundary is redacted regardless of the redaction switch.
    assert secret not in response["stdout"]
    assert secret not in response["stderr"]
    assert "visible" in response["stdout"]


def test_shell_exec_tails_output_after_redaction(monkeypatch):
    """The transcript-facing tails stay bounded: redaction happens, then the slice."""
    secret = "sk-shell-exec-tail-1234567890"
    filler = "x" * 9000

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout=f"{filler}\n{secret}\n", stderr="")

    monkeypatch.setattr(redact, "_redact_enabled", lambda: False)
    monkeypatch.setattr(srv.subprocess, "run", fake_run)

    response = _call("shell.exec", {"command": "echo safe"})

    assert len(response["stdout"]) <= 4000
    assert secret not in response["stdout"]
