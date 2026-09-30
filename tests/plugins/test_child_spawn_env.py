"""Invariants for the plugin child-spawn env allowlist (plugins/child_spawn_env).

The helper backs the long-lived children spawned by photon (node sidecar), buzz
(CLI) and openviking (vendored server). Those processes outlive the turn that
started them, so anything in their environment is effectively published for
their lifetime (/proc/<pid>/environ). Contract under test: Tier-1-shaped names
never cross, the names a non-Hermes child genuinely needs always do, and the
Windows arm is data rather than a host assumption.
"""
from __future__ import annotations

from plugins.child_spawn_env import minimal_child_env


def test_tier1_secrets_never_reach_the_child_env() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/op",
        "LANG": "C.UTF-8",
        "ANTHROPIC_API_KEY": "sk-ant-tier1",
        "OPENAI_API_KEY": "sk-oai-tier1",
        "DISCORD_BOT_TOKEN": "discord-tier1",
        "GITHUB_TOKEN": "gh-tier1",
        "DATABASE_URL": "postgres://pw@db/example",
        "HERMES_DESKTOP": "1",
        "BUZZ_PRIVATE_KEY": "operator-stale-key",
    }
    env = minimal_child_env(source, is_windows=False)
    # Only the documented base crossed — every Tier-1 shape stayed behind.
    assert set(env) == {"PATH", "HOME", "LANG"}


def test_essentials_cross_and_tls_trust_survives() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/h",
        "TEMP": "/tmp",
        "TZ": "UTC",
        "SSL_CERT_FILE": "/certs.pem",
        "NODE_EXTRA_CA_CERTS": "/ca.pem",
    }
    env = minimal_child_env(source, is_windows=False)
    # Behind a corporate proxy a child without the trust anchors cannot verify
    # upstream certs at all — they must survive the allowlist.
    for name in ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"):
        assert name in env
    assert env["TZ"] == "UTC" and env["TEMP"] == "/tmp"


def test_windows_arm_is_data_not_host_assumption() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/h",
        "SYSTEMROOT": "C:\\Windows",
        "APPDATA": "C:\\Users\\op\\AppData",
    }
    posix_env = minimal_child_env(source, is_windows=False)
    windows_env = minimal_child_env(source, is_windows=True)
    # CRT essentials cross only when the child host is Windows.
    assert "SYSTEMROOT" not in posix_env and "SYSTEMROOT" in windows_env
    assert "APPDATA" not in posix_env and "APPDATA" in windows_env


def test_empty_values_do_not_cross() -> None:
    # An empty-string PATH would shadow the child's own resolution; drop it.
    env = minimal_child_env({"PATH": "", "HOME": "/h"}, is_windows=False)
    assert env == {"HOME": "/h"}
