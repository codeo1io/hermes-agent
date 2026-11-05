"""Syntax guard for ``hermes update``: the files compiled before/after every tree move.

Split out of ``hermes_cli/update_cmd.py`` (code-health FILE_LINES): the critical-file set
and the compile-based validators are self-contained; the update flow only calls them.
"""

from __future__ import annotations

from pathlib import Path

# Compiled before (preflight) and after (post-pull guard, ZIP gate) every tree move. The first rows
# are what the launcher and ``hermes_bootstrap`` import before any application code (review G3);
# test_update_post_pull_syntax_guard derives that set from the real entry paths and pins it here.
CRITICAL_FILES = (
    "hermes_bootstrap.py", "hermes_cli/_parser.py", "hermes_cli/_launchers.py",
    "hermes_cli/_early_recovery.py", "hermes_cli/update_lock.py", "hermes_cli/update_custody.py",
    "hermes_cli/update_handoff.py", "hermes_cli/venv_sync.py", "pm/__init__.py", "pm/environments.py",
    "hermes_cli/main.py", "hermes_cli/config.py", "hermes_cli/__init__.py",
    "hermes_cli/web_server.py", "cli.py", "run_agent.py", "model_tools.py", "toolsets.py",
    "hermes_constants.py")


def validate_python_files_syntax(
    root, relpaths
) -> tuple[bool, str | None, str | None]:
    """Compile *relpaths* under *root* without writing bytecode into the tree."""
    import py_compile
    import tempfile

    root = Path(root)
    with tempfile.TemporaryDirectory(prefix="hermes-syntax-check-") as tmpdir:
        for relpath in relpaths:
            path = root / relpath
            if not path.exists():
                continue
            cfile = Path(tmpdir) / (str(relpath).replace("/", "__") + "c")
            try:
                py_compile.compile(str(path), cfile=str(cfile), doraise=True)
            except py_compile.PyCompileError as exc:
                return False, str(path), str(exc)
            except OSError as exc:
                return False, str(path), f"could not read: {exc}"
    return True, None, None


def validate_critical_files_syntax(root) -> tuple[bool, str | None, str | None]:
    """Compile each file in ``CRITICAL_FILES`` to catch SyntaxErrors.

    These are the files imported on every ``hermes`` startup; if any of them
    has a syntax error (orphan merge-conflict markers, bad ref to a name
    that no longer exists, etc.) the CLI can't bootstrap at all. We validate
    them after a successful ``git pull`` so we can auto-roll-back instead of
    leaving the user with a bricked install.

    The compiled ``.pyc`` is written to a temp directory rather than the
    source tree's ``__pycache__/`` so we don't race with concurrent test
    workers that walk the same dir, and so we don't leave a stale pyc
    behind in production if the next interpreter run picks a different
    Python version. The pyc is discarded on function return either way —
    we only care about the compile-or-not signal.

    Returns ``(ok, failing_path, error_message)``. ``ok=True`` means every
    file parsed cleanly.
    """
    return validate_python_files_syntax(root, CRITICAL_FILES)
