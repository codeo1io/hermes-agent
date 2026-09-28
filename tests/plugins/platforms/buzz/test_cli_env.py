"""Contract for the buzz CLI spawn env (adapter._buzz_cli_env).

The CLI child carries the Nostr private key by design (env, never argv/logs);
the base env is an allowlist so no OTHER Tier-1 secret rides along, and a stale
BUZZ_* value from the operator's shell cannot reach the child. Regression for
the full ``os.environ.copy()`` spawn.
"""
from __future__ import annotations

from plugins.platforms.buzz.adapter import _buzz_cli_env


def test_buzz_cli_env_carries_run_wiring_and_no_tier1_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-tier1")
    monkeypatch.setenv("BUZZ_AUTH_TAG", "stale-operator-tag")
    monkeypatch.setenv("BUZZ_PRIVATE_KEY", "stale-operator-key")

    env = _buzz_cli_env("wss://relay.example", "nsec-run-key")

    assert env["BUZZ_RELAY_URL"] == "wss://relay.example"
    assert env["BUZZ_PRIVATE_KEY"] == "nsec-run-key"
    # Only an explicit auth_tag argument sets the tag — never the shell's leftover.
    assert "BUZZ_AUTH_TAG" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "/usr/bin:/bin"


def test_buzz_cli_env_sets_auth_tag_only_when_supplied(monkeypatch) -> None:
    monkeypatch.setenv("BUZZ_AUTH_TAG", "stale-operator-tag")

    env = _buzz_cli_env("wss://relay.example", "nsec-run-key", auth_tag='["a","b"]')

    assert env["BUZZ_AUTH_TAG"] == '["a","b"]'
