"""Regression coverage for the typed delegate provider-health surface.

Motivated by the 2026-10-02 provider storm on the pi delegate backend: 71.1%
of recorded delegate turns failed (3,547/5,028 spool envelopes provider/
runtime) yet every dispatch still paid the full spawn + turn + stall-timeout
cost because the delegate layer kept no provider-failure memory — retries
amplified into host resource exhaustion (219 thread-create failures, 139
fork EAGAIN, 25 ENOSPC).

Pins the two halves of ``agent/delegate_provider_health``:
(1) failure classification — every storm signature from the spool evidence
    maps to a stable class, the HTTP taxonomy path and the marker-text path
    agree, and unrecognizable failures fail open to ``unknown``;
(2) the (backend, model)-keyed breaker — opens only on 2 consecutive
    provider-class failures inside a 30-min window, opens for exactly the
    affected pair, escalates on failed half-open probes up to the 4 h cap,
    resets on success, and survives restarts via the durable ledger file.

Hermetic: the autouse home isolation gives each test a fresh profile
(therefore a fresh ledger instance); time is injected through the module's
``_now``/``_mono`` seams, so nothing depends on wall-clock speed.
"""

from __future__ import annotations

import json
from pathlib import Path

import agent.delegate_provider_health as dph
from agent.delegate_provider_health import classify_delegate_failure
from hermes_constants import get_hermes_home


