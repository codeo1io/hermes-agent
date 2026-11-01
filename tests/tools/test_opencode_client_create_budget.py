"""Cold-directory create budget regression (incident 2026-11-01 13:53Z).

msn-m5-opencode-recovery-005 failed with "Could not start opencode delegate
session: timed out" after 60s: the shared server had never hosted the
delegate's working directory, so POST /session synchronously bootstrapped a
full OpenCode Instance (config + LSP + plugin scan) that took 63.7s, while the
client transport carried a flat 60s socket timeout and aborted 3.8s before the
bootstrap finished — orphaning a session the server actually created.

The A4 readiness ladder existed but only gated the spawn wait in
acquire_opencode_server; the per-request transport never saw it. These tests
pin the wiring: the session-create transport budget inherits the ladder total
(30+90+240 clipped by BOOTSTRAP_TOTAL_CAP), both for a fresh start and a
resume-fence GET on a persisted native id.
"""

import agent.opencode_client as oc
from agent.delegate_start_budget import (
    BOOTSTRAP_STAGE_LADDER,
    BOOTSTRAP_TOTAL_CAP,
    bootstrap_stage_budgets,
)

__all__ = ["LadderRecordingTransport", "make_client"]


class LadderRecordingTransport:
    """Transport factory that records the socket budget it was built with."""

    instances: list["LadderRecordingTransport"] = []

    def __init__(self, base_url: str, timeout: float = 60.0):
        self.timeout = timeout
        self.calls: list[tuple[str, str]] = []
        type(self).instances.append(self)

    # -- _Transport surface -------------------------------------------------

    def request(self, method: str, path: str, body=None):
        self.calls.append((method, path))
        if method == "POST" and path.startswith("/session"):
            # Cold-directory bootstrap observed in the incident: 63.7s inside
            # the create call. The assertion is on the budget, not the wall
            # clock — a test must never sleep the incident duration.
            return 200, '{"id": "ses_colddir_1"}'
        return 200, "{}"


def make_client(**kwargs):
    oc._reset_server_singleton()
    LadderRecordingTransport.instances.clear()
    client = oc.OpenCodeClient(
        persistent_session=True,
        session_id="handle-1",
        session_name="Hermes test",
        acp_cwd="/tmp",
        transport_factory=lambda cwd, timeout=60.0: LadderRecordingTransport(
            "http://unit", timeout=timeout
        ),
        **kwargs,
    )
    return client


def test_start_passes_ladder_ceiling_to_create_transport():
    """Fresh start: the create POST's socket budget is the ladder total."""
    stages = bootstrap_stage_budgets(BOOTSTRAP_TOTAL_CAP)
    assert tuple(stages) == BOOTSTRAP_STAGE_LADDER  # 30, 90, 240
    client = make_client()
    client.start(timeout=BOOTSTRAP_TOTAL_CAP, stages=stages)
    transport = LadderRecordingTransport.instances[-1]
    # RED pre-fix: transport.timeout was the _UrllibTransport default 60.0 —
    # strictly below the observed 63.7s cold bootstrap.
    assert transport.timeout >= sum(stages), transport.timeout
    assert transport.calls[0] == ("POST", "/session?directory=%2Ftmp")


def test_start_ladder_total_hard_capped():
    """A caller budget beyond the cap still caps the transport budget."""
    client = make_client()
    client.start(timeout=1800.0, stages=bootstrap_stage_budgets(1800.0))
    transport = LadderRecordingTransport.instances[-1]
    # The ladder itself stops at 30+90+240=360 regardless of a larger caller
    # budget; the transport budget follows the ladder total and never
    # exceeds BOOTSTRAP_TOTAL_CAP.
    assert transport.timeout == sum(BOOTSTRAP_STAGE_LADDER)
    assert transport.timeout <= BOOTSTRAP_TOTAL_CAP
    assert transport.timeout < 1800.0


def test_resume_fence_get_uses_ladder_budget():
    """Persisted native id: the fence GET rides the same raised budget."""
    stages = bootstrap_stage_budgets(600.0)
    client = make_client()
    client.native_session_id = "ses_persisted_1"
    out = client.start(timeout=600.0, stages=stages)
    transport = LadderRecordingTransport.instances[-1]
    assert out == {"sessionId": "ses_persisted_1"}
    assert transport.calls[0][0] == "GET"
    assert transport.timeout >= sum(stages)


def test_legacy_start_without_stages_keeps_default_above_flat_60():
    """No ladder supplied: budget must still exceed the old flat 60s kill."""
    client = make_client()
    client.start(timeout=30.0)
    transport = LadderRecordingTransport.instances[-1]
    assert transport.timeout > 60.0
