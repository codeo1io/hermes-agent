"""The TUI server-state finalizer must survive a partially initialized module.

``tests/conftest.py::_reset_tui_gateway_server_state`` runs after every test.
If a test (or a thread it spawned) is still importing ``tui_gateway.server``
when the test ends — a circular import leaves the module object in
``sys.modules`` with only the attributes defined so far — the finalizer used
to read ``mod._sessions`` directly and crash with ``AttributeError``,
poisoning an otherwise passing file (observed as a teardown ERROR on
``test_kanban_resume_guard.py`` in CI and on ``main`` itself). A module that
has not defined ``_sessions`` yet has no live sessions to close; the only
correct behavior is to skip.
"""

import sys
import types

import pytest

from tests.conftest import _teardown_tui_server_sessions

pytestmark = pytest.mark.usefixtures("_isolate_hermes_home")


def test_finalizer_skips_partial_module_without_sessions(monkeypatch):
    partial = types.ModuleType("tui_gateway.server")
    # A partially initialized module: imported into sys.modules but the
    # module body has not reached the ``_sessions`` assignment yet.
    assert not hasattr(partial, "_sessions")
    monkeypatch.setitem(sys.modules, "tui_gateway.server", partial)
    # The autouse ``_reset_tui_gateway_server_state`` fixture may still see
    # this module at teardown (a real in-flight import is never monkeypatched
    # away); it must not raise AttributeError. RED on the unguarded read.


def test_teardown_helper_closes_fully_initialized_module():
    complete = types.ModuleType("tui_gateway.server")
    closed = []

    def _close_session_by_id(sid, end_reason=None):
        closed.append((sid, end_reason))

    complete._close_session_by_id = _close_session_by_id
    complete._sessions = {"sid": object()}
    _teardown_tui_server_sessions(complete)
    assert closed == [("sid", "test_cleanup")]


def test_teardown_helper_ignores_sessions_test_double():
    double = types.ModuleType("tui_gateway.server")
    double._sessions = "not-a-dict"  # replaced by a test double
    # Must not raise and must not iterate the non-dict.
    _teardown_tui_server_sessions(double)


def test_teardown_helper_skips_partial_module_without_sessions():
    partial = types.ModuleType("tui_gateway.server")
    assert not hasattr(partial, "_sessions")
    # Must not raise on a module that never defined ``_sessions``.
    _teardown_tui_server_sessions(partial)
