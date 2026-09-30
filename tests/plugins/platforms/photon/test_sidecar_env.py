"""Contract for the Photon sidecar spawn env (adapter._sidecar_env).

The sidecar is a detached node process that outlives the gateway — its
environment is readable for its whole lifetime, so it must carry the project
wiring and nothing else. Regression for the full ``os.environ.copy()`` spawn.
"""
from __future__ import annotations

from plugins.platforms.photon.adapter import _sidecar_env


def test_sidecar_env_carries_project_wiring_and_no_tier1_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-tier1")
    monkeypatch.setenv("PHOTON_STALE_OPERATOR_VAR", "must-not-cross")

    env = _sidecar_env("proj-1", "proj-secret-1", 8123, "127.0.0.1", "sidecar-token-1")

    # Project wiring the sidecar is configured through.
    assert env["PHOTON_PROJECT_ID"] == "proj-1"
    assert env["PHOTON_PROJECT_SECRET"] == "proj-secret-1"
    assert env["PHOTON_SIDECAR_PORT"] == "8123"
    assert env["PHOTON_SIDECAR_BIND"] == "127.0.0.1"
    assert env["PHOTON_SIDECAR_TOKEN"] == "sidecar-token-1"
    # Stdin-EOF watch is the only leash on an orphaned sidecar — it must be on.
    assert env["PHOTON_SIDECAR_WATCH_STDIN"] == "1"
    # Resolution base still present.
    assert env["PATH"] == "/usr/bin:/bin"
    # Tier-1 secrets and unrelated operator vars never cross.
    assert "ANTHROPIC_API_KEY" not in env
    assert "PHOTON_STALE_OPERATOR_VAR" not in env
