"""Guard-safe ``HERMES_KANBAN_DB`` pinning for kanban tests.

Why (verified 2026-09-15, PR #15 CI): the self-hosted runner's ``TMPDIR`` lives
under the real kanban root, so pytest ``tmp_path`` is INSIDE
``_REAL_KANBAN_ROOT`` and ``tests/conftest.py``'s ``_kanban_write_guard``
refuses every tmp-derived DB path (#69283). ``HERMES_HOME`` never moved the
kanban root anyway (``kanban_home()`` is the native root shared across
profiles), so an unpinned test would write to the REAL ``~/.hermes/kanban.db``.
The sanctioned isolation is the ``HERMES_KANBAN_DB`` env pin — exactly what the
dispatcher injects into worker envs (``hermes_cli/kanban_db_dispatch.py``).
The pinned path must itself live OUTSIDE the real root; when even the system
``TMPDIR`` is inside it, fall back to ``/tmp``.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import tests.conftest as _conftest

_REAL_KANBAN_ROOT: Path = _conftest._REAL_KANBAN_ROOT


def _is_under_real_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(_REAL_KANBAN_ROOT)
    except ValueError:
        return False
    return True


def guard_safe_dir(tmp_path: Path, label: str) -> Path:
    """Writable dir for ``label`` guaranteed outside the real kanban root."""
    cand = tmp_path / label
    if not _is_under_real_root(cand):
        cand.mkdir(parents=True, exist_ok=True)
        return cand  # dev machines: plain tmp_path
    base = Path(tempfile.gettempdir()).resolve()
    if _is_under_real_root(base):
        base = Path("/tmp")  # self-hosted runner: even TMPDIR is under the root
    # Long-lived runner: /tmp persists, so a recycled pid with the same test
    # name would hit exist_ok=True and reopen a PREVIOUS run's DB (init_db()
    # only migrates, never resets). mkdtemp guarantees a fresh, unique dir per
    # process instance even when pids recycle; the pid prefix aids debugging.
    scratch_base = base / "hermes-kanban-test-scratch"
    scratch_base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"pid{os.getpid()}-", dir=str(scratch_base)))
    out = scratch / tmp_path.name / label
    out.mkdir(parents=True, exist_ok=True)
    return out


def pin_kanban_db(monkeypatch, tmp_path: Path, label: str = "kanban") -> Path:
    """Pin ``HERMES_KANBAN_DB`` outside the real root; reset the init cache."""
    from hermes_cli import kanban_db as kb

    pin = guard_safe_dir(tmp_path, label) / "kanban.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(pin))
    kb._INITIALIZED_PATHS.clear()
    return pin
