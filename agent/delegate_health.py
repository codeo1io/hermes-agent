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
- Durable across restarts: every mutation is written atomically to
  ``<hermes home>/cache/delegate-provider-health.json`` and reloaded lazily
  on first use. The 10-02 continuity repair RESTARTED the gateway mid-storm;
  a memory-only ledger forgets every open circuit at that boundary and
  post-restart dispatches re-enter the same dead provider at full cost. A
  restart also forgets in-flight half-open probes (the probe died with the
  old process; keeping ``probing`` set would wedge fail-closed forever).
  Fail-open on every IO/parse error: an unreadable or corrupt file means a
  fresh ledger, and persistence never propagates exceptions.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent.delegate_errors import PROVIDER_FAILURE_CLASSES
from hermes_constants import get_hermes_home, hermes_home_key

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
_STATE_FILENAME = "delegate-provider-health.json"
_STATE_VERSION = 1

logger = logging.getLogger(__name__)

# (backend, model) — provider health is per upstream model.
LedgerKey = tuple[str, str]


def _default_state_path() -> Path:
    """``cache/delegate-provider-health.json`` under the effective home.

    Resolved lazily at each save/load so a turn running under a bound
    profile scope addresses that profile's file (never hardcoded
    ``~/.hermes``). It lives beside, not inside, ``cache/delegate-sessions/``
    so session-metadata pruning can never delete breaker state.
    """
    try:
        return Path(get_hermes_home()) / "cache" / _STATE_FILENAME
    except Exception:  # pragma: no cover - resilience, never fail dispatch
        return (
            Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
            / "cache"
            / _STATE_FILENAME
        )


def _decode_state_entry(raw: object, now: float, drift: float) -> dict | None:
    """Rebuild one entry dict from its persisted form, or None to skip it.

    Stamps are stored as *ages at save time* and rebased onto the loading
    ledger's clock minus the real save->load drift (the injectable clock's
    origin is process-relative), so a circuit 100s into a 900s cooldown on
    save is ~100s (+ real elapsed) into it after a restart. ``probing`` is
    always decoded False: the restarted process's first caller past the
    cooldown is its probe — an inherited in-flight probe has no one left to
    resolve it and would refuse dispatch forever.
    """
    if not isinstance(raw, dict):
        return None
    consecutive = raw.get("consecutive")
    cooldown = raw.get("cooldown")
    if not isinstance(consecutive, int) or not isinstance(cooldown, (int, float)):
        return None
    last_class = raw.get("last_error_class")
    opened_age = raw.get("opened_age")
    failures = raw.get("failure_ages")
    return {
        "failures": [
            now - max(0.0, float(age)) - drift
            for age in (failures if isinstance(failures, list) else [])
            if isinstance(age, (int, float))
        ],
        "consecutive": consecutive,
        "last_error_class": last_class if isinstance(last_class, str) else "",
        "opened_at": (
            now - max(0.0, float(opened_age)) - drift
            if isinstance(opened_age, (int, float))
            else None
        ),
        "cooldown": float(cooldown),
        "probing": False,
    }


@dataclass(frozen=True)
class CircuitOpen:
    """Why a dispatch is being refused; ``retry_after_s`` advises the wait."""

    retry_after_s: float
    consecutive: int
    last_error_class: str


