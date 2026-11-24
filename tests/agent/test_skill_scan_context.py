"""Scan-context foundation tests (finding f8c3e3602c81, plan U1/U2).

Pins the per-invocation scan-context contract:

* ``compute_ownership_roots()`` resolves exactly what ``is_external_skill_path``
  resolves per call, so the batch (``ownership_roots=``) verdicts are identical
  to the default ones — including with external dirs, trusted project dirs and
  discovery off.
* ``_build_scan_context()``'s name->dir index replicates ``_find_skill_dir``'s
  winner semantics (same sorted walk, first match wins — duplicate names pick
  the same winner), and ``is_curation_eligible``/``_find_skill_dir`` answer
  identically with and without a ctx on a mixed fixture tree.
"""

import os
from unittest.mock import patch

import pytest

SKILL_MD = "---\nname: {name}\ndescription: fixture skill {name}\n---\n\n# {name}\n"


def _make_skill(base, name, *, text_name=None):
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD.format(name=text_name or name))
    return skill_dir


@pytest.fixture
def hermes_home(tmp_path):
    home = tmp_path / ".hermes"
    (home / "skills").mkdir(parents=True)
    return home


@pytest.fixture
def external_dir(tmp_path):
    ext = tmp_path / "external-skills"
    ext.mkdir()
    return ext


class TestComputeOwnershipRoots:
    def test_matches_per_call_resolution_with_external_dirs(self, hermes_home, external_dir):
        (hermes_home / "config.yaml").write_text(f"skills:\n  external_dirs:\n    - {external_dir}\n")
        with patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}):
            from agent.skill_utils import compute_ownership_roots, get_external_skills_dirs, get_project_skills_dirs
            expected = [*get_external_skills_dirs(), *get_project_skills_dirs()]
            assert list(compute_ownership_roots()) == expected

    def test_trusted_project_dirs_included(self, hermes_home, tmp_path, monkeypatch):
        project = tmp_path / "my-project"
        project_skills = project / ".hermes" / "skills"
        project_skills.mkdir(parents=True)
        (project / ".git").write_text("gitdir: /elsewhere\n")  # worktree-style marker (home_io_guard-safe)
        (project / "workfile.txt").write_text("x")
        (hermes_home / "config.yaml").write_text(
            f"skills:\n  trusted_project_dirs:\n    - {project}\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        monkeypatch.chdir(project)
        from agent.skill_utils import compute_ownership_roots
        assert project_skills.resolve() in compute_ownership_roots()

    def test_project_discovery_off_excludes_project_dirs(self, hermes_home, tmp_path, monkeypatch):
        project = tmp_path / "my-project"
        (project / ".hermes" / "skills").mkdir(parents=True)
        (project / ".git").write_text("gitdir: /elsewhere\n")
        (hermes_home / "config.yaml").write_text(
            f"skills:\n  project_discovery: false\n  trusted_project_dirs:\n    - {project}\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        monkeypatch.chdir(project)
        from agent.skill_utils import compute_ownership_roots
        assert compute_ownership_roots() == ()

    def test_no_config_degrades_to_empty(self, hermes_home):
        with patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}):
            from agent.skill_utils import compute_ownership_roots
            assert compute_ownership_roots() == ()


class TestIsExternalSkillPathWithRoots:
    def test_batch_verdicts_match_default(self, hermes_home, external_dir):
        ext_skill = _make_skill(external_dir, "ext-skill")
        local_skill = _make_skill(hermes_home / "skills", "local-skill")
        unrelated = hermes_home / "notes" / "a.txt"
        (hermes_home / "config.yaml").write_text(f"skills:\n  external_dirs:\n    - {external_dir}\n")
        with patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}):
            from agent.skill_utils import compute_ownership_roots, is_external_skill_path
            roots = compute_ownership_roots()
            for path in (ext_skill / "SKILL.md", local_skill / "SKILL.md", unrelated, ext_skill):
                assert is_external_skill_path(path, ownership_roots=roots) == is_external_skill_path(path)


class TestScanContextIndexAndEligibility:
    @pytest.fixture
    def tree(self, hermes_home, external_dir, tmp_path):
        """Mixed fixture: managed + unmanaged + duplicate-name + external-mounted-under-local."""
        skills = hermes_home / "skills"
        _make_skill(skills, "alpha")                      # unmanaged (no record)
        _make_skill(skills, "beta")                       # managed via created_by
        _make_skill(skills, "dup-a", text_name="dup")     # duplicate name, sorts first
        (skills / "nested" / "dup-b").mkdir(parents=True, exist_ok=True)
        (skills / "nested" / "dup-b" / "SKILL.md").write_text(SKILL_MD.format(name="dup"))
        _make_skill(skills / "ext-mounted", "extmounted")  # external dir mounted under local tree
        _make_skill(external_dir, "ext-skill")
        (hermes_home / "config.yaml").write_text(f"skills:\n  external_dirs:\n    - {skills / 'ext-mounted'}\n")
        import json
        (skills / ".usage.json").write_text(json.dumps({"beta": {"created_by": "agent", "state": "active"}}))
        return hermes_home

    def test_local_dirs_winner_matches_find_skill_dir(self, tree):
        with patch.dict(os.environ, {"HERMES_HOME": str(tree)}):
            from tools.skill_usage import _build_scan_context, _find_skill_dir
            ctx = _build_scan_context()
            for name in ("alpha", "beta", "dup"):
                assert ctx.local_dirs[name] == _find_skill_dir(name), name
            # duplicate name: sorted-first winner (dup-a), not nested/dup-b
            assert ctx.local_dirs["dup"].name == "dup-a"
            # external-mounted-under-local never enters the index
            assert "extmounted" not in ctx.local_dirs

    def test_ctx_eligibility_matches_default(self, tree):
        with patch.dict(os.environ, {"HERMES_HOME": str(tree)}):
            from tools.skill_usage import _build_scan_context, is_curation_eligible, read_skill_name
            ctx = _build_scan_context()
            skills = tree / "skills"
            checked = 0
            for skill_md in skills.rglob("SKILL.md"):
                fm_name = read_skill_name(skill_md, fallback=skill_md.parent.name)
                assert is_curation_eligible(fm_name, skill_md, ctx=ctx) == is_curation_eligible(fm_name, skill_md)
                checked += 1
            assert checked >= 5

    def test_unmanaged_and_curated_reports_shape(self, tree):
        with patch.dict(os.environ, {"HERMES_HOME": str(tree)}):
            from tools.skill_usage import unmanaged_report, curated_report
            unmanaged = {row["name"] for row in unmanaged_report()}
            curated = {row["name"] for row in curated_report()}
            assert "alpha" in unmanaged and "dup" in unmanaged
            assert "beta" not in unmanaged and "beta" in curated
            assert "extmounted" not in unmanaged  # external-mounted: not curation-eligible
            assert "ext-skill" not in unmanaged and "ext-skill" not in curated
