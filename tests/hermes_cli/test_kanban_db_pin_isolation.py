"""Kanban live-DB pin-isolation regression tests (card t_950d4b99).

Incident: conductor run 30c1df938db6 ran a probe script that ALTERed the live
``~/.hermes/kanban.db`` schema (``tasks.owner``) and wrote 6 probe cards. The
probe redirected ``HERMES_HOME`` to scratch, but ``kanban_home()``
(hermes_cli/kanban_db.py) resolves to ``HERMES_KANBAN_HOME`` else
``get_default_hermes_root()`` — the NATIVE root — so when ``HERMES_HOME`` is a
profile dir under the native root (the normal topology) the kanban root does
NOT move: it is shared across profiles BY DESIGN (a per-profile board would
fork the dispatcher/worker handoff). The sanctioned isolation mechanism for
scratch/probe processes is the ``HERMES_KANBAN_DB`` env pin — exactly what the
dispatcher injects into every worker env (hermes_cli/kanban_db_dispatch.py).

Tests in this file:

* the shared-root topology precondition: HERMES_HOME points elsewhere, yet
  the kanban root and default DB still resolve to the native root;
* the pinned-isolation contract (the guard the incident demanded): with
  ``HERMES_KANBAN_DB`` pinned exactly like the dispatcher pins worker envs,
  connect/init/migration/create/complete stay on the pinned file and the
  shared root's DB stays byte-identical — no rows, no schema drift, not even
  a lock or WAL sidecar beside it;
* the un-pinned control arm: in this topology with NO pin, connect/init/
  create/complete writes DO land in the shared root's ``kanban.db`` — the
  incident replayed on a fake root, so the pinned-isolation test cannot pass
  vacuously (#69283 lineage: a guard must be provably red on the unguarded
  behavior);
* the subprocess probe-replay arm: a CHILD process (env-only isolation, no
  monkeypatch, no in-process pytest guard) in the same topology, protected
  only by the env pin — the exact vector the conftest guard cannot see.

The "live" root in every test is a fake under ``tmp_path``, never the
operator's real ``~/.hermes``; the autouse ``_kanban_write_guard`` in
tests/conftest.py stays the fail-closed backstop for the real root.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

# Ensure the worktree (not the stale global clone) is first on sys.path.
_WORKTREE = Path(__file__).resolve().parents[2]
if str(_WORKTREE) not in sys.path:
    sys.path.insert(0, str(_WORKTREE))

import hermes_constants
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


# Sidecar files the connect/init machinery can leave beside a DB: the
# cross-process init lock (``<db>.init.lock``), the dispatcher tick lock, and
# SQLite's WAL/rollback journals. A pinned run must not create any of these
# beside the shared-root DB.
_SIDECAR_SUFFIXES = (".init.lock", ".dispatch.lock", "-wal", "-shm", "-journal")

_Sentinel = namedtuple("_Sentinel", "sha256 columns files")


# ---------------------------------------------------------------------------
# Fixture — the incident topology
# ---------------------------------------------------------------------------

@pytest.fixture
def shared_root(tmp_path, monkeypatch):
    """Incident topology: native root = ``<tmp>/native/.hermes`` (a FAKE
    "live" root), ``HERMES_HOME`` = a profile dir under it.

    ``kanban_home()`` therefore resolves to the fake live root — the
    shared-across-profiles design — exactly like the 30c1df938db6 probe run,
    where pointing ``HERMES_HOME`` at scratch did NOT move the kanban root.
    """
    fake_root = tmp_path / "native" / ".hermes"
    fake_root.mkdir(parents=True)
    # Patch where production reads: get_default_hermes_root() resolves this
    # module global at call time (hermes_constants.py). Host-independent —
    # the win32 LOCALAPPDATA branch funnels through the same function.
    monkeypatch.setattr(
        hermes_constants, "_get_platform_default_hermes_home", lambda: fake_root
    )
    # Reset the REAL memo (hermes_constants._default_hermes_root_memo), not
    # the `_cached_default_hermes_root` attribute fresh_home resets (dead
    # code, absent from hermes_constants).
    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None)
    monkeypatch.setenv("HERMES_HOME", str(fake_root / "profiles" / "probe"))
    for var in (
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(var, raising=False)
    # Kanban module-level init cache must not leak between tests.
    kb._INITIALIZED_PATHS.clear()
    return fake_root


# ---------------------------------------------------------------------------
# Helpers — sentinel snapshots and read-only DB facts
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> frozenset:
    """Every file/dir under *root* as posix-relative names — catches sidecar
    creation (see ``_SIDECAR_SUFFIXES``) and stray ``kanban/`` workspace dirs."""
    return frozenset(p.relative_to(root).as_posix() for p in root.rglob("*"))


def _facts(db_path: Path, task_id: str | None = None) -> dict:
    """Read-only facts about a kanban DB: tasks column-name set (schema shape —
    the ALTER-damage guard), row count, and the (title, status, result) row."""
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
        row_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        task = None
        if task_id is not None:
            row = conn.execute(
                "SELECT title, status, result FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            task = dict(row) if row is not None else None
        return {"columns": columns, "row_count": row_count, "task": task}
    finally:
        conn.close()


def _seed_sentinel(fake_root: Path) -> _Sentinel:
    """Initialize the fake live DB (fixture env has NO pin) and snapshot it.

    Snapshots are taken only after every connection is closed so WAL
    ``-wal``/``-shm`` sidecars are checkpointed away and byte-level probes are
    permitted (``connect_tracked`` releases its registry entry on close).
    """
    seeded_path = kbc.init_db()
    assert seeded_path == fake_root / "kanban.db"
    with kbc.connect_closing():
        pass  # settle WAL; closing the last connection removes the sidecars
    facts = _facts(fake_root / "kanban.db")
    assert facts["row_count"] == 0  # seeded clean: any later row is the probe's
    return _Sentinel(
        sha256=_sha256(fake_root / "kanban.db"),
        columns=facts["columns"],
        files=_tree(fake_root),
    )


# ---------------------------------------------------------------------------
# T1 — topology precondition
# ---------------------------------------------------------------------------

def test_shared_root_topology_resolves_default_db_to_fake_live_root(shared_root):
    """Incident precondition: HERMES_HOME points elsewhere (profile mode), yet
    the kanban root does NOT move — kanban_home() shares the native root
    across profiles by design, so the default board's DB stays at
    ``<native root>/kanban.db``."""
    profile_dir = Path(os.environ["HERMES_HOME"])
    assert profile_dir == shared_root / "profiles" / "probe"  # points elsewhere
    assert profile_dir != shared_root
    assert hermes_constants.get_default_hermes_root() == shared_root  # native kept
    assert kb.kanban_home() == shared_root
    assert kb.kanban_db_path() == shared_root / "kanban.db"


# ---------------------------------------------------------------------------
# T3 — un-pinned control arm (the incident, replayed on a fake root)
# ---------------------------------------------------------------------------

def test_without_pin_writes_land_in_shared_root_incident_topology(shared_root):
    """Control arm: with the exact 30c1df938db6 topology and NO pin, the
    connect/init/create/complete write path lands in the shared root's
    ``kanban.db``.

    This proves the fixture reproduces the incident, so the pinned-isolation
    test cannot pass vacuously: if path resolution ever stops behaving like
    the incident topology, THIS test fails loudly instead of the pinned test
    silently going green for the wrong reason.
    """
    before = _seed_sentinel(shared_root)
    assert kb.kanban_db_path() == shared_root / "kanban.db"  # still un-pinned

    conn = kbc.connect()  # connect + auto-init resolve the shared-root path
    tid = kb.create_task(
        conn, title="incident probe replay", created_by="t_950d4b99-guard"
    )
    assert kb.complete_task(conn, tid, result="done via shared root") is True
    conn.close()

    live = shared_root / "kanban.db"
    after = _facts(live, task_id=tid)
    assert after["row_count"] == 1  # the probe card landed in the shared DB
    assert after["task"] == {
        "title": "incident probe replay",
        "status": "done",
        "result": "done via shared root",
    }
    assert after["columns"] == before.columns  # row writes, not schema drift
    assert _sha256(live) != before.sha256  # the shared-root file CHANGED


# ---------------------------------------------------------------------------
# T2 — pinned-isolation contract (the guard the incident demanded)
# ---------------------------------------------------------------------------

def test_pinned_kanban_db_keeps_connect_init_create_complete_off_shared_root(
    shared_root, tmp_path, monkeypatch
):
    """With ``HERMES_KANBAN_DB`` pinned exactly the way the dispatcher pins
    worker envs (hermes_cli/kanban_db_dispatch.py: HERMES_KANBAN_DB +
    HERMES_KANBAN_WORKSPACES_ROOT), every write surface — connect (with its
    auto-init), the migration/init pass, create_task, complete_task — stays
    on the pinned file while HERMES_HOME points elsewhere in the shared-root
    topology.

    The shared root's seeded DB must come out byte-identical: same sha256
    (no probe rows), same tasks column set (no ALTER damage — the incident's
    schema mutation), and the same file tree (no WAL/lock sidecars or
    ``kanban/`` workspace dirs created beside it).
    """
    before = _seed_sentinel(shared_root)
    assert before.columns  # seeded schema is real — guard the guard

    # Pin exactly what dispatch pins; the DB pin must win over board and
    # root resolution (kanban_db._board_path checks it first).
    pinned = tmp_path / "pinned" / "kanban.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(pinned))
    monkeypatch.setenv("HERMES_KANBAN_WORKSPACES_ROOT", str(tmp_path / "pinned-ws"))
    assert kb.kanban_db_path() == pinned

    conn = kbc.connect()  # connect + auto-init (schema + ALTER pass), pinned
    tid = kb.create_task(
        conn, title="pin isolation probe", created_by="t_950d4b99-guard"
    )
    # fire_lifecycle_hook stays at its default True — the real path; with no
    # hooks configured invoke_hook is a no-op, as every kanban test relies on.
    assert kb.complete_task(conn, tid, result="done via pinned db") is True
    conn.close()
    kbc.init_db()  # forced migration pass on the pinned path

    # The probe card and the full schema live in the PINNED DB.
    pinned_facts = _facts(pinned, task_id=tid)
    assert pinned_facts["task"] == {
        "title": "pin isolation probe",
        "status": "done",
        "result": "done via pinned db",
    }
    assert pinned_facts["row_count"] == 1
    assert pinned_facts["columns"] == before.columns  # migration ran THERE

    # The shared root is untouched — bytes, schema, rows, and directory.
    live = shared_root / "kanban.db"
    after = _facts(live)
    assert _sha256(live) == before.sha256
    assert after["columns"] == before.columns  # the ALTER-damage guard
    assert after["row_count"] == 0
    assert _tree(shared_root) == before.files  # no sidecars, no kanban/ dirs


# ---------------------------------------------------------------------------
# T4 — subprocess probe-replay arm (the exact incident vector, but pinned)
# ---------------------------------------------------------------------------

def _child_base_env(tmp_path: Path) -> tuple[dict, Path]:
    """Env for child processes whose NATIVE hermes root is a fake under
    ``tmp_path`` — built from the real host platform (never a faked one):
    POSIX redirects ``HOME``; win32 redirects ``LOCALAPPDATA``/``USERPROFILE``.

    Returns ``(env, fake_root)``. Pytest markers are stripped so the child
    behaves like the real probe process (no test guard active in it)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_WORKTREE)
    for var in (
        "PYTEST_CURRENT_TEST",
        "PYTEST_VERSION",
        "HERMES_TEST_ISOLATION",
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_BOARD",
    ):
        env.pop(var, None)
    if sys.platform == "win32":
        fake_root = tmp_path / "la" / "hermes"
        env["LOCALAPPDATA"] = str(tmp_path / "la")
        env["USERPROFILE"] = str(tmp_path / "u")
    else:
        fake_root = tmp_path / "u" / ".hermes"
        env["HOME"] = str(tmp_path / "u")
    fake_root.mkdir(parents=True)
    return env, fake_root


