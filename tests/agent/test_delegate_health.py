"""Delegate provider-health ledger contract (bounded circuit breaker).

Regression family: cognitive-continuity.autonomy-recovery-workers-fail-closed-loop
(09-30 cliproxy cooling-down storm stalled parallel delegates 1800-3600s each
and every retry re-entered the identical dead provider). The breaker bounds
that damage — and must itself never become a new way to fail closed: non-provider
failure classes never open it.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from agent.delegate_health import (
    CircuitOpen,
    DelegateHealthLedger,
    FAILURE_THRESHOLD,
    INITIAL_COOLDOWN_S,
    MAX_COOLDOWN_S,
    WINDOW_S,
    get_delegate_health_ledger,
    reset_delegate_health_ledger,
)

KEY = ("pi", "glm-4.6")
OTHER_KEY = ("pi", "claude-opus-4")


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_ledger() -> tuple[DelegateHealthLedger, FakeClock]:
    clock = FakeClock()
    return DelegateHealthLedger(now=clock), clock


def open_ledger(ledger, clock):
    """Drive the key to an open circuit; clock ends at the opening moment."""
    for i in range(FAILURE_THRESHOLD):
        ledger.record_failure(KEY, "rate_limit")
        if i < FAILURE_THRESHOLD - 1:
            clock.advance(1.0)
    state = ledger.check(KEY)
    assert isinstance(state, CircuitOpen)
    return state


def test_three_provider_failures_in_window_open_the_circuit():
    ledger, clock = make_ledger()
    for i in range(FAILURE_THRESHOLD - 1):
        ledger.record_failure(KEY, "rate_limit")
        clock.advance(10.0)
        assert ledger.check(KEY) is None
    ledger.record_failure(KEY, "rate_limit")
    state = ledger.check(KEY)
    assert isinstance(state, CircuitOpen)
    assert state.last_error_class == "rate_limit"
    assert state.consecutive == FAILURE_THRESHOLD
    assert state.retry_after_s == pytest.approx(INITIAL_COOLDOWN_S)
    clock.advance(30.0)
    assert ledger.check(KEY).retry_after_s == pytest.approx(INITIAL_COOLDOWN_S - 30.0)


def test_failures_farther_apart_than_window_never_open():
    ledger, clock = make_ledger()
    for _ in range(FAILURE_THRESHOLD + 3):
        ledger.record_failure(KEY, "overloaded")
        clock.advance(WINDOW_S + 100.0)
        assert ledger.check(KEY) is None


def test_entries_are_isolated_per_key():
    ledger, clock = make_ledger()
    for _ in range(FAILURE_THRESHOLD):
        ledger.record_failure(KEY, "provider_stall")
        clock.advance(1.0)
    assert isinstance(ledger.check(KEY), CircuitOpen)
    assert ledger.check(OTHER_KEY) is None


@pytest.mark.parametrize(
    "error_class", ["resource_exhausted", "agent_stall", "unknown", "transport", ""]
)
def test_non_provider_classes_never_open(error_class):
    ledger, _clock = make_ledger()
    for _ in range(FAILURE_THRESHOLD * 3):
        ledger.record_failure(KEY, error_class)
    assert ledger.check(KEY) is None


def test_half_open_grants_exactly_one_probe_after_cooldown():
    ledger, clock = make_ledger()
    open_ledger(ledger, clock)
    clock.advance(INITIAL_COOLDOWN_S - 1.0)
    assert isinstance(ledger.check(KEY), CircuitOpen)
    clock.advance(1.0)
    # First caller past the cooldown is the single probe.
    assert ledger.check(KEY) is None
    # A second dispatch while the probe is unresolved is still refused.
    state = ledger.check(KEY)
    assert isinstance(state, CircuitOpen)
    # The probe succeeds: circuit closes fully, and a fresh streak is needed.
    ledger.record_success(KEY)
    assert ledger.check(KEY) is None
    ledger.record_failure(KEY, "rate_limit")
    assert ledger.check(KEY) is None


def test_failed_probe_doubles_cooldown_up_to_cap():
    ledger, clock = make_ledger()
    open_ledger(ledger, clock)
    clock.advance(INITIAL_COOLDOWN_S)
    assert ledger.check(KEY) is None  # probe granted
    ledger.record_failure(KEY, "rate_limit")
    state = ledger.check(KEY)
    assert isinstance(state, CircuitOpen)
    assert state.retry_after_s == pytest.approx(MAX_COOLDOWN_S)  # 900 * 2
    clock.advance(MAX_COOLDOWN_S)
    assert ledger.check(KEY) is None  # second probe


def test_probe_transport_failure_does_not_wedge():
    """A probe turn that dies NON-provider (spawn failure, transport, local
    error) must resolve the in-flight probe instead of refusing every later
    check forever: those errors carry no evidence against the provider, and
    this ledger must never itself become a fail-closed loop."""
    ledger, clock = make_ledger()
    open_ledger(ledger, clock)
    clock.advance(INITIAL_COOLDOWN_S)
    assert ledger.check(KEY) is None  # the single probe is granted
    # The probe turn dies before reaching the provider (e.g. pi binary
    # failed to spawn -> classify_delegate_failure -> "transport").
    ledger.record_failure(KEY, "transport")
    # Cooldown has elapsed and no probe is in flight: the next dispatch gets
    # a fresh probe — not a permanent "probe already in flight" refusal.
    assert ledger.check(KEY) is None
    # The ledger is still coherent: that probe failing provider-side re-opens
    # with a doubled cooldown, exactly like a normal failed probe.
    ledger.record_failure(KEY, "rate_limit")
    state = ledger.check(KEY)
    assert isinstance(state, CircuitOpen)
    assert state.retry_after_s == pytest.approx(MAX_COOLDOWN_S)
    ledger.record_failure(KEY, "rate_limit")
    state = ledger.check(KEY)
    # 1800 * 2 would be 3600; the ladder is capped.
    assert state.retry_after_s == pytest.approx(MAX_COOLDOWN_S)


def test_success_closes_and_resets_the_streak():
    ledger, clock = make_ledger()
    ledger.record_failure(KEY, "rate_limit")
    ledger.record_failure(KEY, "rate_limit")
    clock.advance(1.0)
    ledger.record_success(KEY)
    # Two more failures after the success are below threshold: the earlier
    # streak did not survive it.
    ledger.record_failure(KEY, "rate_limit")
    assert ledger.check(KEY) is None
    ledger.record_failure(KEY, "rate_limit")
    assert ledger.check(KEY) is None
    ledger.record_failure(KEY, "rate_limit")
    assert isinstance(ledger.check(KEY), CircuitOpen)


def test_reset_delegate_health_ledger_clears_global_state():
    # Reset first: the ledger is process-global, so state recorded by an
    # earlier test in this file must not leak into this one (reset is the
    # isolation seam — it re-reads this test's own hermes home, which is
    # fresh under the per-test HERMES_HOME fixture).
    reset_delegate_health_ledger()
    get_delegate_health_ledger().record_failure(KEY, "rate_limit")
    fresh = reset_delegate_health_ledger()
    assert fresh is get_delegate_health_ledger()
    assert fresh.check(KEY) is None


def test_ledger_registry_is_per_profile_home(tmp_path, monkeypatch):
    """Multiplex: one process, two profiles (A→B→A). Breaker memory must be
    slotted by hermes_home_key() — an open circuit in profile A must neither
    refuse profile B's dispatches nor merge entries into B's state file."""
    reset_delegate_health_ledger()
    home_a = tmp_path / "profiles" / "a"
    home_b = tmp_path / "profiles" / "b"
    for home in (home_a, home_b):
        (home / "cache").mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(home_a))
    ledger_a = get_delegate_health_ledger()
    for _ in range(FAILURE_THRESHOLD):
        ledger_a.record_failure(KEY, "rate_limit")
    assert isinstance(ledger_a.check(KEY), CircuitOpen)
    assert (home_a / "cache" / "delegate-provider-health.json").exists()

    monkeypatch.setenv("HERMES_HOME", str(home_b))
    ledger_b = get_delegate_health_ledger()
    assert ledger_b is not ledger_a
    assert ledger_b.check(KEY) is None  # B inherits nothing from A
    # B's own state file carries only B's entries — never A's.
    ledger_b.record_failure(OTHER_KEY, "rate_limit")
    state_b = home_b / "cache" / "delegate-provider-health.json"
    assert state_b.exists()
    assert "glm-4.6" not in state_b.read_text(encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(home_a))
    assert get_delegate_health_ledger() is ledger_a  # A's slot survives
    assert isinstance(get_delegate_health_ledger().check(KEY), CircuitOpen)
    reset_delegate_health_ledger()


# --- durable state across restarts (the emergency-restart shape) ----------
# The 10-02 continuity repair RESTARTED the gateway mid-storm; an
# in-memory-only ledger forgets every open circuit at that boundary and
# post-restart dispatches re-enter the same dead provider at full cost.


def test_open_circuit_survives_restart_via_state_file(tmp_path):
    """An open circuit written to the state file re-opens in a fresh ledger:
    cooldowns are rebased through real save->load time onto the new clock."""
    path = tmp_path / "cache" / "delegate-provider-health.json"
    clock = FakeClock()
    ledger = DelegateHealthLedger(now=clock, state_path=path)
    open_ledger(ledger, clock)
    assert path.exists()  # mutations persist; the file is the restart carrier

    restarted = DelegateHealthLedger(
        now=FakeClock(start=clock.now + 5.0), state_path=path
    )
    state = restarted.check(KEY)
    assert isinstance(state, CircuitOpen)
    assert state.last_error_class == "rate_limit"
    assert state.consecutive == FAILURE_THRESHOLD
    # 5s of the 900s cooldown burned between save and load (plus ms drift).
    assert state.retry_after_s == pytest.approx(INITIAL_COOLDOWN_S - 5.0, abs=5.0)
    assert restarted.check(OTHER_KEY) is None  # only the saved key came back


def test_reset_reloads_open_circuit_from_default_state_file():
    """reset + re-instantiation keeps open circuits via the default per-home
    state file (cache/delegate-provider-health.json under the Hermes home)."""
    reset_delegate_health_ledger()
    ledger = get_delegate_health_ledger()
    for _ in range(FAILURE_THRESHOLD):
        ledger.record_failure(KEY, "rate_limit")
    assert isinstance(ledger.check(KEY), CircuitOpen)
    state_file = (
        Path(os.environ["HERMES_HOME"]) / "cache" / "delegate-provider-health.json"
    )
    assert state_file.exists()

    fresh = reset_delegate_health_ledger()
    state = fresh.check(KEY)
    assert isinstance(state, CircuitOpen)
    assert state.last_error_class == "rate_limit"
    assert state.retry_after_s > INITIAL_COOLDOWN_S - 60.0


def test_success_removes_the_persisted_entry(tmp_path):
    path = tmp_path / "cache" / "delegate-provider-health.json"
    clock = FakeClock()
    ledger = DelegateHealthLedger(now=clock, state_path=path)
    open_ledger(ledger, clock)
    ledger.record_success(KEY)

    restarted = DelegateHealthLedger(now=FakeClock(start=clock.now), state_path=path)
    assert restarted.check(KEY) is None


def test_restart_regrants_a_probe_in_flight_at_shutdown(tmp_path):
    """A half-open probe granted just before a restart must not wedge the
    circuit fail-closed: the restarted process grants one fresh probe."""
    path = tmp_path / "cache" / "delegate-provider-health.json"
    clock = FakeClock()
    ledger = DelegateHealthLedger(now=clock, state_path=path)
    open_ledger(ledger, clock)
    clock.advance(INITIAL_COOLDOWN_S)
    assert ledger.check(KEY) is None  # probe granted (probing=True)

    restarted = DelegateHealthLedger(now=FakeClock(start=clock.now), state_path=path)
    assert restarted.check(KEY) is None  # re-granted, not refused forever


def test_corrupt_or_foreign_state_file_fails_open_to_fresh(tmp_path):
    path = tmp_path / "cache" / "delegate-provider-health.json"
    path.parent.mkdir(parents=True)
    for garbage in (
        "{not json at all",
        '["a", "list", "not", "a", "dict"]',
        '{"version": 99, "entries": {}}',
    ):
        path.write_text(garbage, encoding="utf-8")
        ledger = DelegateHealthLedger(now=FakeClock(), state_path=path)
        assert ledger.check(KEY) is None
        ledger.record_failure(KEY, "rate_limit")  # still fully usable
        assert ledger.check(KEY) is None
    assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)


def test_concurrent_mutation_and_persist_never_raises(tmp_path):
    path = tmp_path / "delegate-provider-health.json"
    ledger = DelegateHealthLedger(state_path=path)
    errors: list = []

    def hammer(worker: int) -> None:
        try:
            key = ("pi", f"model-{worker}")
            for _ in range(50):
                ledger.record_failure(key, "rate_limit")
                ledger.check(key)
                ledger.record_success(key)
        except Exception as exc:  # pragma: no cover - failure evidence
            errors.append(exc)

    threads = [
        threading.Thread(target=hammer, args=(worker,)) for worker in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    # The surviving file is well-formed despite 8 interleaved writers.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("entries"), dict)
