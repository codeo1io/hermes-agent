"""Regression tests for the 2026-09-17 kanban fixture-leak wave.

Two defects collaborated to write dispatcher-test fixture rows (``owner`` /
``child`` / ``a0``–``a4`` / ``b0``–``b2``) into the LIVE ``~/.hermes/kanban.db``:

1. ``hermes_constants.get_default_hermes_root()`` collapsed a sandboxed
   ``HERMES_HOME`` parked under the native home (pytest ``--basetemp
   ~/.hermes/tmp/...``) back to the PRODUCTION root, so every kanban path
   resolved to the live board.
2. The conftest ``_kanban_write_guard`` only patches modules already in
   ``sys.modules`` at fixture time — the FIRST test in a file that lazily
   imports ``hermes_cli.kanban_db`` inside its body wrote before any patch
   existed.

The choke-point guard ``kanban_db_connect._ensure_test_isolation`` now arms on
env/ancestry test signals and refuses production board paths regardless of
patch timing.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# get_default_hermes_root: sandbox-under-root no longer collapses
# ---------------------------------------------------------------------------


def test_default_root_keeps_sandboxed_home_under_native_home(monkeypatch, tmp_path):
    from hermes_constants import get_default_hermes_root

    # tmp_path here may itself live under the real ~/.hermes (conductor
    # delegate TMPDIR): the sandbox is NOT a profile home, so it must be
    # treated as the root itself instead of collapsing to the native home.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "sandbox"))
    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)
    root = get_default_hermes_root()
    assert root == Path(tmp_path / "sandbox")


def test_default_root_profile_home_still_maps_to_parent(monkeypatch, tmp_path):
    from hermes_constants import get_default_hermes_root

    profiles = tmp_path / "hermes" / "profiles" / "worker"
    profiles.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profiles))
    root = get_default_hermes_root()
    assert root == tmp_path / "hermes"


def test_default_root_dot_profile_home_keeps_existing_mapping(monkeypatch, tmp_path):
    """Dotted profile dirs (<root>/profiles/.name) keep the pre-existing
    grandparent mapping (ValueError branch) — this test pins it so the
    sandbox-under-root change cannot silently alter it."""
    from hermes_constants import get_default_hermes_root

    profiles = tmp_path / "hermes" / "profiles" / ".hidden"
    profiles.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profiles))
    root = get_default_hermes_root()
    assert root == tmp_path / "hermes"


# ---------------------------------------------------------------------------
# kanban choke-point guard: production board refused from a test context,
# regardless of conftest patch timing
# ---------------------------------------------------------------------------


@pytest.fixture()
def _pytest_context(monkeypatch, tmp_path):
    """Exercise the production-path guard against a synthetic, isolated root.

    A CI runner's real home can itself be a registered pytest sandbox. Using
    that home here makes the guard correctly allow the path and the test
    incorrectly fail (or touch the runner's actual state). Keep the security
    predicate real while replacing only the platform root and sandbox lookup.
    """
    synthetic_root = tmp_path / "synthetic-production-home" / ".hermes"
    synthetic_root.mkdir(parents=True)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_self.py::test_x")
    monkeypatch.setattr(
        "hermes_state_guard._real_platform_state_root", lambda: synthetic_root
    )
    monkeypatch.setattr("hermes_state_guard._path_in_sandbox", lambda _path: False)
    yield


def test_guard_refuses_production_kanban_db(_pytest_context):
    from hermes_state_guard import _real_platform_state_root
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = _real_platform_state_root()
    assert root is not None
    with pytest.raises(RuntimeError, match="test-isolation guard"):
        _ensure_test_isolation(root / "kanban.db")


def test_guard_refuses_production_board_dirs_and_profiles(_pytest_context):
    from hermes_state_guard import _real_platform_state_root
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = _real_platform_state_root()
    assert root is not None
    with pytest.raises(RuntimeError, match="test-isolation guard"):
        _ensure_test_isolation(root / "kanban" / "boards" / "second" / "kanban.db")
    with pytest.raises(RuntimeError, match="test-isolation guard"):
        _ensure_test_isolation(root / "profiles" / "worker" / "kanban.db")


def test_guard_allows_sandboxed_db_under_real_root(_pytest_context, monkeypatch, tmp_path):
    """A scratch directory beneath a platform root is not a production board.

    Model the layout in a temporary root; metadata probes of the actual
    ~/.hermes/tmp directory are forbidden by the hermetic home-I/O guard.
    """
    import hermes_state_guard
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = tmp_path / "synthetic-platform-home" / ".hermes"
    monkeypatch.setattr(hermes_state_guard, "_real_platform_state_root", lambda: root)
    sandbox_db = root / "tmp" / "pytest-something" / ".hermes" / "kanban.db"
    _ensure_test_isolation(sandbox_db)  # must not raise


def test_guard_bypass_env(_pytest_context, monkeypatch):
    from hermes_state_guard import _real_platform_state_root
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = _real_platform_state_root()
    assert root is not None
    monkeypatch.setenv("HERMES_KANBAN_GUARD_BYPASS", "1")
    _ensure_test_isolation(root / "kanban.db")  # must not raise


def test_guard_inert_outside_test_context(monkeypatch):
    from hermes_state_guard import _real_platform_state_root
    from hermes_cli import kanban_db_connect as kbc

    root = _real_platform_state_root()
    assert root is not None
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.delenv("HERMES_TEST_ISOLATION", raising=False)
    # The ancestry signal survives the env deletion by design (it is the
    # belt for children spawned with rebuilt envs) — but THIS test simulates
    # "not a test process", and under run_tests_parallel.py / nested pytest
    # the process tree genuinely has a pytest ancestor, which would flip the
    # guard back on. Neutralize it: the guard is memoised, so patch the
    # module global _in_test_context consults.
    monkeypatch.setattr("hermes_state_guard._PYTEST_ANCESTOR", False)
    # Not memoised in this process yet: without psutil ancestors there is
    # nothing pytest-shaped above us inside the test runner either, so the
    # guard must stay silent and simply return.
    kbc._ensure_test_isolation(root / "kanban.db")  # must not raise


# ---------------------------------------------------------------------------
# Write-boundary choke (2026-09-18 wave 8): write_txn guards externally-opened
# conns too — a raw sqlite3.connect to the live board must not become a write
# path for dispatcher helpers (claim_task / create_task / _set_worker_pid).
# ---------------------------------------------------------------------------


@pytest.mark.allow_real_home_io
def test_write_txn_refuses_raw_conn_to_live_board(_pytest_context):
    """connect() refuses the live board, but a fixture that opens the live DB
    with raw sqlite3.connect and drives kb.create_task goes through
    write_txn — that boundary must refuse as well.

    allow_real_home_io: this test deliberately touches a file under the REAL
    home (an empty placeholder at the live-board path) to prove the CHOKE
    fires before sqlite opens anything. The autouse home-io guard wraps
    sqlite3.connect and refuses the real-home path with its own AssertionError
    BEFORE the choke under test can raise, turning the test into a permanent
    red (2026-10-30 main-red wave). The guard-behavior escape hatch is the
    established mechanism for exactly this shape.
    """
    import sqlite3

    from hermes_state_guard import _real_platform_state_root
    from hermes_cli import kanban_db_connect as kbc

    root = _real_platform_state_root()
    assert root is not None
    with sqlite3.connect(":memory:") as raw:
        monkeypatch.setattr(kbc, "_main_db_file", lambda _conn: str(root / "kanban.db"))
        with pytest.raises(RuntimeError, match="test-isolation guard"):
            with kbc.write_txn(raw):
                pytest.fail("write boundary reached before isolation guard")


def test_main_db_file_reports_isolated_connection_path(tmp_path):
    import sqlite3

    from hermes_cli import kanban_db_connect as kbc

    db = tmp_path / "isolated-kanban.db"
    with sqlite3.connect(db) as raw:
        assert Path(kbc._main_db_file(raw)).resolve() == db.resolve()


def test_registered_real_home_never_bypasses_kanban_guard(_pytest_context, monkeypatch):
    from hermes_state_guard import _real_platform_state_root, pin_sandbox_root
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = _real_platform_state_root()
    assert root is not None
    monkeypatch.setattr("hermes_state_guard._SANDBOX_ROOTS", [])
    pin_sandbox_root(root)
    from hermes_state_guard import _SANDBOX_ROOTS
    assert root not in _SANDBOX_ROOTS
    with pytest.raises(RuntimeError, match="test-isolation guard"):
        _ensure_test_isolation(root / "kanban.db")


def test_guard_refuses_symlink_alias_into_production_board(_pytest_context, monkeypatch, tmp_path):
    """An external alias cannot evade the resolved-path production check."""
    import hermes_state_guard
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = tmp_path / "synthetic-platform-home" / ".hermes"
    root.mkdir(parents=True)
    monkeypatch.setattr(hermes_state_guard, "_real_platform_state_root", lambda: root)
    alias = tmp_path / "outside.db"
    alias.symlink_to(root / "kanban.db")
    with pytest.raises(RuntimeError, match="test-isolation guard"):
        _ensure_test_isolation(alias)


def test_guard_fails_closed_on_resolution_error(_pytest_context, monkeypatch, tmp_path):
    """A metadata guard denying resolution must not silently allow a DB open."""
    import hermes_state_guard
    from hermes_cli.kanban_db_connect import _ensure_test_isolation

    root = tmp_path / "synthetic-platform-home" / ".hermes"
    monkeypatch.setattr(hermes_state_guard, "_real_platform_state_root", lambda: root)
    alias = tmp_path / "unresolvable.db"
    original_resolve = Path.resolve

    def blocked_resolve(path, *args, **kwargs):
        if path == alias:
            raise PermissionError("metadata denied")
        return original_resolve(path, *args, **kwargs)

    with monkeypatch.context() as isolated:
        isolated.setattr(Path, "resolve", blocked_resolve)
        with pytest.raises(RuntimeError, match="cannot resolve DB path"):
            _ensure_test_isolation(alias)


def test_real_platform_state_root_ignores_redirected_home(monkeypatch, tmp_path):
    """Invariant (wave-8 forensics item 1): the deny-root follows the REAL
    home, not the HOME env a test redirected — so the guard keeps matching
    the production board even while HOME points at a sandbox."""
    from hermes_state_guard import _real_platform_state_root

    real = _real_platform_state_root()
    assert real is not None
    monkeypatch.setenv("HOME", str(tmp_path / "sandbox-home"))
    assert _real_platform_state_root() == real, (
        "deny-root must not follow a redirected HOME env"
    )