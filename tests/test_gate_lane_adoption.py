"""The conductor gate-lane adoption contract: only a bare whole-suite run under the gate adopts the canonical runner."""
from __future__ import annotations

import sys
from pathlib import Path

from tests.conftest import _gate_lane_runner_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env(workers="4", **extra):
    return {"CONDUCTOR_LOCAL_VALIDATION_WORKERS": workers, **extra}


def test_bare_admitted_gate_lane_adopts_the_canonical_runner_with_the_granted_budget():
    plan = _gate_lane_runner_plan(_env(), positional_args=(), collect_only=False)
    assert plan is not None
    assert plan["argv"] == ["bash", str(PROJECT_ROOT / "scripts" / "run_tests.sh")]
    assert plan["env"]["HERMES_TEST_WORKERS"] == "4"
    assert plan["env"]["HERMES_PYTHON"] == sys.executable
    assert plan["env"]["HERMES_TEST_GATE_ADOPTED_RUNNER"] == "1"


def test_the_testpaths_default_invocation_is_still_the_whole_suite():
    assert _gate_lane_runner_plan(_env(), positional_args=("tests",), collect_only=False) is not None


def test_path_scoped_collect_only_unadmitted_and_nested_lanes_never_adopt():
    admitted = _env()
    assert _gate_lane_runner_plan(admitted, positional_args=("tests/agent",), collect_only=False) is None
    assert _gate_lane_runner_plan(admitted, positional_args=(), collect_only=True) is None
    assert _gate_lane_runner_plan(_env(workers="pending"), positional_args=(), collect_only=False) is None
    assert _gate_lane_runner_plan(_env(workers="0"), positional_args=(), collect_only=False) is None
    assert _gate_lane_runner_plan({"OTHER": "1"}, positional_args=(), collect_only=False) is None
    assert _gate_lane_runner_plan(
        _env(HERMES_TEST_GATE_ADOPTED_RUNNER="1"), positional_args=(), collect_only=False
    ) is None
