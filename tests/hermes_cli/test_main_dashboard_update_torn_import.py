"""`hermes update` torn-import contract for ``main_dashboard``.

Regression for the install-e2e failure (v2026.8.18 -> HEAD legs, red since
2026-09-13): the pre-update gateway process restarts itself after the tree on
disk is already post-update, so ``hermes_cli.cli_output`` may already sit in
``sys.modules`` WITHOUT the new ``line_input`` symbol while the rest of the
tree is new. ``dashboard_procs._kill_stale_dashboard_processes`` imports
``hermes_cli.main_dashboard`` during that window — a module-scope import of
``line_input`` there made every update auto-restart exit 1.
"""

import importlib
import sys


def test_main_dashboard_imports_with_pre_update_cli_output(monkeypatch):
    cli_output = sys.modules.pop("hermes_cli.cli_output", None)
    try:
        monkeypatch.setitem(
            sys.modules,
            "hermes_cli.cli_output",
            type(sys)("hermes_cli.cli_output"),  # pre-update shape: no line_input
        )
        import hermes_cli.main_dashboard as main_dashboard  # noqa: F401  (import IS the test)
        importlib.reload(main_dashboard)
    finally:
        monkeypatch.undo()
        if cli_output is not None:
            sys.modules["hermes_cli.cli_output"] = cli_output
        else:
            sys.modules.pop("hermes_cli.cli_output", None)
