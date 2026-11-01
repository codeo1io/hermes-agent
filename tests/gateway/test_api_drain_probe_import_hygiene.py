"""The API drain probe must never import the gateway graph on the owner loop.

``_gateway_is_draining`` runs inside the first request of every HTTP door
(``_admit_api_agent_request`` → ``_draining_response``), directly on the owner
loop. Lazy-importing ``gateway.run`` there pulls the entire gateway module graph
(slash commands → account usage → ``httpx`` → ``rich``) through ``importlib`` on
the loop: 0.4s cold on an idle host, 2s+ on a loaded CI runner, stalling every
session, timer and socket behind one request's drain check
(``test_api_admission_off_loop[chat]`` main-red).

A ``gateway.run`` that was never imported cannot own a draining runner — the
module-level ``_gateway_runner_ref`` is only ever set by
``GatewayRunner.__init__`` — so probing a missing module is exactly "not
draining", without importing it (the same ``sys.modules.get`` hygiene
``tools/cronjob_tools.py`` already uses for the same reason).
"""

import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def cold_gateway_run(monkeypatch):
    """A process where ``gateway.run`` was never imported; restores any live module after."""
    live = sys.modules.pop("gateway.run", None)
    yield
    if live is not None:
        sys.modules["gateway.run"] = live


def _probe(api):
    return api._draining_response()


def test_drain_probe_does_not_import_gateway_run_on_the_loop(
    api, owner, monkeypatch, cold_gateway_run
):
    """A cold process's first drain probe must not import ``gateway.run``."""
    captured = []
    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def spy_import(name, *args, **kwargs):
        if name == "gateway.run":
            captured.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", spy_import)
    assert _probe(api) is None  # not draining: no error response
    assert captured == [], "the drain probe imported gateway.run on the owner loop"


def test_drain_probe_reads_a_live_module_runner(api, owner, monkeypatch):
    """With ``gateway.run`` live (a real gateway), its runner ref still gates the probe."""
    fake = SimpleNamespace(_gateway_runner_ref=lambda: SimpleNamespace(_draining=True))
    monkeypatch.setitem(sys.modules, "gateway.run", fake)
    response = _probe(api)
    assert response is not None and response.status == 503


def test_drain_probe_reports_external_drain_from_live_module(api, owner, monkeypatch):
    """An externally-started drain seen through the live module remains fail-safe."""
    fake = SimpleNamespace(
        _gateway_runner_ref=lambda: SimpleNamespace(
            _draining=False, _external_drain_active=True
        )
    )
    monkeypatch.setitem(sys.modules, "gateway.run", fake)
    assert api._gateway_is_draining() is True
    response = _probe(api)
    assert response is not None and response.status == 503


def test_drain_probe_live_module_not_draining(api, owner, monkeypatch):
    """A live runner that is neither draining nor externally drained admits the request."""
    fake = SimpleNamespace(_gateway_runner_ref=lambda: SimpleNamespace(_draining=False))
    monkeypatch.setitem(sys.modules, "gateway.run", fake)
    assert _probe(api) is None


def test_drain_probe_live_module_dead_ref(api, owner, monkeypatch):
    """A live module whose runner was collected (weakref died) admits the request."""
    fake = SimpleNamespace(_gateway_runner_ref=lambda: None)
    monkeypatch.setitem(sys.modules, "gateway.run", fake)
    assert _probe(api) is None
