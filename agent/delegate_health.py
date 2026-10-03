"""Delegate provider-health ledger: a bounded circuit breaker for native delegates.

WHY: during the 09-30 cliproxy glm-4.6 cooling-down storm, the same dead
provider stalled every parallel delegate worker for 1800-3600s per attempt and
each retry re-entered the identical outage. Retrying a *confirmed-dead*
provider multiplies wall-clock damage; the provider needs a bounded period of
rest between delegate attempts.

Semantics (kept deliberately small — this is a breaker, not a scheduler):

- Keyed by ``(backend, model)``: provider health is per upstream model, so a
  dead ``glm-4.6`` never blocks delegations to other models.
- Opens after 3 provider-class failures within a 600s window. Only classes in
  ``agent.delegate_errors.PROVIDER_FAILURE_CLASSES`` count: an agent wedging
  (``agent_stall``), a full local host (``resource_exhausted``), or a broken
  RPC transport (``transport``) say nothing about the provider, and must never
  stop delegate traffic.
- Fail-open everywhere: a ledger error, an unknown error class, or clock
  weirdness degrades to "let the dispatch through". The breaker bounds damage
  from a storm; it must never become a new way to fail closed (the original
  finding).
- Cooldown ladder 900s -> 1800s (doubling, capped): after the cooldown one
  half-open probe is granted; a probe failure re-opens with double the
  cooldown, a success closes fully.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from agent.delegate_errors import PROVIDER_FAILURE_CLASSES

__all__ = [
    "CircuitOpen",
    "DelegateHealthLedger",
    "FAILURE_THRESHOLD",
    "INITIAL_COOLDOWN_S",
    "MAX_COOLDOWN_S",
    "WINDOW_S",
    "get_delegate_health_ledger",
    "reset_delegate_health_ledger",
]

FAILURE_THRESHOLD = 3
WINDOW_S = 600.0
INITIAL_COOLDOWN_S = 900.0
MAX_COOLDOWN_S = 1800.0

# (backend, model) — provider health is per upstream model.
LedgerKey = tuple[str, str]


@dataclass(frozen=True)
class CircuitOpen:
    """Why a dispatch is being refused; ``retry_after_s`` advises the wait."""

    retry_after_s: float
    consecutive: int
    last_error_class: str


class DelegateHealthLedger:
    """In-memory per-key breaker state; process-local by design (each gateway
    process sees its own delegates). Thread-safe; clock injectable for tests."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._entries: dict[LedgerKey, dict] = {}

    def record_failure(self, key: LedgerKey, error_class: str) -> None:
        """Count a failure. Non-provider classes are ignored entirely: they
        carry no information about the upstream provider."""
        if error_class not in PROVIDER_FAILURE_CLASSES:
            return
        now = self._now()
        with self._lock:
            entry = self._entries.setdefault(
                key,
                {
                    "failures": [],
                    "consecutive": 0,
                    "last_error_class": "",
                    "opened_at": None,
                    "cooldown": INITIAL_COOLDOWN_S,
                    "probing": False,
                },
            )
            entry["last_error_class"] = error_class
            entry["consecutive"] += 1
            entry["failures"].append(now)
            entry["failures"] = [
                stamp for stamp in entry["failures"] if now - stamp <= WINDOW_S
            ]
            if entry["probing"]:
                # A half-open probe failure decides alone: re-open immediately
                # with double the cooldown, capped. Requiring a fresh window of
                # failures would re-open the provider to the storm after every
                # single probe (the window prunes the history that opened it).
                entry["probing"] = False
                entry["cooldown"] = min(entry["cooldown"] * 2, MAX_COOLDOWN_S)
                entry["opened_at"] = now
                return
            if len(entry["failures"]) < FAILURE_THRESHOLD:
                return
            # Opening or re-arming: both restart the cooldown from now.
            entry["opened_at"] = now

    def record_success(self, key: LedgerKey) -> None:
        """Any success closes the circuit fully (resets the streak)."""
        with self._lock:
            self._entries.pop(key, None)

    def check(self, key: LedgerKey) -> CircuitOpen | None:
        """`None` = dispatch may proceed; `CircuitOpen` = refuse/defer.

        While the cooldown has elapsed, exactly one half-open probe is
        granted; a second check before that probe resolves is still refused.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry["opened_at"] is None:
                return None
            elapsed = self._now() - entry["opened_at"]
            if elapsed < entry["cooldown"]:
                return CircuitOpen(
                    retry_after_s=entry["cooldown"] - elapsed,
                    consecutive=entry["consecutive"],
                    last_error_class=entry["last_error_class"],
                )
            if not entry["probing"]:
                entry["probing"] = True
                return None
            # Probe already in flight: stay closed to it until it resolves.
            return CircuitOpen(
                retry_after_s=entry["cooldown"],
                consecutive=entry["consecutive"],
                last_error_class=entry["last_error_class"],
            )


_LEDGER = DelegateHealthLedger()


def get_delegate_health_ledger() -> DelegateHealthLedger:
    """The process-wide ledger (delegate turns in one gateway share state)."""
    return _LEDGER


def reset_delegate_health_ledger() -> DelegateHealthLedger:
    """Replace the process-wide ledger with a fresh one. Test seam — also
    used to drop all breaker state at once if an operator force-recovers."""
    global _LEDGER
    _LEDGER = DelegateHealthLedger()
    return _LEDGER
