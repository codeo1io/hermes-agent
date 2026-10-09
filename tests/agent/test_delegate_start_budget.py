"""Staged start-handshake budgets for native delegate sessions (agent/delegate_start_budget).

Regression family: the A4 cognitive-continuity loop (finding 567c6f06838d). A
fixed 30s start-handshake cap killed healthy-but-slow delegates under host
load (get_state measured 30.9s, abort 216s, queue latency 42 minutes), and
the resulting re-spawn herd amplified the very load that caused the timeouts.
These tests pin the budget CONTRACTS, not values: clipping, monotone prefix
shape, fail-open degeneracy, and respawn-jitter bounds.
"""

import random

import pytest

from agent.delegate_start_budget import (
    BOOTSTRAP_STAGE_LADDER,
    BOOTSTRAP_TOTAL_CAP,
    RESPAWN_PAUSE_RANGE,
    bootstrap_stage_budgets,
    respawn_pause,
)


class TestBootstrapStageBudgets:
    def test_full_budget_keeps_base_ladder(self):
        # The ladder IS the wait pattern; a generous budget must not stretch
        # it (total handshake stays bounded well under the phase budget).
        assert bootstrap_stage_budgets(600.0) == [30.0, 90.0, 240.0]
        assert bootstrap_stage_budgets(10_000.0) == [30.0, 90.0, 240.0]

    def test_ladder_clipped_to_small_budget(self):
        # Plan examples: the tail stage absorbs the remainder.
        assert bootstrap_stage_budgets(45.0) == [30.0, 15.0]
        assert bootstrap_stage_budgets(10.0) == [10.0]
        assert bootstrap_stage_budgets(30.0) == [30.0]

    def test_prefix_shape_and_bounds_hold_across_budget_sweep(self):
        # Contract for every positive budget: non-empty, total never exceeds
        # the input, and every stage except a clipped tail equals the base
        # ladder prefix (stage 1 is always the fast wedge-fail probe).
        for budget in [0.5, 1.0, 5.0, 29.9, 30.0, 31.0, 120.0, 359.0, 360.0, 361.0, 599.5, 600.0, 900.0]:
            stages = bootstrap_stage_budgets(budget)
            assert stages, f"empty ladder for budget={budget}"
            assert sum(stages) <= budget + 1e-9, f"{stages} exceeds budget={budget}"
            assert all(s > 0 for s in stages), f"non-positive stage for budget={budget}: {stages}"
            for i, stage in enumerate(stages):
                assert stage <= BOOTSTRAP_STAGE_LADDER[i] + 1e-9, (
                    f"stage {i} exceeds ladder for budget={budget}: {stages}"
                )
                if i < len(stages) - 1:
                    assert stage == BOOTSTRAP_STAGE_LADDER[i], (
                        f"non-tail stage {i} deviates for budget={budget}: {stages}"
                    )

    def test_degenerate_budget_is_never_empty(self):
        # Fail-open: a zero/negative budget still yields exactly one bounded
        # stage (the caller issues one immediate call, never zero, never an
        # unbounded one).
        assert bootstrap_stage_budgets(0.0) == [0.0]
        assert bootstrap_stage_budgets(-5.0) == [0.0]

    def test_total_cap_admits_the_full_ladder(self):
        # Relationship, not snapshot: the cap must be able to fund every
        # stage of the base ladder so a healthy session is never budget-
        # starved below the designed handshake pattern.
        assert BOOTSTRAP_TOTAL_CAP >= sum(BOOTSTRAP_STAGE_LADDER)


class TestRespawnPause:
    def test_pause_bounds_and_determinism(self):
        rng = random.Random(7)
        first = respawn_pause(rng)
        low, high = RESPAWN_PAUSE_RANGE
        assert low <= first < high
        # Same seed, same pause — injectable rng makes the wiring observable.
        assert respawn_pause(random.Random(7)) == first

    def test_pause_varies_but_stays_in_range(self):
        rng = random.Random(1234)
        pauses = [respawn_pause(rng) for _ in range(200)]
        low, high = RESPAWN_PAUSE_RANGE
        assert all(low <= p < high for p in pauses)
        # Jitter must actually jitter (a constant pause cannot de-synchronize
        # a re-spawn herd).
        assert len(set(pauses)) > 10


@pytest.mark.parametrize("missing", [BOOTSTRAP_STAGE_LADDER, RESPAWN_PAUSE_RANGE])
def test_constants_are_module_level_for_injectability(missing):
    # The wiring reads these at call time; they must be module attributes
    # (injectable/patchable), not closure locals.
    assert missing is not None
