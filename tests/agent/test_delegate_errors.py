"""Classifier contracts for the typed delegate failure vocabulary (T0/D1).

Every row pins the mapping the A4 remediation depends on: the conductor's
failure-family typing reads the error class, the provider-health breaker
opens only on provider classes, and metadata v4 persists error_class — a
drifted mapping silently re-types provider storms as transport noise, which
is exactly the original incident (stalls classified "transport/phase budget"
while the provider was cooling down for 1800s).
"""

from __future__ import annotations

import pytest

from agent.delegate_errors import (
    PROVIDER_FAILURE_CLASSES,
    DelegateTurnStalled,
    classify_delegate_failure,
)


def test_delegate_turn_stalled_is_a_timeout_error_with_typed_attrs():
    """Subclass contract: existing ``except TimeoutError`` consumers, the
    spool's stall-marker regex, and pinned wording all keep working."""
    message = (
        "pi session turn timed out: stalled after 1800s without observable progress"
    )
    exc = DelegateTurnStalled(
        message,
        error_class="rate_limit",
        provider_signal="Rate limit: disabling model glm-4.6 for 1800 seconds",
        retry_after=1800.0,
        zero_activity=True,
    )
    assert isinstance(exc, TimeoutError)
    assert str(exc) == message
    assert exc.error_class == "rate_limit"
    assert "Rate limit" in exc.provider_signal
    assert exc.retry_after == 1800.0
    assert exc.zero_activity is True

    bare = DelegateTurnStalled("wedged", error_class="agent_stall")
    assert bare.provider_signal == ""
    assert bare.retry_after is None
    assert bare.zero_activity is False


@pytest.mark.parametrize(
    ("text", "expected_class"),
    [
        # Rate-limit signatures — observed on every storm day (agent.log.3).
        ("Rate limit: disabling model glm-4.6 for 1800 seconds (cooling down)", "rate_limit"),
        ("HTTP 429 Too Many Requests", "rate_limit"),
        ("rate_limit exceeded for provider cliproxyapi", "rate_limit"),
        ("usage limit reached on this account", "rate_limit"),
        # Overloaded upstream.
        ("HTTP 503 Service Unavailable", "overloaded"),
        ("provider is overloaded, try later", "overloaded"),
        # Native bootstrap handshake — must outrank the generic timeout
        # table (pi_rpc_client raises this exact wording when the staged
        # handshake ladder is exhausted).
        ("pi did not answer command 'get_state'", "bootstrap_timeout"),
        # Timeout / abort paths.
        ("operation was aborted", "timeout"),
        ("request timed out upstream", "timeout"),
        # Local-host exhaustion — evidence only, never opens the breaker.
        ("fork: Resource temporarily unavailable", "resource_exhausted"),
        ("can't start new thread", "resource_exhausted"),
        ("No space left on device", "resource_exhausted"),
        ("OSError: [Errno 11] retry", "resource_exhausted"),
        # Pi lifecycle / transport.
        ("pi rpc process exited mid-turn", "transport"),
        ("pi rpc client is closed", "transport"),
        ("Could not start pi process", "transport"),
    ],
)
def test_signature_table(text, expected_class):
    error_class, provider_signal, _retry_after = classify_delegate_failure(
        text, zero_activity=False
    )
    assert error_class == expected_class
    assert provider_signal  # a text match always yields bounded evidence


def test_status_codes_need_word_boundaries():
    """Ordinary numbers in prose must not classify: ``14293`` contains "429"
    and ``25030`` contains "503", but neither is a status code."""
    error_class, provider_signal, retry_after = classify_delegate_failure(
        "wrote 14293 bytes in 25030 ms", zero_activity=True
    )
    assert error_class == "provider_stall"  # fell through to the structural signal
    assert provider_signal == ""
    assert retry_after is None


def test_rate_limit_cooldown_is_parsed_as_retry_after():
    _cls, _signal, retry_after = classify_delegate_failure(
        "Rate limit: disabling model glm-4.6 for 1800 seconds (cooling down)",
        zero_activity=False,
    )
    assert retry_after == 1800.0
    # No cooldown advice stated -> no retry hint fabricated.
    _cls, _signal, retry_after = classify_delegate_failure(
        "rate limit hit", zero_activity=False
    )
    assert retry_after is None


