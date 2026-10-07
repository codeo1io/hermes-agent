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

from agent.delegate_errors import classify_delegate_failure
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


def test_three_handshake_failures_do_not_open_the_circuit():
    """Invariant companion to the ``bootstrap_timeout`` class (plan U1):
    three classified handshake timeouts — the evidenced host-load wedge —
    never open the breaker, so a healthy provider is not cooled by a slow
    local bring-up. (Invariant, not red by design: the classifier-level red
    is pinned in tests/agent/test_delegate_errors.py.)"""
    ledger, clock = make_ledger()
    for _ in range(FAILURE_THRESHOLD * 3):
        error_class, _signal, _retry = classify_delegate_failure(
            "pi did not answer command 'get_state'", zero_activity=True
        )
        ledger.record_failure(KEY, error_class)
        clock.advance(1.0)
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


def test_non_provider_probe_death_costs_one_cooldown_not_a_wedge():
    """Review regression (fail-closed wedge): a probe turn that dies with a
    non-provider class (e.g. agent_stall) DID consume the granted half-open
    probe, so it must resolve it as inconclusive and re-arm the window from
    now — the key refuses for one more cooldown and then grants a fresh
    probe. It may never leave the circuit fail-closed forever on a probe
    nobody will answer."""
    ledger, clock = make_ledger()
    open_ledger(ledger, clock)
    clock.advance(INITIAL_COOLDOWN_S)
    assert ledger.check(KEY) is None  # the single probe is granted
    ledger.record_failure(KEY, "agent_stall")  # probe turn dies non-provider
    state = ledger.check(KEY)
    # Inconclusive: window re-armed from the resolution, cooldown unchanged,
    # streak preserved for the next provider-class failure.
    assert isinstance(state, CircuitOpen)
    assert state.retry_after_s == pytest.approx(INITIAL_COOLDOWN_S)
    clock.advance(INITIAL_COOLDOWN_S)
    assert ledger.check(KEY) is None  # fresh probe — the circuit is not wedged


def test_unanswered_lost_probe_regrants_after_one_cooldown():
    """Review regression: a probe whose turn never reports back (thread
    killed by a BaseException, bootstrap death before any turn ran, crash
    between grant and resolution) is declared lost one full cooldown past
    its grant and re-armed — a dead probe costs one cooldown, never the
    process lifetime."""
    ledger, clock = make_ledger()
    open_ledger(ledger, clock)
    clock.advance(INITIAL_COOLDOWN_S)
    assert ledger.check(KEY) is None  # probe granted; nobody ever resolves it
    clock.advance(INITIAL_COOLDOWN_S / 2)
    assert isinstance(ledger.check(KEY), CircuitOpen)  # still in flight
    clock.advance(INITIAL_COOLDOWN_S)  # one full cooldown past the grant
    assert ledger.check(KEY) is None  # declared lost; fresh probe granted


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


# --- per-profile isolation (the multiplex / conductor-spool shape) --------
# One spool or gateway process serves every profile; breaker state must be
# keyed by the profile home or profile A's outage gates profile B's
# dispatches — and A's open entries would lazily-persist into B's state file.


def test_ledger_registry_is_keyed_per_profile_home(tmp_path, monkeypatch):
    """Two homes in ONE process (A -> B -> A): each gets its own ledger
    instance and its own durable state file; a failure recorded under B
    never touches A's in-memory circuit or A's file."""
    home_a = tmp_path / "profiles" / "alpha"
    home_b = tmp_path / "profiles" / "beta"
    home_a.mkdir(parents=True)
    home_b.mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(home_a))
    reset_delegate_health_ledger()
    ledger_a = get_delegate_health_ledger()
    for _ in range(FAILURE_THRESHOLD):
        ledger_a.record_failure(KEY, "rate_limit")
    assert isinstance(ledger_a.check(KEY), CircuitOpen)
    file_a = home_a / "cache" / "delegate-provider-health.json"
    assert file_a.exists()
    a_bytes = file_a.read_bytes()

    # Same process, different profile: no shared in-memory state, no gating,
    # no contamination of A's durable file.
    monkeypatch.setenv("HERMES_HOME", str(home_b))
    ledger_b = get_delegate_health_ledger()
    assert ledger_b is not ledger_a
    assert ledger_b.check(KEY) is None  # A's open circuit never gates B
    ledger_b.record_failure(KEY, "rate_limit")
    file_b = home_b / "cache" / "delegate-provider-health.json"
    assert file_b.exists()  # B's streak persisted to B's own file
    assert file_a.read_bytes() == a_bytes  # ...and only to B's file

    # A -> B -> A: re-entering A's scope keeps A's open circuit alive (the
    # registry entry survived the excursion; a reset would still recover it
    # from A's own file, per the restart tests above).
    monkeypatch.setenv("HERMES_HOME", str(home_a))
    assert get_delegate_health_ledger() is ledger_a
    assert isinstance(get_delegate_health_ledger().check(KEY), CircuitOpen)

    # Registry hygiene: reset drops every home's ledger at once.
    monkeypatch.setenv("HERMES_HOME", str(home_b))
    reset_delegate_health_ledger()
    assert get_delegate_health_ledger() is not ledger_b
