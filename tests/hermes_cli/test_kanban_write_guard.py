"""#69283: kanban write guard prevents tests from writing to real ~/.hermes."""

from __future__ import annotations

import pytest

from hermes_cli import kanban_db
from hermes_cli import kanban_db_connect as kbc


def test_connect_succeeds_under_test_home(tmp_path, monkeypatch):
    """When HERMES_HOME is a temp dir, kanban connect succeeds normally."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    conn = kbc.connect()
    try:
        assert str(kanban_db.kanban_db_path()).startswith(str(home))
    finally:
        conn.close()


def test_connect_raises_when_kanban_home_is_real_root(monkeypatch):
    """When kanban paths resolve to the REAL root, connect raises RuntimeError."""
    import tests.conftest as _conftest

    monkeypatch.setattr(
        kanban_db, "kanban_home", lambda: _conftest._REAL_KANBAN_ROOT
    )
    monkeypatch.setattr(
        kanban_db,
        "kanban_db_path",
        lambda board=None: _conftest._REAL_KANBAN_ROOT / "kanban.db",
    )
    # Wave-9 (2026-09-18): the connect-time choke in kanban_db_connect fires
    # BEFORE the conftest wrapper, so the message is the choke's — either guard
    # refusing the production board is the contract; match both spellings.
    with pytest.raises(RuntimeError, match="(write_guard|test-isolation guard)"):
        kbc.connect()


def test_connect_raises_for_explicit_db_path_under_real_root():
    """Explicit db_path pointing under the real root is also refused."""
    import tests.conftest as _conftest

    with pytest.raises(RuntimeError, match="(write_guard|test-isolation guard)"):
        kbc.connect(_conftest._REAL_KANBAN_ROOT / "kanban.db")
