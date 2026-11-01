"""Owner-loop-safe accessors for the live gateway runner.

``gateway.run``'s module body imports the entire gateway graph (slash commands →
account usage → ``httpx`` → ``rich``) through ``importlib``. Anything that runs
on the owner loop — the API drain probe inside the first request of every HTTP
door, the chat door's ``/model`` override lookup — must never trigger that
import: ~0.4s cold on an idle host, seconds on a loaded one, stalling every
session, timer and socket behind one request.

A ``gateway.run`` that was never imported cannot own a runner — the
module-level ``_gateway_runner_ref`` is set only by ``GatewayRunner.__init__``
— so a missing module is exactly "no runner", consulted through
``sys.modules.get`` (the same hygiene ``tools/cronjob_tools.py`` uses for the
same reason).
"""

from __future__ import annotations

import sys
from typing import Any, Optional


def live_gateway_runner() -> Optional[Any]:
    """The live ``GatewayRunner`` when ``gateway.run`` is already imported, else ``None``."""
    gateway_run = sys.modules.get('gateway.run')
    if gateway_run is None:
        return None
    return gateway_run._gateway_runner_ref()


def gateway_is_draining() -> bool:
    """Whether the owning gateway currently refuses new agent turns."""
    from gateway.platforms.api_server_fire_startup import runner_is_draining

    runner = live_gateway_runner()
    return bool(runner) and runner_is_draining(runner)


def session_model_override_for(session_key: Optional[str], logger=None) -> Optional[dict]:
    """The gateway's per-session ``/model`` override for *session_key*, if any — a
    user-issued ``/model`` always wins over static route config."""
    if not session_key:
        return None
    runner = live_gateway_runner()
    if runner is None:
        return None
    try:
        rehydrate = getattr(runner, "_rehydrate_session_model_override", None)
        if callable(rehydrate):
            rehydrate(session_key)
    except Exception:
        if logger is not None:
            logger.debug(
                "api_server failed to rehydrate session /model override for %s", session_key, exc_info=True)
    override = runner._session_model_overrides.get(session_key)
    return dict(override) if isinstance(override, dict) else None
