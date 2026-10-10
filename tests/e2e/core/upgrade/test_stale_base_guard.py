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
    # Not dated-release tags: describe can land on any annotated tag.
    ("v0.21.4+canary.20261004T084456Z", None),
    ("rc.35-v0.21.5", None),
    ("e2e-upgrade-base", None),
    ("v2026.9.24-rc1", None),
])
def test_release_series_extraction(tag, series):
    assert _series(tag) == series


def test_same_series_base_is_allowed(monkeypatch):
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.9.24",
                                                      base="b" * 40))
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
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
    """HEAD describing to no dated release tag cannot vouch for any base series."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v0.21.4")
    assert up._stale_base_reason() is not None


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
    """No dated tag describes HEAD: the explicit override is the only escape, keep it working."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "v2026.8.18")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v0.21.4")
    assert up._stale_base_reason() is None


def test_module_fails_prereq_on_stale_base(monkeypatch, tmp_path):
    """The fixture path: the module's autouse prerequisite fails on a stale N-1."""
    monkeypatch.setattr(up, "_refs", lambda: up._Refs(head="h" * 40, base_tag="v2026.8.18",
                                                      base="b" * 40))
    monkeypatch.setenv("HERMES_E2E_UPGRADE_BASE", "")
    monkeypatch.setattr(up, "_git", lambda *a, **k: "v2026.9.24")
    reason = up._stale_base_reason()
    assert reason is not None
    # Behavioral wiring proof: the autouse fixture is a plain zero-arg function —
    # call it directly and assert it turns the same verdict into a hard FAIL.
    with pytest.raises(pytest.fail.Exception, match="another series"):
        # The module-level name is pytest's FixtureFunctionDefinition (direct calls
        # are rejected); __wrapped__ (set by functools.update_wrapper) is the raw
        # zero-arg prerequisite body the autouse wiring schedules for this module.
        up._upgrade_prerequisites.__wrapped__()
