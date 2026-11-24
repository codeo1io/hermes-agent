"""Deterministic IO/call-budget regression tests for the curator skill scans.

Pins the failure class behind finding f8c3e3602c81 (rc=124 probe timeouts):
the pre-fix scan re-resolved config and re-read every SKILL.md once per
candidate — O(N x N) reads and thousands of config loads per invocation.
Wall-clock assertions flap exactly when the fleet is busiest, so the class is
pinned with IO/call BUDGETS instead:

* ``read_skill_name`` (the SKILL.md read path) <= 2N + 8 for an N-skill tree
  (one listing pass + one index pass; the pre-fix loop was N + N*N).
* ``_load_raw_config`` entries <= 16 per invocation (post-fix: a handful of
  cache-hit entries; pre-fix on a real tree: 9,041 per invocation).
"""

import json
import os
from unittest.mock import patch

import pytest

SKILL_MD = "---\nname: {name}\ndescription: budget fixture skill {name}\n---\n\n# {name}\n"

N_SKILLS = 40
N_MANAGED = 10
READ_BUDGET = 2 * N_SKILLS + 8
CONFIG_LOAD_BUDGET = 16


@pytest.fixture
def budget_env(tmp_path, monkeypatch):
    """Temp HERMES_HOME with 40 local skills, 10 carrying created_by markers."""
    home = tmp_path / ".hermes"
    skills = home / "skills"
    skills.mkdir(parents=True)
    usage = {}
    for i in range(N_SKILLS):
        name = f"skill-{i:02d}"
        d = skills / name
        d.mkdir()
        (d / "SKILL.md").write_text(SKILL_MD.format(name=name))
        if i < N_MANAGED:
            usage[name] = {"created_by": "agent", "state": "active"}
    (skills / ".usage.json").write_text(json.dumps(usage))
    (home / "config.yaml").write_text("skills: {}\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return home


def _counted_calls(module, attr):
    calls = {"n": 0}
    original = getattr(module, attr)

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    return counting, calls


class TestScanBudgets:
    def test_unmanaged_scan_within_read_and_config_budgets(self, budget_env):
        import agent.skill_utils as skill_utils
        import tools.skill_usage as skill_usage

        read_fn, reads = _counted_calls(skill_usage, "read_skill_name")
        load_fn, loads = _counted_calls(skill_utils, "_load_raw_config")
        with patch.object(skill_usage, "read_skill_name", read_fn), \
                patch.object(skill_utils, "_load_raw_config", load_fn):
            rows = skill_usage.unmanaged_report()
        assert len(rows) == N_SKILLS - N_MANAGED, "fixture classification sanity"
        assert reads["n"] <= READ_BUDGET, (
            f"SKILL.md reads blew the budget: {reads['n']} > {READ_BUDGET} "
            "(the per-candidate re-walk regression is back)"
        )
        assert loads["n"] <= CONFIG_LOAD_BUDGET, (
            f"raw-config loads blew the budget: {loads['n']} > {CONFIG_LOAD_BUDGET} "
            "(the per-candidate root re-resolution regression is back)"
        )

    def test_curated_scan_within_budgets(self, budget_env):
        import agent.skill_utils as skill_utils
        import tools.skill_usage as skill_usage

        read_fn, reads = _counted_calls(skill_usage, "read_skill_name")
        load_fn, loads = _counted_calls(skill_utils, "_load_raw_config")
        with patch.object(skill_usage, "read_skill_name", read_fn), \
                patch.object(skill_utils, "_load_raw_config", load_fn):
            rows = skill_usage.curated_report()
        assert len(rows) == N_MANAGED, "fixture classification sanity"
        assert reads["n"] <= READ_BUDGET and loads["n"] <= CONFIG_LOAD_BUDGET

    def test_usage_report_within_budgets(self, budget_env):
        import agent.skill_utils as skill_utils
        import tools.skill_usage as skill_usage

        read_fn, reads = _counted_calls(skill_usage, "read_skill_name")
        load_fn, loads = _counted_calls(skill_utils, "_load_raw_config")
        with patch.object(skill_usage, "read_skill_name", read_fn), \
                patch.object(skill_utils, "_load_raw_config", load_fn):
            rows = skill_usage.usage_report()
        assert len(rows) >= N_SKILLS, "every on-disk skill appears"
        assert reads["n"] <= READ_BUDGET + N_SKILLS, (
            "usage_report may walk once for names; beyond that the re-walk "
            f"regression is back: {reads['n']}"
        )
        assert loads["n"] <= CONFIG_LOAD_BUDGET

    def test_empty_tree_within_budgets(self, tmp_path, monkeypatch):
        home = tmp_path / ".hermes"
        (home / "skills").mkdir(parents=True)
        (home / "config.yaml").write_text("skills: {}\n")
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        import agent.skill_utils as skill_utils
        import tools.skill_usage as skill_usage

        load_fn, loads = _counted_calls(skill_utils, "_load_raw_config")
        with patch.object(skill_utils, "_load_raw_config", load_fn):
            assert skill_usage.unmanaged_report() == []
        assert loads["n"] <= CONFIG_LOAD_BUDGET