class DelegateHealthLedger:
    """Per-key breaker state. In-memory is authoritative; every mutation is
    persisted (atomic tmp+rename, last-writer-wins) to the state file under
    the effective Hermes home so a gateway restart keeps open circuits — the
    incident family's restart is itself the state loss. State loads lazily
    on first use (import must not touch the filesystem, and first use runs
    under the owning profile's scope). Thread-safe; clock injectable for
    tests; persistence is fail-open on every IO/parse error."""

    def __init__(
        self,
        now: Callable[[], float] = time.monotonic,
        state_path: "Path | Callable[[], Path] | None" = None,
    ) -> None:
        self._now = now
        self._state_path = state_path  # None => default per-home path, lazily
        self._lock = threading.Lock()
        self._entries: dict[LedgerKey, dict] = {}
        self._loaded = False

    def _resolve_state_path(self) -> Path:
        path = self._state_path
        if path is None:
            return _default_state_path()
        return path() if callable(path) else path

    def _ensure_loaded_locked(self) -> None:
        """One tolerant load per ledger lifetime (caller holds the lock)."""
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(
                self._resolve_state_path().read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return
        try:
            if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
                return
            if not isinstance(data.get("entries"), dict):
                return
            saved_at = data.get("saved_at")
            if not isinstance(saved_at, (int, float)):
                return
            now = self._now()
            # Real seconds between save and load; stamps are rebased through
            # it so cooldown/window math survives the restart.
            drift = max(0.0, time.time() - float(saved_at))
            for raw_key, raw in data["entries"].items():
                parts = str(raw_key).split("/", 1)
                if len(parts) != 2:
                    continue
                entry = _decode_state_entry(raw, now, drift)
                if entry is not None:
                    self._entries[(parts[0], parts[1])] = entry
        except Exception:
            return  # fail-open: a malformed file never breaks dispatch

    def _persist_locked(self) -> None:
        """Atomic write of the current entries; never raises (json of these
        plain types cannot fail, so only OSError is swallowed)."""
        path = self._resolve_state_path()
        try:
            now = self._now()
            entries = {}
            for (backend, model), entry in self._entries.items():
                entries[f"{backend}/{model}"] = {
                    "consecutive": entry["consecutive"],
                    "last_error_class": entry["last_error_class"],
                    "cooldown": entry["cooldown"],
                    "probing": entry["probing"],
                    "opened_age": (
                        None
                        if entry["opened_at"] is None
                        else max(0.0, now - entry["opened_at"])
                    ),
                    "failure_ages": [
                        max(0.0, now - stamp) for stamp in entry["failures"]
                    ],
                }
            text = json.dumps(
                {
                    "version": _STATE_VERSION,
                    "saved_at": time.time(),
                    "entries": entries,
                },
                ensure_ascii=False,
                indent=2,
            )
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = path.with_name(
                f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp.write_text(text, encoding="utf-8")
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            tmp.replace(path)
        except OSError:
            logger.debug("delegate health state persist failed", exc_info=True)

    def record_failure(self, key: LedgerKey, error_class: str) -> None:
        """Count a failure. Non-provider classes are ignored entirely: they
        carry no information about the upstream provider."""
        if error_class not in PROVIDER_FAILURE_CLASSES:
            return
        now = self._now()
        with self._lock:
            self._ensure_loaded_locked()
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
            elif len(entry["failures"]) >= FAILURE_THRESHOLD:
                # Opening or re-arming: both restart the cooldown from now.
                entry["opened_at"] = now
            self._persist_locked()

    def record_success(self, key: LedgerKey) -> None:
        """Any success closes the circuit fully (resets the streak)."""
        with self._lock:
            self._ensure_loaded_locked()
            if self._entries.pop(key, None) is not None:
                self._persist_locked()

    def check(self, key: LedgerKey) -> CircuitOpen | None:
        """`None` = dispatch may proceed; `CircuitOpen` = refuse/defer.

        While the cooldown has elapsed, exactly one half-open probe is
        granted; a second check before that probe resolves is still refused.
        """
        with self._lock:
            self._ensure_loaded_locked()
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
                self._persist_locked()
                return None
            # Probe already in flight: stay closed to it until it resolves.
            return CircuitOpen(
                retry_after_s=entry["cooldown"],
                consecutive=entry["consecutive"],
                last_error_class=entry["last_error_class"],
            )


# One ledger per Hermes home, NOT one per process. The conductor spool and
# multiplex gateways drive every profile in one process; a process-wide
# singleton would let profile A's provider outage gate profile B's dispatches
# — worse, the first mutation under B's scope would lazily-persist A's open
# entries into B's state file. Keying by ``hermes_home_key()`` rides the
# profile-runtime scope bindings multiplex already provides, so the right
# ledger is selected with no new state plumbing. Constructing a ledger does
# no I/O (state files load lazily per mutation), so filling the registry is
# as cheap as the old singleton.
_LEDGERS: dict[str, DelegateHealthLedger] = {}
_LEDGER_REGISTRY_LOCK = threading.Lock()


def _ledger_for_home() -> DelegateHealthLedger:
    """The ledger instance bound to the current Hermes home."""
    try:
        key = hermes_home_key()
    except Exception:
        key = ""  # fail-open: one shared ledger beats refusing health checks
    with _LEDGER_REGISTRY_LOCK:
        ledger = _LEDGERS.get(key)
        if ledger is None:
            ledger = DelegateHealthLedger()
            _LEDGERS[key] = ledger
        return ledger


def get_delegate_health_ledger() -> DelegateHealthLedger:
    """The provider-health ledger for the current profile home.

    Sessions within one profile share breaker state by design — one
    provider outage is that profile's outage — while profiles never share
    it: the conductor spool and multiplex gateways serve every profile from
    one process. Each ledger resolves its state file lazily per mutation,
    so cooldowns also persist per home.
    """
    return _ledger_for_home()


def reset_delegate_health_ledger() -> DelegateHealthLedger:
    """Drop every per-home ledger and return a fresh one for this home.

    Test isolation seam and the operator's force-recover switch. The fresh
    ledger lazily reloads this home's own state file, so open circuits
    survive a reset through the durable file while in-memory drift does not.
    """
    with _LEDGER_REGISTRY_LOCK:
        _LEDGERS.clear()
    return _ledger_for_home()