def _run_child(code: str, env: dict) -> dict:
    """Run a probe child and parse its last stdout line as JSON."""
    res = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(_WORKTREE),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert lines, f"child produced no report; stderr={res.stderr!r}"
    return json.loads(lines[-1])


def _shared_root_tree(root: Path) -> frozenset:
    """File set under *root* EXCLUDING the ``profiles/`` subtree.

    The probe child legitimately writes its own HERMES_HOME (a profile dir
    under the fake root — logs, caches); that is not the incident. The damage
    surface is the shared root itself: ``kanban.db`` + sidecars + ``kanban/``
    workspace/board dirs."""
    return frozenset(
        rel
        for rel in (p.relative_to(root).as_posix() for p in root.rglob("*"))
        if not rel.startswith("profiles/")
    )


def test_probe_subprocess_with_env_pin_only_leaves_shared_root_untouched(tmp_path):
    """The incident vector, replayed safely: a CHILD process with env-only
    isolation — native root faked via HOME/LOCALAPPDATA, HERMES_HOME a profile
    dir under it — protected ONLY by the env pin.

    The autouse ``_kanban_write_guard`` in tests/conftest.py is an in-process
    monkeypatch; it cannot see this child. If the ``HERMES_KANBAN_DB`` pin
    ever stops winning resolution, this is the test that catches the exact
    30c1df938db6 probe shape (schema ALTER + probe cards on the shared DB)."""
    base_env, fake_root = _child_base_env(tmp_path)

    # Seed the fake live DB via a child with HERMES_KANBAN_HOME only
    # (kanban_home() checks it first) — the parent stays out of the topology.
    seed_env = dict(base_env)
    seed_env["HERMES_KANBAN_HOME"] = str(fake_root)
    report = _run_child(
        "import json\n"
        "from hermes_cli import kanban_db_connect as kbc\n"
        "p = kbc.init_db()\n"
        "with kbc.connect_closing():\n"
        "    pass\n"
        "print(json.dumps({'seeded': str(p)}))\n",
        seed_env,
    )
    assert Path(report["seeded"]) == fake_root / "kanban.db"

    facts = _facts(fake_root / "kanban.db")
    assert facts["row_count"] == 0  # seeded clean: any later row is the probe's
    assert facts["columns"]
    before = _Sentinel(
        sha256=_sha256(fake_root / "kanban.db"),
        columns=facts["columns"],
        files=_shared_root_tree(fake_root),
    )

    # The probe child: incident topology + ONLY the env pin (no monkeypatch).
    pinned = tmp_path / "pinned" / "kanban.db"
    probe_env = dict(base_env)
    probe_env.update(
        HERMES_HOME=str(fake_root / "profiles" / "probe"),
        HERMES_KANBAN_DB=str(pinned),
        HERMES_KANBAN_WORKSPACES_ROOT=str(tmp_path / "pinned-ws"),
    )
    report = _run_child(
        "import json\n"
        "from hermes_cli import kanban_db as kb, kanban_db_connect as kbc\n"
        "conn = kbc.connect()\n"
        "tid = kb.create_task(conn, title='probe pinned',"
        " created_by='t_950d4b99-guard')\n"
        "ok = kb.complete_task(conn, tid, result='done')\n"
        "conn.close()\n"
        "kbc.init_db()\n"
        "print(json.dumps({'kanban_home': str(kb.kanban_home()),"
        " 'db': str(kb.kanban_db_path()), 'task': tid, 'completed': ok}))\n",
        probe_env,
    )
    # The child resolved to the pinned DB, not the shared/native root. (The
    # ROOT itself still resolves to the shared fake root — the pin redirects
    # the DB, not kanban_home(); that is the designed behavior under test.)
    assert Path(report["db"]) == pinned
    assert Path(report["kanban_home"]) == fake_root
    assert tmp_path in Path(report["kanban_home"]).resolve().parents
    assert report["completed"] is True

    pinned_facts = _facts(pinned, task_id=report["task"])
    assert pinned_facts["task"] == {
        "title": "probe pinned",
        "status": "done",
        "result": "done",
    }
    assert pinned_facts["row_count"] == 1
    assert pinned_facts["columns"] == before.columns  # migration ran there

    # Sentinel untouched: bytes, schema, rows, and the shared-root tree.
    live = fake_root / "kanban.db"
    after = _facts(live)
    assert _sha256(live) == before.sha256
    assert after["columns"] == before.columns
    assert after["row_count"] == 0
    assert _shared_root_tree(fake_root) == before.files
