"""Staged start-handshake budgets for native delegate sessions.

Root cause family: the A4 continuity loop (finding 567c6f06838d). The delegate
start handshake waited on a FIXED 30s wall clock. Under host load (fleet
dispatch bursts, load average 17–26) a healthy pi child regularly took longer
than 30s to answer its first ``get_state`` — the handshake timed out, the
caller re-spawned another Node process, and the re-spawn herd amplified the
very load that caused the timeouts. Emergency continuity repairs then re-armed
the prevention contract 1,458 times because the underlying capability kept
failing the same way.

Two coupled fixes live here, both pure (no I/O, no env vars, no config keys —
the work order's ``timeout_seconds`` is the real budget):

- a STAGE LADDER for handshake waits: wait 30s (the old fast wedge-fail
  probe, preserved as stage 1), then 90s, then 240s — the caller checks
  process liveness between stages, so a wedged child still fails at 30s
  while a slow-but-alive one gets room to answer. The ladder is clipped by
  the caller's total budget and hard-capped well under the phase budget.
- a JITTERED RESPAWN PAUSE, applied only immediately before RE-SPAWNING a
  new native process (same-id retry / fresh-native recovery). Waiting
  longer inside one live session adds no load; a new Node spawn does — the
  pause de-synchronizes the herd exactly at that boundary.
"""

from __future__ import annotations

import random

__all__ = [
    "BOOTSTRAP_STAGE_LADDER",
    "BOOTSTRAP_TOTAL_CAP",
    "RESPAWN_PAUSE_RANGE",
    "bootstrap_stage_budgets",
    "respawn_pause",
]

# Base wait ladder for one native RPC handshake. Stage 1 preserves the
# historical fast wedge-fail bound; later stages give a slow-but-alive child
# room under load. Monotone non-decreasing by construction.
BOOTSTRAP_STAGE_LADDER: tuple[float, ...] = (30.0, 90.0, 240.0)

# Hard ceiling for the handshake wall clock regardless of the caller's
# (possibly much larger) turn budget: staging must never become a new way to
# hang a delegate slot. 600s ≪ the 1800s phase budget.
BOOTSTRAP_TOTAL_CAP = 600.0

# Pause range before RE-SPAWNING a native process (seconds).
RESPAWN_PAUSE_RANGE = (0.5, 2.0)


def bootstrap_stage_budgets(total_budget: float) -> list[float]:
    """Clip :data:`BOOTSTRAP_STAGE_LADDER` to ``total_budget``.

    The returned list is the base-ladder prefix with (at most) the final
    stage truncated to the remainder: e.g. 45 -> ``[30, 15]``, 10 -> ``[10]``,
    600 -> ``[30, 90, 240]``. Never empty — a degenerate (<= 0) budget yields
    a single immediate stage so the caller still issues exactly one bounded
    call — and never exceeds the input.
    """
    remaining = float(total_budget)
    stages: list[float] = []
    for stage in BOOTSTRAP_STAGE_LADDER:
        if remaining <= 0.0:
            break
        take = min(float(stage), remaining)
        stages.append(take)
        remaining -= take
    if not stages:
        return [0.0]
    return stages


def respawn_pause(rng: random.Random) -> float:
    """Jittered pause (seconds) before RE-SPAWNING a native pi process.

    Uniform over :data:`RESPAWN_PAUSE_RANGE`. Takes the rng as an argument so
    callers (and tests) can inject a seeded ``random.Random``.
    """
    low, high = RESPAWN_PAUSE_RANGE
    return low + rng.random() * (high - low)
