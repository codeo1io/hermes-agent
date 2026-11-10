"""C6 prerequisite — the upgrade lane must refuse a stale release series, never run it silently.

The 2026-10-04 e2e-upgrade run (37226448600) was the first to execute after the fork's
re-parent: its clone fetched none of the fork's ``v2026.9.*`` tags, so
``git describe --tags --abbrev=0 HEAD~1`` parked main at ``v2026.8.18`` (0.20.4, six weeks
stale) and every leg upgraded a tree that predates the layout refactor under test — the torn
and lock-only legs died on ``from hermes_cli._startup_fast import
is_desktop_ssh_backend_argv`` (a symbol the old ``_startup_fast`` lacks), the clean legs on a
known entrypoint regression, ~11 runner-minutes per attempt for zero signal about HEAD.

These cells pin the prerequisite layer (``_stale_base_reason``) that now fails the module the
moment the resolved N-1 is from another release series than HEAD — the exact defect shape —
while leaving every legitimate configuration alone.
"""

from __future__ import annotations

import pytest

from tests.e2e.core.upgrade import test_upgrade_path as up


def _series(tag: str) -> str | None:
    return up._release_series(tag)


@pytest.mark.parametrize("tag,series", [
    ("v2026.9.24", "2026.9"),
    ("v2026.10.1", "2026.10"),
    ("v2026.9.11", "2026.9"),
    ("v2026.8.18", "2026.8"),
    # The fork's own SemVer scheme (minted from 2026-11-05) is a first-class series.
    ("v0.23.0", "0.23"),
    ("v0.22.4", "0.22"),
    ("v1.0.0", "1.0"),
    # Not release tags: describe can land on any annotated tag.
    ("v0.21.4+canary.20261004T084456Z", None),
    ("rc.35-v0.21.5", None),
    ("e2e-upgrade-base", None),
    ("v2026.9.24-rc1", None),
    ("v0.23.0-rc1", None),
])
def test_release_series_extraction(tag, series):
    assert _series(tag) == series


def test_same_series_base_is_allowed(monkeypatch):
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.9.24",
                                                      base="b" * 40))
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
    assert up._stale_base_reason() is None


def test_scheme_handoff_head_with_calver_base_is_allowed(monkeypatch):
    """The live 2026-11-10 shape: HEAD carries the fork's SemVer (v0.23.0 series 0.23)
    while the newest CalVer release (v2026.9.24) predates the scheme handoff.

    The guard's job is to catch a checkout MISSING its tags (HEAD describes to None
    or an unrelated series because the fork never fetched them) — not to reject the
    legitimate boundary where the fork minted a new scheme after its last CalVer
    release. N-1 CalVer + HEAD SemVer is exactly the real upgrade this lane must
    exercise: updating a v2026.9.x install to a v0.23.x tree.
    """
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.9.24",
                                                      base="b" * 40))
    monkeypatch.delenv("HERMES_E2E_UPGRADE_BASE", raising=False)
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v0.23.0")
    assert up._stale_base_reason() is None


def test_stale_series_base_fails_with_tag_advice(monkeypatch):
    """The exact live defect: base v2026.8.18 while HEAD's own series is 2026.9."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
    reason = up._stale_base_reason()
    assert reason is not None
    assert "v2026.8.18" in reason and "fetch them" in reason


def test_no_dated_tag_on_head_still_guards(monkeypatch):
    """HEAD describing to no release tag cannot vouch for any base series."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "e2e-upgrade-base")
    assert up._stale_base_reason() is not None


def test_unrelated_same_scheme_series_still_fails(monkeypatch):
    """Both ends carry SemVer release tags but from unrelated series: not a handoff,
    not the same series — the checkout cannot vouch for the base."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v0.13.2",
                                                      base="b" * 40))
    monkeypatch.delenv("HERMES_E2E_UPGRADE_BASE", raising=False)
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v0.23.0")
    reason = up._stale_base_reason()
    assert reason is not None and "fetch them" in reason


def test_explicit_same_series_base_allowed(monkeypatch):
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.9.14",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "v2026.9.14")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
    assert up._stale_base_reason() is None


def test_explicit_cross_series_base_fails(monkeypatch):
    """The override replays an upgrade within one series; crossing series blind stays an error."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "v2026.8.18")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
    reason = up._stale_base_reason()
    assert reason is not None
    assert "HERMES_E2E_UPGRADE_BASE" in reason


def test_explicit_base_on_untagged_head_allowed(monkeypatch):
    """No release tag describes HEAD: the explicit override is the only escape, keep it working."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "v2026.8.18")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v0.21.4+canary.20261004T084456Z")
    assert up._stale_base_reason() is None


def test_module_fails_prereq_on_stale_base(monkeypatch, tmp_path):
    """The fixture path: the module's autouse prerequisite fails on a stale N-1."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
    reason = up._stale_base_reason()
    assert reason is not None
    # The autouse fixture's fail path is one call away; prove the wiring reads the same verdict.
    import inspect
    src = inspect.getsource(up._upgrade_prerequisites)
    assert "pytest.fail(stale)" in src, "prerequisite fixture does not fail on a stale base"
