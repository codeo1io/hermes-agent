"""Plugin children never inherit the gateway's credential-bearing environment.

A plugin that spawns a third-party CLI, a sidecar or a local server must build
the child env through the ``tools.environments.local`` scrubbers — never
``os.environ.copy()``: the process env holds the launch profile's bot tokens,
relay tokens and provider keys, and a child (a CLI we do not own, a daemon that
outlives us) is exactly where those must not leak. Each test drives the REAL
spawn path with a captured child env and asserts the boundary contract:

- Hermes' own secrets (bot/relay tokens) stay out — always.
- The child's own tokens, added by the caller after the scrub, get through.
- The provider-key pass follows the site's ``inherit_credentials`` decision.
"""

import asyncio
import os
from typing import Any, Dict, List

import pytest

import plugins.memory.openviking as ov
from plugins.platforms.buzz import adapter as buzz_adapter
from plugins.platforms.photon import adapter as photon_adapter
from plugins.platforms.photon.adapter import PhotonAdapter

# Secrets of a shape the scrubbers classify on sight: a gateway bot token
# (Tier 1 — never passes to any child) and a provider key (Tier 2 — passes only
# to children spawned with inherit_credentials=True).
GATEWAY_TOKEN = {"TELEGRAM_BOT_TOKEN": "tgram-secret-value"}
PROVIDER_KEY = {"OPENAI_API_KEY": "sk-provider-secret-value"}


def _seed_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {**GATEWAY_TOKEN, **PROVIDER_KEY}.items():
        monkeypatch.setenv(key, value)


# ── buzz CLI: its own key only, never Hermes' credentials ─────────────────


@pytest.mark.asyncio
async def test_buzz_cli_child_env_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_secrets(monkeypatch)
    captured: Dict[str, Any] = {}

    class _Proc:
        returncode = 0

        async def communicate(self, *a: Any, **k: Any) -> Any:
            return (b"", b"")

    async def _fake_exec(*args: Any, **kwargs: Any) -> _Proc:
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    rc, _out, _err = await buzz_adapter._exec_buzz(
        "/usr/bin/buzz", ["version"], relay_url="wss://relay.example", private_key="ab" * 32
    )

    assert rc == 0
    env = captured["env"]
    for key in GATEWAY_TOKEN:
        assert key not in env, "the buzz CLI must not see Hermes' gateway tokens"
    for key in PROVIDER_KEY:
        assert key not in env, "a third-party CLI gets no provider credentials"
    assert env["BUZZ_RELAY_URL"] == "wss://relay.example"
    assert env["BUZZ_PRIVATE_KEY"] == "ab" * 32, "the child's own key travels with it"
    assert env["HOME"] == env["HERMES_REAL_HOME"], "its config/credentials resolve under the user's HOME"


# ── photon sidecar: no Hermes credentials at all ──────────────────────────


def _make_photon_adapter(monkeypatch: pytest.MonkeyPatch) -> PhotonAdapter:
    from gateway.config import PlatformConfig

    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    return PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))


@pytest.mark.asyncio
async def test_photon_sidecar_child_env_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_secrets(monkeypatch)
    adapter = _make_photon_adapter(monkeypatch)

    async def _no_reap() -> None:
        pass

    monkeypatch.setattr(adapter, "_reap_stale_sidecar", _no_reap)
    monkeypatch.setattr(adapter, "_ensure_sidecar_deps", _no_reap)
    spawned: Dict[str, Any] = {}

    class _CmdResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd: List[str], **kwargs: Any) -> _CmdResult:
        return _CmdResult()

    monkeypatch.setattr(photon_adapter.subprocess, "run", _fake_run)

    class _FakeProc:
        pid = 999
        stdout = None
        stdin = None

        @staticmethod
        def poll() -> None:
            return None

    def _fake_popen(cmd: List[str], **kwargs: Any) -> _FakeProc:
        spawned["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(photon_adapter.subprocess, "Popen", _fake_popen)

    class _HealthyClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "_HealthyClient":
            return self

        async def __aexit__(self, *a: Any, **k: Any) -> bool:
            return False

        async def post(self, *a: Any, **k: Any) -> Any:
            class _Resp:
                status_code = 200

            return _Resp()

    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _HealthyClient)

    await adapter._start_sidecar()

    env = spawned["kwargs"]["env"]
    for key in GATEWAY_TOKEN:
        assert key not in env, "the sidecar must not see Hermes' gateway tokens"
    for key in PROVIDER_KEY:
        assert key not in env, "the sidecar runs Photon's own protocol — no provider pass for it"
    assert env["PHOTON_PROJECT_ID"] == "test-project-id", "its own project keys travel with it"
    assert env["PHOTON_PROJECT_SECRET"] == "test-project-secret"
    assert env["PHOTON_SIDECAR_WATCH_STDIN"] == "1"


# ── openviking server: the profile's provider pass, never the launch env ──


def test_openviking_server_child_env_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_secrets(monkeypatch)
    monkeypatch.setattr(ov, "_local_openviking_port_is_open", lambda host, port: False)
    monkeypatch.setattr(ov.shutil, "which", lambda name: "/usr/local/bin/openviking-server")
    captured: Dict[str, Any] = {}

    class _FakeProc:
        pid = 4242

    def _fake_popen(cmd: List[str], **kwargs: Any) -> _FakeProc:
        captured.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(ov.subprocess, "Popen", _fake_popen)

    result, _msg = ov._start_local_openviking_server("http://127.0.0.1:1933")

    assert result == ov._LOCAL_SERVER_STARTED
    env = captured["env"]
    for key in GATEWAY_TOKEN:
        assert key not in env, "the server must not see Hermes' gateway/bot tokens"
    for key, value in PROVIDER_KEY.items():
        assert env.get(key) == value, (
            "the server's models may read provider keys — inherit_credentials=True passes the bound "
            "profile's, never the launch profile's raw env"
        )
    assert "PYTHONPATH" not in env, "the venv-shadowing strip (#78153) survives the composition"
    assert env["HOME"] == env["HERMES_REAL_HOME"], "ov.conf stays under the user's HOME"
    assert env is not os.environ
