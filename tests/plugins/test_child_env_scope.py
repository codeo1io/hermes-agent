"""Child-env scope contracts for the platform/memory plugins' subprocess spawns.

Regression for the P05 class (root AGENTS.md § Code Shape Rules): children must
be spawned from ``hermes_subprocess_env()`` so the launch profile's secrets and
credential env never ride into a long-lived child. The buzz/photon/openviking
sites were the three product spawns that still copied ``os.environ`` verbatim.

The A→B→A walk below is the two-home shape: while profile B is active, the
child env must not carry profile A's home (cross-profile leak) — regardless of
whether the child sees the routed home or no home marker at all.
"""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

pytest.importorskip("tools.environments.local", reason="spawn helpers live with the terminal backend")

# Provider/Tier-2 credential sentinels the scrubber must always remove.
_SECRET_SENTINELS = {
    "OPENAI_API_KEY": "sk-sentinel-openai",
    "ANTHROPIC_API_KEY": "sk-ant-sentinel",
    "GOOGLE_API_KEY": "sentinel-google",
}


def _sentinel_env(home: str) -> dict[str, str]:
    env = dict(_SECRET_SENTINELS)
    env["HERMES_HOME"] = home
    env["PARENT_ONLY_MARKER"] = "set-by-parent"
    return env


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = 0

    async def communicate(self, _stdin=None):  # noqa: ANN001 - asyncio proc protocol
        return b"", b""

    def kill(self) -> None:  # pragma: no cover - timeout path not exercised here
        pass

    async def wait(self):  # pragma: no cover
        return 0


@pytest.mark.asyncio
async def test_buzz_cli_child_env_is_scrubbed_and_scoped(monkeypatch, tmp_path):
    """_exec_buzz builds the child env via hermes_subprocess_env(): launch secrets
    stripped, buzz credentials present, and the ACTIVE home — never the previous one."""
    from plugins.platforms.buzz import adapter as buzz

    captured: dict[str, dict] = {}

    async def fake_exec(*args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        return _FakeProc()

    monkeypatch.setattr(buzz.asyncio, "create_subprocess_exec", fake_exec)

    home_a, home_b = tmp_path / "homeA", tmp_path / "homeB"
    seen_homes = []
    for home in (home_a, home_b, home_a):  # A → B → A
        monkeypatch.setenv("HERMES_HOME", str(home))
        for key, value in _sentinel_env(str(home)).items():
            monkeypatch.setenv(key, value)
        rc, _out, _err = await buzz._exec_buzz(
            "/usr/bin/true", ["send"], relay_url="wss://relay", private_key="sek",
        )
        assert rc == 0
        child_env = captured["env"]
        for secret in _SECRET_SENTINELS:
            assert secret not in child_env, f"{secret} leaked into buzz CLI child env"
        assert child_env.get("BUZZ_RELAY_URL") == "wss://relay"
        assert child_env.get("BUZZ_PRIVATE_KEY") == "sek"
        assert "BUZZ_AUTH_TAG" not in child_env  # not passed -> not inherited from parent
        seen_homes.append(child_env.get("HERMES_HOME"))

    # While B was active, the child must not carry A's home; symmetrically for A after B.
    assert seen_homes[1] != str(home_a)
    assert seen_homes[2] != str(home_b)


@pytest.mark.asyncio
async def test_photon_sidecar_env_is_scrubbed(monkeypatch, tmp_path):
    """_start_sidecar hands the node child a scrubbed env plus exactly its PHOTON_* scope."""
    photon = pytest.importorskip("plugins.platforms.photon.adapter", reason="photon platform plugin")
    from plugins.platforms import photon as photon_pkg  # noqa: F401  (import surface sanity)

    captured: dict[str, dict] = {}
    fake_proc = SimpleNamespace(pid=4242, poll=lambda: None, returncode=None)

    def fake_popen(*args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        return fake_proc

    monkeypatch.setattr(photon.subprocess, "Popen", fake_popen)

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(photon.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(photon, "_write_runtime_record", lambda *a, **k: None)
    monkeypatch.setattr(photon, "_delete_runtime_record", lambda *a, **k: None)

    adapter = object.__new__(photon.PhotonAdapter)
    adapter._project_id = "proj-1"
    adapter._project_secret = "proj-secret"
    adapter._sidecar_port = 47471
    adapter._sidecar_bind = "127.0.0.1"
    adapter._sidecar_token = "tok"
    adapter._node_bin = sys.executable
    adapter._sidecar_proc = None
    adapter._sidecar_supervisor_task = None

    async def _noop(*a, **k): ...
    monkeypatch.setattr(adapter, "_ensure_sidecar_deps", _noop, raising=False)
    monkeypatch.setattr(adapter, "_reap_stale_sidecar", _noop, raising=False)
    monkeypatch.setattr(adapter, "_apply_spectrum_patch", _noop, raising=False)

    async def _quiet_supervisor(*args, **kwargs):  # real signature: async (self, proc)
        await asyncio.sleep(0)

    monkeypatch.setattr(photon.PhotonAdapter, "_supervise_sidecar", _quiet_supervisor)

    home = tmp_path / "homeP"
    monkeypatch.setenv("HERMES_HOME", str(home))
    for key, value in _sentinel_env(str(home)).items():
        monkeypatch.setenv(key, value)

    await adapter._start_sidecar()

    child_env = captured["env"]
    for secret in _SECRET_SENTINELS:
        assert secret not in child_env, f"{secret} leaked into photon sidecar env"
    assert child_env.get("PHOTON_PROJECT_ID") == "proj-1"
    assert child_env.get("PHOTON_PROJECT_SECRET") == "proj-secret"
    assert child_env.get("PHOTON_SIDECAR_PORT") == "47471"
    assert child_env.get("PHOTON_SIDECAR_WATCH_STDIN") == "1"


def test_openviking_server_child_env_is_scrubbed_and_pythonpath_stripped(monkeypatch, tmp_path):
    """The openviking-server child gets a scrubbed env and NEVER the parent's PYTHONPATH
    (venv shadowing / Windows .pyd lock, #78153) — even when PYTHONPATH is set by the host."""
    ov = pytest.importorskip("plugins.memory.openviking", reason="openviking memory plugin")
    import plugins.memory.openviking as ov_mod

    captured: dict[str, dict] = {}

    def fake_popen(*args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        return SimpleNamespace(pid=9999)

    monkeypatch.setattr(ov_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ov_mod.shutil, "which", lambda name: "/usr/bin/fake-openviking-server")

    home = tmp_path / "homeOV"
    monkeypatch.setenv("HERMES_HOME", str(home))
    for key, value in _sentinel_env(str(home)).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PYTHONPATH", "/launch/venenv/site-packages")  # Desktop backend residue

    # Locate the local-server spawn entrypoint (_start_local_openviking_server(endpoint)).
    spawner = getattr(ov_mod, "_start_local_openviking_server", None)
    if spawner is None:  # pragma: no cover - name drift guard
        pytest.skip("openviking local-server spawner renamed; update this test's discovery")
    try:
        outcome = spawner("http://127.0.0.1:47891")
    except TypeError:
        pytest.skip("spawner signature changed; update this test")
    # Port-occupied and no-binary paths return early; force the spawn branch to have run.
    assert captured, f"spawn branch not reached (outcome={outcome!r})"
    child_env = captured["env"]
    for secret in _SECRET_SENTINELS:
        assert secret not in child_env, f"{secret} leaked into openviking-server env"
    assert "PYTHONPATH" not in child_env
