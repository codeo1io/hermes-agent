"""Provider-circuit helpers for the delegate-session tool.

Extracted from ``tools/delegate_session_tool.py`` (code-health FILE_LINES cap:
moved code keeps its cap; see root AGENTS.md). Semantics unchanged.
"""

from __future__ import annotations

import logging
from typing import Optional

from agent.delegate_health import get_delegate_health_ledger

logger = logging.getLogger(__name__)


def _circuit_open_error(backend: str, model: str, ledger=None) -> Optional[str]:
    """Dispatch-time fail-fast guard (A2 breaker): ``None`` lets the turn
    through; a message refuses it while the (backend, model) provider circuit
    is open. Retrying a confirmed-dead provider multiplies wall-clock damage
    (the A4 storm re-entered the same outage for 30-76 minutes per attempt).
    Fail-open: any internal error lets the dispatch through — the breaker
    must never become a new way to fail closed.

    ``ledger`` pins the dispatching profile's registry: the turn thread does
    not inherit the home-override contextvar, so worker calls pass the ledger
    captured at dispatch time; parent-side gates may omit it and resolve at
    call time.
    """
    try:
        circuit = (ledger or get_delegate_health_ledger()).check((backend, model))
    except Exception:
        logger.debug("delegate provider gate failed open", exc_info=True)
        return None
    if circuit is None:
        return None
    return (
        "delegate provider unavailable (error_class=provider_unavailable): "
        f"{backend}/{model or 'default'} circuit open after "
        f"{circuit.consecutive} provider-class failures "
        f"(last: {circuit.last_error_class}); "
        f"retry after {circuit.retry_after_s:.0f}s"
    )


def _ledger_record_success(key: tuple[str, str], ledger=None) -> None:
    # ``ledger`` pins the dispatching profile's registry for turn-thread calls
    # (plain threads do not inherit the home-override contextvar).
    try:
        (ledger or get_delegate_health_ledger()).record_success(key)
    except Exception:
        logger.debug("delegate health record_success failed (fail-open)", exc_info=True)


def _ledger_record_failure(key: tuple[str, str], error_class: str, ledger=None) -> None:
    # ``ledger`` pins the dispatching profile's registry for turn-thread calls
    # (plain threads do not inherit the home-override contextvar).
    # Forward EVERY terminal class, provider or not (R-fold): the ledger
    # itself decides provider classes escalate the breaker while
    # non-provider classes merely resolve an in-flight half-open probe (a
    # probe turn that dies agent_stall/transport must not wedge the key
    # closed).
    try:
        (ledger or get_delegate_health_ledger()).record_failure(key, error_class)
    except Exception:
        logger.debug("delegate health record_failure failed (fail-open)", exc_info=True)


