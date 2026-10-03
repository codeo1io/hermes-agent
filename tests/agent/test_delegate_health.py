"""Delegate provider-health ledger contract (bounded circuit breaker).

Regression family: cognitive-continuity.autonomy-recovery-workers-fail-closed-loop
(09-30 cliproxy cooling-down storm stalled parallel delegates 1800-3600s each
and every retry re-entered the identical dead provider). The breaker bounds
that damage — and must itself never become a new way to fail closed: non-provider
failure classes never open it.
"""

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
    get_delegate_health_ledger().record_failure(KEY, "rate_limit")
    fresh = reset_delegate_health_ledger()
    assert fresh is get_delegate_health_ledger()
    assert fresh.check(KEY) is None