class _FakeClock:
    def __init__(self) -> None:
        self._wall = 1_800_000_000.0
        self._mono = 5_000.0

    def now(self) -> float:
        return self._wall

    def mono(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._wall += seconds
        self._mono += seconds


class _HTTPError(Exception):
    """Minimal HTTP-shaped exception for the taxonomy path."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class _StallError(Exception):
    """Typed stall exception shape produced at the delegate boundary."""

    def __init__(self, had_unsolicited_activity: bool) -> None:
        super().__init__(
            "pi session turn stalled after 900s without observable progress"
        )
        self.had_unsolicited_activity = had_unsolicited_activity


def install_clock(monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(dph, "_now", clock.now)
    monkeypatch.setattr(dph, "_mono", clock.mono)
    return clock


def ledger_file() -> Path:
    # The durable ledger lives OUTSIDE cache/delegate-sessions/ on purpose:
    # metadata pruning globs *.json under delegate-sessions/ and must never
    # delete provider-health state.
    return Path(get_hermes_home()) / "cache" / "delegate-provider-health.json"


def restart_ledger(monkeypatch) -> None:
    """Simulate a process restart: drop instance cache, reload from disk."""
    monkeypatch.setattr(dph, "_LEDGERS", {})


# ------------------------------------------------------------- classification


def test_storm_signatures_map_to_stable_classes():
    """Every failure shape counted in the 2026-10-02 spool evidence keeps a
    stable class: unknown signatures must never silently flip to another row
    later (consumers key policy off these strings)."""
    cases = [
        # 353 cooling-down 429s from the cliproxy aggregator
        ("429 rate_limit_error: All credentials for model glm-4.6 are cooling down", "rate_limit"),
        # 949 pi-side fetch aborts
        ("This operation was aborted", "timeout"),
        # 219 thread-create + 139 fork EAGAIN + 25 ENOSPC host casualties
        ("can't start new thread", "resource_exhausted"),
        ("[Errno 11] Resource temporarily unavailable", "resource_exhausted"),
        ("[Errno 28] No space left on device", "resource_exhausted"),
        # 229 get_state command timeouts + 164 rpc-process exits
        ("pi did not answer command 'get_state'", "transport"),
        ("pi rpc process exited with code 1", "transport"),
        ("pi rpc client is closed", "transport"),
        # provider capacity shapes
        ("The engine is currently overloaded", "overloaded"),
        ("internal server error", "server_error"),
        ("bad gateway", "server_error"),
        # key-resolution / credential shapes
        ("Unauthorized: invalid bearer token", "auth"),
        ("Error code: 403 - Forbidden", "auth"),
    ]
    for text, expected in cases:
        assert classify_delegate_failure(Exception(text)) == expected, text
        assert classify_delegate_failure(text=text) == expected, text


def test_http_taxonomy_and_marker_paths_agree_on_rate_limit():
    """An exception carrying HTTP 429 semantics lands on the same class
    whether the taxonomy path (status extractable) or the marker-text path
    (plain exception) resolves it."""
    via_status = classify_delegate_failure(
        _HTTPError(429, "Error code: 429 - Too Many Requests")
    )
    via_text = classify_delegate_failure(
        Exception("Error code: 429 - Too Many Requests")
    )
    assert via_status == "rate_limit"
    assert via_text == via_status


def test_unrecognized_failures_fail_open_to_unknown():
    assert classify_delegate_failure(Exception("widget seized")) == "unknown"
    assert classify_delegate_failure() == "unknown"
    assert classify_delegate_failure(text="") == "unknown"


def test_stall_split_is_structural_not_textual():
    # Structural evidence wins: the attribute alone decides the split.
    assert (
        classify_delegate_failure(_StallError(had_unsolicited_activity=False))
        == "provider_stall"
    )
    assert (
        classify_delegate_failure(_StallError(had_unsolicited_activity=True))
        == "agent_stall"
    )
    assert (
        classify_delegate_failure(
            Exception("pi session turn stalled after 1800s without observable progress"),
            had_unsolicited_activity=False,
        )
        == "provider_stall"
    )
    # Without structural evidence the message alone cannot prove the failure
    # was provider-side, so it must NOT open the breaker (agent_stall).
    assert (
        classify_delegate_failure(
            Exception("pi session turn stalled after 1800s without observable progress")
        )
        == "agent_stall"
    )


# ------------------------------------------------------------------- breaker


def test_breaker_opens_only_after_two_consecutive_recent_provider_failures(monkeypatch):
    clock = install_clock(monkeypatch)
    backend, model = "pi", "glm-4.6"

    # One provider-class failure never opens: a transient blip must not
    # fail-fast the whole lane.
    dph.record_outcome(backend, model, "rate_limit")
    assert dph.provider_unavailable_error(backend, model) is None

    clock.advance(10.0)
    dph.record_outcome(backend, model, "rate_limit")
    gate = dph.provider_unavailable_error(backend, model)
    assert gate is not None
    assert gate.startswith("provider_unavailable: pi/glm-4.6")
    assert "rate_limit" in gate
    assert "retry after 60s" in gate


def test_stale_pair_does_not_open(monkeypatch):
    clock = install_clock(monkeypatch)
    dph.record_outcome("pi", "glm-4.6", "rate_limit")
    clock.advance(dph._PAIR_WINDOW_S + 1.0)
    dph.record_outcome("pi", "glm-4.6", "rate_limit")
    # The pair window (30 min) expired: this failure restarts the pair
    # instead of opening; the next *fresh* one opens.
    assert dph.provider_unavailable_error("pi", "glm-4.6") is None
    clock.advance(60.0)
    dph.record_outcome("pi", "glm-4.6", "rate_limit")
    assert dph.provider_unavailable_error("pi", "glm-4.6") is not None


def test_non_provider_classes_never_open(monkeypatch):
    install_clock(monkeypatch)
    # Host-pressure and transport casualties of a storm are typed evidence
    # only: gating on them would amplify the very outage being survived.
    for cls in (
        "agent_stall",
        "resource_exhausted",
        "transport",
        "auth",
        "billing",
        "unknown",
    ):
        for _ in range(3):
            dph.record_outcome("pi", "glm-4.6", cls)
        assert dph.provider_unavailable_error("pi", "glm-4.6") is None, cls


def test_breaker_is_keyed_to_backend_and_model(monkeypatch):
    install_clock(monkeypatch)
    for _ in range(2):
        dph.record_outcome("pi", "glm-4.6", "rate_limit")
    assert dph.provider_unavailable_error("pi", "glm-4.6") is not None
    # Other models and other backends are independent circuits.
    assert dph.provider_unavailable_error("pi", "glm-4.7") is None
    assert dph.provider_unavailable_error("opencode", "glm-4.6") is None


def test_half_open_probe_then_success_closes_and_resets(monkeypatch):
    clock = install_clock(monkeypatch)
    backend, model = "pi", "glm-4.6"
    for _ in range(2):
        dph.record_outcome(backend, model, "rate_limit")
    assert dph.provider_unavailable_error(backend, model) is not None

    # Window expires: consult permits dispatch (the probe) and flips the
    # entry to half-open.
    clock.advance(61.0)
    assert dph.provider_unavailable_error(backend, model) is None
    snap = dph.health_snapshot()["pi/glm-4.6"]
    assert snap["state"] == "half_open"

    # A successful probe closes and fully resets the ladder.
    dph.record_outcome(backend, model, None)
    snap = dph.health_snapshot()["pi/glm-4.6"]
    assert snap["state"] == "closed"
    assert snap["opens"] == 0
    assert dph.provider_unavailable_error(backend, model) is None
    # Reset means the next single provider failure is pair member #1 again.
    dph.record_outcome(backend, model, "rate_limit")
    assert dph.provider_unavailable_error(backend, model) is None


def test_failed_probe_escalates_up_to_cap(monkeypatch):
    clock = install_clock(monkeypatch)
    backend, model = "pi", "glm-4.6"
    dph.record_outcome(backend, model, "rate_limit")
    dph.record_outcome(backend, model, "rate_limit")
    gate = dph.provider_unavailable_error(backend, model)
    assert gate is not None and "retry after 60s" in gate

    # Each failed half-open probe re-opens one rung up the exponential
    # ladder, doubling from 60 s, capped at the 4 h house maximum.
    expected = 120
    for _ in range(12):
        snap = dph.health_snapshot()["pi/glm-4.6"]
        clock.advance((snap["retry_after_s"] or 1) + 0.1)
        assert dph.provider_unavailable_error(backend, model) is None  # half-open
        dph.record_outcome(backend, model, "rate_limit")  # probe fails
        gate = dph.provider_unavailable_error(backend, model)
        assert gate is not None
        snap = dph.health_snapshot()["pi/glm-4.6"]
        assert snap["retry_after_s"] <= 14400
        assert snap["retry_after_s"] == min(expected, 14400)
        expected *= 2
    assert dph.health_snapshot()["pi/glm-4.6"]["retry_after_s"] == 14400


def test_success_out_of_the_blue_closes_an_open_circuit(monkeypatch):
    clock = install_clock(monkeypatch)
    for _ in range(2):
        dph.record_outcome("pi", "glm-4.6", "rate_limit")
    assert dph.provider_unavailable_error("pi", "glm-4.6") is not None
    # An in-flight turn that started before the gate succeeded: the provider
    # demonstrably recovered, so the circuit must not stay open.
    dph.record_outcome("pi", "glm-4.6", None)
    assert dph.provider_unavailable_error("pi", "glm-4.6") is None


# ----------------------------------------------------------- durable ledger


def test_ledger_state_survives_restart(monkeypatch):
    clock = install_clock(monkeypatch)
    for _ in range(2):
        dph.record_outcome("pi", "glm-4.6", "rate_limit")
    assert ledger_file().is_file()

    restart_ledger(monkeypatch)
    gate = dph.provider_unavailable_error("pi", "glm-4.6")
    assert gate is not None
    assert gate.startswith("provider_unavailable: pi/glm-4.6")


def test_expired_circuit_survives_restart_as_half_open(monkeypatch):
    clock = install_clock(monkeypatch)
    for _ in range(2):
        dph.record_outcome("pi", "glm-4.6", "rate_limit")
    clock.advance(61.0)
    restart_ledger(monkeypatch)
    assert dph.provider_unavailable_error("pi", "glm-4.6") is None
    assert dph.health_snapshot()["pi/glm-4.6"]["state"] == "half_open"


def test_corrupt_ledger_file_fails_open(monkeypatch, tmp_path):
    install_clock(monkeypatch)
    target = Path(get_hermes_home()) / "cache" / "delegate-provider-health.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json at all", encoding="utf-8")
    restart_ledger(monkeypatch)
    assert dph.provider_unavailable_error("pi", "glm-4.6") is None
    assert dph.health_snapshot() == {}
    # And the ledger keeps working afterwards (first write replaces junk).
    dph.record_outcome("pi", "glm-4.6", "rate_limit")
    dph.record_outcome("pi", "glm-4.6", "rate_limit")
    assert dph.provider_unavailable_error("pi", "glm-4.6") is not None
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == 1


def test_health_snapshot_is_read_only_evidence(monkeypatch):
    install_clock(monkeypatch)
    dph.record_outcome("pi", "glm-4.6", "transport")
    snap = dph.health_snapshot()["pi/glm-4.6"]
    assert snap["backend"] == "pi"
    assert snap["model"] == "glm-4.6"
    assert snap["state"] == "closed"
    assert snap["error_class"] == "transport"
    assert snap["consecutive_failures"] == 1
    assert snap["opens"] == 0
    assert snap["retry_after_s"] is None
    # No gate error: closed rows never block dispatch.
    assert dph.provider_unavailable_error("pi", "glm-4.6") is None
