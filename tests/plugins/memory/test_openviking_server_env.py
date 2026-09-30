"""Contract for the openviking-server spawn env (memory provider plugin).

The vendored server child is long-lived. Two invariants: it never inherits
PYTHONPATH (the Desktop backend's Hermes venv would shadow the server's own
site-packages and, on Windows, lock the venv's .pyd files — #78153), and it
never inherits the gateway's Tier-1 secrets. Regression for the
``os.environ.copy()`` spawn.
"""
from __future__ import annotations

from plugins.memory.openviking import _server_child_env


def test_server_env_has_no_pythonpath_and_no_tier1_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PYTHONPATH", "/opt/hermes/venv/lib")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-tier1")
    monkeypatch.setenv("HERMES_DESKTOP", "1")

    env = _server_child_env()

    # PYTHONPATH must not shadow the server's own interpreter state (#78153).
    assert "PYTHONPATH" not in env
    # The gateway's secrets are not the server's business.
    assert "ANTHROPIC_API_KEY" not in env
    assert "HERMES_DESKTOP" not in env
    # The server resolves its own interpreter/tools through the base.
    assert env["PATH"] == "/usr/bin:/bin"