def test_zero_activity_splits_provider_stall_from_agent_stall():
    """Prompt acked but zero unsolicited events = dead upstream provider;
    streamed-something-then-wedged = the delegate agent's own stall."""
    assert classify_delegate_failure("", zero_activity=True) == (
        "provider_stall",
        "",
        None,
    )
    error_class, _signal, _retry = classify_delegate_failure(
        "mid-sentence and then nothing", zero_activity=False
    )
    assert error_class == "agent_stall"
    # Text signatures outrank the structural signal: a rate-limit line
    # streamed just before silence still classifies as rate_limit.
    error_class, _signal, _retry = classify_delegate_failure(
        "429 Too Many Requests", zero_activity=True
    )
    assert error_class == "rate_limit"


def test_unmatched_text_fails_open_to_unknown():
    """The classifier never raises and never fabricates evidence."""
    assert classify_delegate_failure("", zero_activity=False) == ("unknown", "", None)
    assert classify_delegate_failure(None, zero_activity=False) == (  # type: ignore[arg-type]
        "unknown",
        "",
        None,
    )


def test_rate_limit_beats_lower_priority_tables():
    """Table order is the precedence contract: provider-refusal evidence
    outranks generic overload/timeout wording in the same text."""
    error_class, _signal, _retry = classify_delegate_failure(
        "429 retry soon; service overloaded; request timed out",
        zero_activity=False,
    )
    assert error_class == "rate_limit"


def test_provider_signal_is_bounded_and_case_preserving():
    line = "Rate limit: disabling model glm-4.6 " + "x" * 500
    _cls, provider_signal, _retry = classify_delegate_failure(
        line, zero_activity=False
    )
    assert provider_signal.startswith("Rate limit")
    assert len(provider_signal) <= 200


def test_only_provider_conditions_may_open_the_breaker():
    """Relationship the health ledger depends on: provider-death classes are
    breaker-eligible; delegate-agent, local-host, and transport classes are
    not — they must never shadow a healthy provider on the same key."""
    assert {"rate_limit", "overloaded", "timeout", "provider_stall"} <= (
        PROVIDER_FAILURE_CLASSES
    )
    assert not {"agent_stall", "resource_exhausted", "transport", "unknown"} & (
        PROVIDER_FAILURE_CLASSES
    )


# ------------------------------------------- native bootstrap handshake (U1)


def test_handshake_timeout_classifies_bootstrap_timeout():
    """The evidenced spool-boundary string — ``pi did not answer command
    'get_state'`` (10-06 recurrence: get_state answered at 30.9s under load
    17.5-26.5) — pins to its own class instead of degrading to
    ``agent_stall``."""
    error_class, provider_signal, retry_after = classify_delegate_failure(
        "pi did not answer command 'get_state'", zero_activity=False
    )
    assert error_class == "bootstrap_timeout"
    assert "did not answer" in provider_signal
    assert retry_after is None


def test_handshake_marker_outranks_generic_timeout_table():
    """Table order is the precedence contract: handshake failures often
    ride alongside abort/timeout prose ('operation was aborted' on the same
    failure); the specific handshake signature must win over
    ``_TIMEOUT_MARKERS``."""
    error_class, _signal, _retry = classify_delegate_failure(
        "pi did not answer command 'start': operation was aborted",
        zero_activity=False,
    )
    assert error_class == "bootstrap_timeout"


def test_handshake_timeout_with_zero_activity_is_not_provider_stall():
    """Without the handshake class this exact text with zero_activity=True
    classified ``provider_stall`` — a PROVIDER class — so a host-load
    handshake wedge could open the breaker against a healthy provider.
    The marker table must outrank the structural signal."""
    error_class, _signal, _retry = classify_delegate_failure(
        "pi did not answer command 'get_messages'", zero_activity=True
    )
    assert error_class == "bootstrap_timeout"


def test_bootstrap_timeout_is_not_a_provider_failure_class():
    """Invariant (green by design; the classifier-level reds live above):
    the breaker vocabulary must never admit the handshake class — host-load
    bring-up episodes must not cool a healthy provider."""
    assert "bootstrap_timeout" not in PROVIDER_FAILURE_CLASSES
