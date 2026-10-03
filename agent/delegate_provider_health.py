"""Typed provider-failure classification + per-profile delegate provider-health ledger.

During the 2026-10-02 provider storm on the pi delegate backend, 71% of all
recorded delegate turns failed (3,553 of 4,998) yet every dispatch kept paying
the full spawn + turn + stall-timeout cost, and the accumulated spawns and
threads compounded the outage into host resource exhaustion (219 thread-create
failures, 139 fork EAGAIN, 25 ENOSPC). The delegate boundary had no memory of
provider failure at all: exceptions were flattened to strings and every retry
started from scratch.

This module gives that boundary two things:

1. ``classify_delegate_failure`` — a small, stable classification of the
   failure shapes actually observed in the spool evidence, reusing the
   existing API taxonomy (``classify_api_error``) when an HTTP status is
   extractable and falling back to a table of stable pi-shaped text markers.
   Classes: ``rate_limit`` ``upstream_rate_limit`` ``overloaded``
   ``server_error`` ``timeout`` ``auth`` ``billing`` (existing enum values
   where one fits) plus delegate-only shapes ``provider_stall`` ``agent_stall``
   ``resource_exhausted`` ``transport`` and ``unknown``.
2. A per-profile (backend, model)-keyed provider-health ledger with a
   fail-fast circuit breaker that mirrors the in-house
   ``fallback_cooldown`` exponential ladder (60 s doubling to a 4 h cap),
   persisted at ``<hermes home>/cache/delegate-provider-health.json`` —
   deliberately OUTSIDE ``cache/delegate-sessions/`` so metadata pruning
   never deletes it. In-process state is authoritative; the file is shared
   memory across restarts and concurrent processes (last writer wins).

Failure semantics: fail-open. Unknown classes, unreadable files, and every
internal error leave dispatch ungated — the breaker only opens on explicit
provider-class evidence, and only for the affected (backend, model) pair.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from agent.error_classifier import FailoverReason, classify_api_error
from hermes_constants import get_hermes_home, hermes_home_key

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ clock seams
# Module-level indirection so tests (and only tests) can advance time without
# patching the global ``time`` module. Production code must call these.


def _now() -> float:
    return time.time()


def _mono() -> float:
    return time.monotonic()


# ------------------------------------------------------------------ classes

#: Failure classes that count as "the provider is unhealthy" for the breaker.
#: Everything else (``transport``, ``auth``, ``resource_exhausted``,
#: ``agent_stall``, ``billing``, ``unknown`` …) is typed evidence only: it is
#: recorded in the ledger and surfaced, but never opens the circuit.
PROVIDER_CLASSES = frozenset(
    {
        "rate_limit",
        "upstream_rate_limit",
        "overloaded",
        "server_error",
        "timeout",
        "provider_stall",
    }
)

#: Delegate-only class shapes the API taxonomy has no enum for.
DELEGATE_CLASSES = frozenset({"provider_stall", "agent_stall", "resource_exhausted", "transport"})

# Verbatim signatures from the 2026-10-02 spool evidence (5,028 envelopes:
# 949 aborts, 353 cooling-down 429s, 229 get_state timeouts, 219 thread-create,
# 139 fork EAGAIN, 164 rpc-process exits, 103 key-resolution, 25 ENOSPC).
# Case-insensitive substrings of the combined exception text; first row wins.
_MARKER_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Host resource pressure — the amplification casualty, never the cause.
    (
        "resource_exhausted",
        (
            "can't start new thread",
            "cannot start new thread",
            "resource temporarily unavailable",  # fork EAGAIN (Errno 11)
            "no space left on device",  # ENOSPC (Errno 28)
            "disk quota exceeded",
        ),
    ),
    # pi RPC process-level failures — retrying a fresh spawn may fix these,
    # so they are typed evidence but do not open the breaker.
    (
        "transport",
        (
            "pi did not answer command",
            "pi rpc process exited",
            "pi rpc client is closed",
            "did not expose stdin/stdout pipes",
            "could not start pi binary",
            "rpc client is closed",
        ),
    ),
    # pi-side fetch aborts surface as bare JS "This operation was aborted".
    ("timeout", ("this operation was aborted", "aborted due to timeout")),
    (
        "rate_limit",
        (
            "cooling down",
            "429",
            "rate limit",
            "rate_limit",
            "too many requests",
            "quota exceeded",
        ),
    ),
    ("overloaded", ("overloaded", "529", "service unavailable")),
    ("server_error", ("internal server error", "bad gateway", "server error")),
    (
        "auth",
        (
            "unauthorized",
            "forbidden",
            "invalid bearer token",
            "invalid api key",
            "api key not valid",
            "api key not found",
            "no api key",
            "authentication required",
            "authentication_error",
        ),
    ),
    ("billing", ("credit balance", "billing", "payment required")),
)

#: API taxonomy verdicts mapped onto this module's class vocabulary. Reasons
#: absent from this table (context overflow, content policy, …) are per-request
#: deterministic failures, not provider health — they stay ``unknown`` (fail-open).
_API_REASON_TO_CLASS: Dict[FailoverReason, str] = {
    FailoverReason.rate_limit: "rate_limit",
    FailoverReason.upstream_rate_limit: "upstream_rate_limit",
    FailoverReason.overloaded: "overloaded",
    FailoverReason.server_error: "server_error",
    FailoverReason.timeout: "timeout",
    FailoverReason.auth: "auth",
    FailoverReason.auth_permanent: "auth",
    FailoverReason.billing: "billing",
}

_STALL_MARKERS = ("session turn stalled after", "without observable progress")

# Breaker policy: open after 2 consecutive provider-class failures that are
# at most _PAIR_WINDOW_S apart; open duration 60 s doubling per reopen to a
# 4 h cap (the fallback_cooldown ladder shape); success at half-open closes
# and resets. Fail-open on everything unrecognized.
_FAILURES_TO_OPEN = 2
_PAIR_WINDOW_S = 1800.0
_OPEN_LADDER_BASE_S = 60.0
_OPEN_LADDER_CAP_S = 14_400.0
_MAX_LEDGER_ENTRIES = 32

_LEDGER_FILENAME = "delegate-provider-health.json"

# Instance registry keyed by hermes home so every profile (and every isolated
# test home) gets its own ledger; process-global dict + lock, same shape the
# state-DB layers use.
_LEDGERS: Dict[str, "_ProviderHealthLedger"] = {}
_LEDGER_REGISTRY_LOCK = threading.Lock()


def classify_delegate_failure(
    exc: Optional[BaseException] = None,
    *,
    text: str = "",
    had_unsolicited_activity: Optional[bool] = None,
    backend: str = "",
    model: str = "",
) -> str:
    """Classify a delegate-boundary failure into a stable class string.

    Resolution order:
    1. **Stall split** — structural evidence first. A typed stall exception
       (``had_unsolicited_activity`` attribute, or the explicit argument) splits
       exactly: zero unsolicited activity after prompt-ack means the provider
       produced nothing → ``provider_stall``; activity-then-silence means the
       delegate stopped producing → ``agent_stall``. A stall recognized only by
       its message (no structural evidence) maps conservatively to
       ``agent_stall`` — ambiguous evidence never opens the breaker.
    2. **HTTP taxonomy** — when ``classify_api_error`` can extract an HTTP
       status from the exception, its verdict wins (rate_limit/overloaded/…).
    3. **Marker table** — stable pi-shaped text signatures (``_MARKER_TABLE``),
       which also catch pi RPC process failures the HTTP taxonomy cannot see.
    4. ``unknown`` — fail-open.

    Never raises; an unclassifiable input is ``unknown``.
    """
    # 1. Structural stall split beats everything.
    activity = had_unsolicited_activity
    if activity is None and exc is not None:
        attr = getattr(exc, "had_unsolicited_activity", None)
        if isinstance(attr, bool):
            activity = attr
    if isinstance(activity, bool):
        return "agent_stall" if activity else "provider_stall"

    combined = "\n".join(part for part in (text, str(exc) if exc is not None else "") if part)
    lowered = combined.lower()

    if any(marker in lowered for marker in _STALL_MARKERS):
        return "agent_stall"

    # 2. HTTP-shaped errors: the existing taxonomy is authoritative whenever a
    #    status code is extractable (guarded: best effort throughout).
    if exc is not None:
        try:
            verdict = classify_api_error(exc, provider=backend, model=model)
        except Exception:  # noqa: BLE001 - classification must never raise
            verdict = None
        if (
            verdict is not None
            and getattr(verdict, "status_code", None) is not None
            and getattr(verdict, "reason", None) is not None
        ):
            mapped = _API_REASON_TO_CLASS.get(verdict.reason)
            if mapped:
                return mapped

    # 3. pi-shaped markers.
    for cls, markers in _MARKER_TABLE:
        if any(marker in lowered for marker in markers):
            return cls

    # 4. Text-stage taxonomy verdicts (no status) only if the markers missed.
    if exc is not None and verdict is not None:
        mapped = _API_REASON_TO_CLASS.get(getattr(verdict, "reason", None))
        if mapped:
            return mapped
    return "unknown"


def _open_ladder_seconds(opens: int) -> float:
    return min(_OPEN_LADDER_BASE_S * (2 ** max(0, opens - 1)), _OPEN_LADDER_CAP_S)


def _ledger_relative_path() -> Path:
    """``cache/delegate-provider-health.json`` under the effective Hermes home."""
    try:
        return Path(get_hermes_home()) / "cache" / _LEDGER_FILENAME
    except Exception:  # noqa: BLE001 - same resilience as _session_store_root
        return Path(
            os.environ.get("HERMES_HOME") or Path.home() / ".hermes"
        ) / "cache" / _LEDGER_FILENAME


class _ProviderHealthLedger:
    """(backend, model)-keyed breaker state; in-memory authoritative, file shared."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    @staticmethod
    def _key(backend: str, model: str) -> str:
        return f"{backend}/{model}"

    def _persist(self) -> None:
        try:
            payload = {
                "version": 1,
                "updated_at": _now(),
                "entries": {
                    key: {k: v for k, v in entry.items() if not k.endswith("_mono")}
                    for key, entry in self._entries.items()
                },
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = self._path.with_name(
                f".{self._path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp.write_text(text, encoding="utf-8")
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            tmp.replace(self._path)  # atomic on POSIX
        except OSError:
            logger.debug("Could not persist delegate provider-health ledger", exc_info=True)

    def _load(self) -> None:
        """Tolerant load: corrupt/missing/unreadable file ⇒ empty ledger."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return
        now, mono = _now(), _mono()
        for key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            loaded = dict(entry)
            # Rebuild in-memory monotonic fields from persisted wall clocks so
            # circuit math stays step-immune across restarts.
            loaded["open_until_mono"] = (
                mono + max(0.0, loaded["open_until"] - now)
                if isinstance(loaded.get("open_until"), (int, float))
                else None
            )
            loaded["last_failure_mono"] = (
                mono - max(0.0, now - loaded["last_failure_at"])
                if isinstance(loaded.get("last_failure_at"), (int, float))
                else None
            )
            self._entries[str(key)] = loaded

    def _trim(self) -> None:
        if len(self._entries) <= _MAX_LEDGER_ENTRIES:
            return
        # Drop the stalest-updated entries; keep open circuits last (dropping
        # one would silently ungate a provider we just declared unhealthy).
        order = sorted(
            self._entries.items(),
            key=lambda kv: (
                kv[1].get("state") == "open",
                float(kv[1].get("updated_at") or 0.0),
            ),
        )
        for key, _entry in order[: len(self._entries) - _MAX_LEDGER_ENTRIES]:
            self._entries.pop(key, None)

    # -- public surface ----------------------------------------------------

    def _fresh_entry(self, backend: str, model: str) -> Dict[str, Any]:
        return {
            "backend": backend,
            "model": model,
            "state": "closed",
            "consecutive_failures": 0,
            "consecutive_provider_failures": 0,
            "error_class": None,
            "last_failure_at": None,
            "last_failure_mono": None,
            "opens": 0,
            "open_until": None,
            "open_until_mono": None,
            "open_duration_s": None,
            "updated_at": _now(),
        }

    def record_outcome(self, backend: str, model: str, error_class: Optional[str]) -> None:
        """Record one delegate outcome: ``None`` = success, else a class string."""
        with self._lock:
            key = self._key(backend, model)
            entry = self._entries.setdefault(key, self._fresh_entry(backend, model))
            now, mono = _now(), _mono()
            entry["updated_at"] = now
            if error_class is None:
                # Success: a healthy turn (or a half-open probe that passed)
                # closes and resets the breaker entirely.
                entry["consecutive_failures"] = 0
                entry["consecutive_provider_failures"] = 0
                entry["state"] = "closed"
                entry["opens"] = 0
                entry["open_until"] = None
                entry["open_until_mono"] = None
            elif error_class in PROVIDER_CLASSES:
                entry["error_class"] = error_class
                entry["consecutive_failures"] += 1
                prev_mono = entry.get("last_failure_mono")
                entry["last_failure_at"] = now
                entry["last_failure_mono"] = mono
                # The opening pair must be recent: a provider failure hours
                # after the last one starts a NEW pair instead of opening.
                fresh_pair = (
                    prev_mono is not None and mono - prev_mono <= _PAIR_WINDOW_S
                )
                if entry.get("state") == "half_open":
                    # The probe failed: re-open, escalated one rung.
                    self._open_locked(entry, now, mono)
                elif entry.get("state") == "open":
                    # Already gated; an in-flight turn still failed. Re-arm the
                    # window so the next open starts from the current failure.
                    entry["consecutive_provider_failures"] = 1
                elif (
                    entry.get("consecutive_provider_failures", 0) >= _FAILURES_TO_OPEN - 1
                    and fresh_pair
                ):
                    self._open_locked(entry, now, mono)
                else:
                    # Stale predecessor restarts the pair; this failure is its
                    # first member either way.
                    entry["consecutive_provider_failures"] = 1
            else:
                # Typed evidence only: never opens the breaker.
                entry["error_class"] = error_class
                entry["consecutive_failures"] += 1
            self._trim()
            self._persist()

    def _open_locked(self, entry: Dict[str, Any], now: float, mono: float) -> None:
        entry["opens"] = int(entry.get("opens") or 0) + 1
        duration = _open_ladder_seconds(entry["opens"])
        entry["state"] = "open"
        entry["open_until"] = now + duration
        entry["open_until_mono"] = mono + duration
        entry["open_duration_s"] = duration
        entry["consecutive_provider_failures"] = 0

    def provider_unavailable_error(self, backend: str, model: str) -> Optional[str]:
        """Typed gate error when dispatch must fail fast, else ``None``.

        Consulting the ledger while its open window has expired flips the
        entry to half-open — the next real dispatch IS the probe.
        """
        with self._lock:
            entry = self._entries.get(self._key(backend, model))
            if not entry or entry.get("state") != "open":
                return None
            remaining = (entry.get("open_until_mono") or 0.0) - _mono()
            if remaining <= 0:
                entry["state"] = "half_open"
                entry["updated_at"] = _now()
                self._persist()
                return None
            retry_after = max(1, int(round(remaining)))
            shown_model = entry.get("model") or "(default model)"
            return (
                f"provider_unavailable: {entry.get('backend')}/{shown_model} "
                f"delegate provider circuit open after {entry.get('opens')} open(s) "
                f"(last failure class: {entry.get('error_class')}); "
                f"fail-fast until half-open probe; retry after {retry_after}s"
            )

    def health_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Read-only per-provider health rows (never gated, never raises)."""
        with self._lock:
            now, mono = _now(), _mono()
            out: Dict[str, Dict[str, Any]] = {}
            for key, entry in self._entries.items():
                state = entry.get("state") or "closed"
                retry_after: Optional[int] = None
                if state == "open":
                    remaining = (entry.get("open_until_mono") or 0.0) - mono
                    if remaining <= 0:
                        state = "half_open"  # view-only; consult flips it for real
                    else:
                        retry_after = max(1, int(round(remaining)))
                out[key] = {
                    "backend": entry.get("backend"),
                    "model": entry.get("model"),
                    "state": state,
                    "error_class": entry.get("error_class"),
                    "consecutive_failures": entry.get("consecutive_failures", 0),
                    "opens": entry.get("opens", 0),
                    "open_duration_s": entry.get("open_duration_s"),
                    "retry_after_s": retry_after,
                    "last_failure_at": entry.get("last_failure_at"),
                    "updated_at": entry.get("updated_at"),
                }
            return out


def _ledger_for_home() -> _ProviderHealthLedger:
    """The ledger instance for the current Hermes home (per-profile isolation)."""
    key = ""
    try:
        key = hermes_home_key()
    except Exception:  # noqa: BLE001 - fail-open to one shared ledger
        key = ""
    with _LEDGER_REGISTRY_LOCK:
        ledger = _LEDGERS.get(key)
        if ledger is None:
            ledger = _ProviderHealthLedger(_ledger_relative_path())
            _LEDGERS[key] = ledger
        return ledger


def record_outcome(backend: str, model: str, error_class: Optional[str]) -> None:
    """Record one delegate outcome for (backend, model) in this profile's ledger."""
    try:
        _ledger_for_home().record_outcome(backend, model, error_class)
    except Exception:  # noqa: BLE001 - health bookkeeping never breaks delegation
        logger.exception("delegate provider-health record_outcome failed")


def provider_unavailable_error(backend: str, model: str) -> Optional[str]:
    """Typed fail-fast gate error for (backend, model), or ``None`` to proceed."""
    try:
        return _ledger_for_home().provider_unavailable_error(backend, model)
    except Exception:  # noqa: BLE001 - fail-open
        logger.exception("delegate provider-health gate consult failed")
        return None


def health_snapshot() -> Dict[str, Dict[str, Any]]:
    """Read-only provider-health rows for this profile."""
    try:
        return _ledger_for_home().health_snapshot()
    except Exception:  # noqa: BLE001 - evidence surface never raises
        logger.exception("delegate provider-health snapshot failed")
        return {}
