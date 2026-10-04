"""Typed errors and failure classification for the native delegate boundary.

The delegate stack (``agent.pi_rpc_client`` -> ``tools.delegate_session_tool``
-> the conductor spool) historically collapsed every failure into prose. Prose
forces each layer to re-derive structure from text, and that is exactly how a
provider-stalled delegate turn masqueraded as a generic transport error for
days (finding ``cognitive-continuity.autonomy-recovery-workers-fail-closed-loop``):
the same ``stalled after Ns`` message was classified differently at every hop.

This module owns the shared vocabulary instead: one exception type carrying the
classification as structured attributes, and one classifier mapping free-form
failure text onto that vocabulary. Class names mirror
``agent.error_classifier::FailoverReason`` where they describe the same
provider condition (``rate_limit`` / ``overloaded`` / ``timeout`` /
``unknown``); delegate-specific conditions get their own names
(``provider_stall`` / ``agent_stall`` / ``resource_exhausted`` /
``transport``). Fail-open by design: the classifier never raises and never
fabricates evidence, so a new failure shape degrades to ``unknown`` rather
than taking the delegation path down.
"""

from __future__ import annotations

import re

__all__ = [
    "DelegateTurnStalled",
    "PROVIDER_FAILURE_CLASSES",
    "classify_delegate_failure",
]


class DelegateTurnStalled(TimeoutError):
    """A delegate turn made no observable progress within its stall window.

    Remains a ``TimeoutError`` subclass so every existing consumer — ``except
    TimeoutError`` handlers, the conductor spool's ``stalled after`` marker,
    and tests pinning the wording — keeps working unchanged. New consumers
    read the structured attributes instead of re-parsing the message:

    - ``error_class``: vocabulary class (see :func:`classify_delegate_failure`)
    - ``provider_signal``: bounded evidence line that matched, if any
    - ``retry_after``: provider-advised retry delay in seconds, when stated
    - ``zero_activity``: no unsolicited delegate event arrived since the
      prompt ack — the structural signature of a dead upstream provider
      rather than a wedged delegate agent
    - ``liveness_triage``: what a stall-time probe found (process alive?
      RPC answering?) — distinguishes a process wedge from a
      responsive-but-unproductive turn. ``None`` when no triage ran.
    """

    def __init__(
        self,
        message: str,
        *,
        error_class: str,
        provider_signal: str = "",
        retry_after: float | None = None,
        zero_activity: bool = False,
        liveness_triage: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.provider_signal = provider_signal
        self.retry_after = retry_after
        self.zero_activity = zero_activity
        self.liveness_triage = liveness_triage


# Only these classes may open the delegate provider-health breaker
# (agent/delegate_health.py): they describe the upstream model provider being
# unavailable, not the delegate agent's own behavior (``agent_stall``), the
# local host (``resource_exhausted``), or the RPC transport (``transport``).
PROVIDER_FAILURE_CLASSES = frozenset(
    {"rate_limit", "overloaded", "timeout", "provider_stall"}
)

_RETRY_AFTER_RE = re.compile(r"for (\d+) seconds?")

# Signature phrases from the observed failure corpus (provider storm logs,
# cliproxy/stderr tails, pi abort paths). Bare status codes use word
# boundaries so ordinary numbers ("14293 bytes") cannot match.
_RATE_LIMIT_MARKERS: tuple = (
    re.compile(r"\b429\b"),
    "rate limit",
    "rate_limit",
    "cooling down",
    "usage limit",
)
_OVERLOADED_MARKERS: tuple = (re.compile(r"\b503\b"), "overloaded")
_TIMEOUT_MARKERS: tuple = ("timed out", "operation was aborted", "aborted")
_RESOURCE_MARKERS: tuple = (
    "resource temporarily unavailable",
    "can't start new thread",
    "cannot start new thread",
    "no space left on device",
    "errno 11",
)
_TRANSPORT_MARKERS: tuple = (
    "pi rpc process exited",
    "pi rpc client is closed",
    "could not start",
)


def _find_marker(lowered: str, marker) -> tuple[int, str]:
    """Char offset and matched text of ``marker`` in lowercased text, (-1, "")."""
    if isinstance(marker, str):
        idx = lowered.find(marker)
        return idx, marker
    match = marker.search(lowered)
    return (match.start(), match.group(0)) if match else (-1, "")


def _evidence_line(text: str, start: int, default: str) -> str:
    """Bounded line of the original (case-preserving) text starting at ``start``."""
    if start < 0 or start >= len(text):
        return default
    end = text.find("\n", start)
    line = text[start:] if end < 0 else text[start:end]
    return line.strip()[:200]


def classify_delegate_failure(
    text: str, *, zero_activity: bool
) -> tuple[str, str, float | None]:
    """Classify delegate failure text -> ``(error_class, provider_signal, retry_after)``.

    ``provider_signal`` is the matched evidence line (original casing, bounded),
    empty when the class came from a structural signal rather than text.
    ``zero_activity`` is the "prompt acked but no unsolicited delegate event
    since" signal: it distinguishes a dead upstream provider (no events at all)
    from a delegate agent that streamed something and then wedged. Signature
    phrases win over the structural signal so a rate-limit line streamed just
    before silence still classifies as ``rate_limit``. Fail-open: unmatched
    text degrades to ``agent_stall``/``unknown`` instead of raising.
    """
    lowered = (text or "").lower()
    for markers, error_class in (
        (_RATE_LIMIT_MARKERS, "rate_limit"),
        (_OVERLOADED_MARKERS, "overloaded"),
        (_TIMEOUT_MARKERS, "timeout"),
        (_RESOURCE_MARKERS, "resource_exhausted"),
        (_TRANSPORT_MARKERS, "transport"),
    ):
        for marker in markers:
            start, phrase = _find_marker(lowered, marker)
            if start >= 0:
                retry_after: float | None = None
                if error_class == "rate_limit":
                    match = _RETRY_AFTER_RE.search(lowered)
                    if match:
                        retry_after = float(match.group(1))
                return error_class, _evidence_line(text, start, phrase), retry_after
    if zero_activity:
        return "provider_stall", "", None
    if lowered.strip():
        return "agent_stall", "", None
    return "unknown", "", None
