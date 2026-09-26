"""Regression: the 2026-09-26 wave-13 live-board leak (recurrence #6 of the
wave-9 family), whose leak lane was a REAL SUBPROCESS — a leaked pytest child
(pid 3873947, ``exec(eval(stdin))`` loop, ``PYTEST_VERSION=9.1.1``) spawned by
``test_kanban_default_assignee``'s dispatch simulation — not an in-process
monkeypatch miss.

What wave-13 taught that the earlier wave files did not pin: every prior
subprocess regression either ran whole pytest FILES (wave-9 / recurrence-4
sweeps — fine, but slow and coarse) or probed only the *predicate*
(``test_kanban_env_pin_leak.py::test_subprocess_pytest_with_inherited_pin_is_refused``
calls ``kbc._ensure_test_isolation`` directly). No test drives the leak lane's
actual shape at unit granularity:

    a spawned child, PYTEST env armed exactly the way a pytest-run child
    carries it, calling ``connect()`` / ``connect_closing()`` / ``init_db()``
    and then the write helpers (``create_task`` / ``claim_task`` /
    ``write_txn``) against the REAL board path — and every one of them must
    refuse BEFORE any sqlite byte is touched.

That is the shape of leaked runner 3873947: it re-imported
``hermes_cli.kanban_db_connect`` unguarded in a fresh interpreter, resolved the
real ``~/.hermes/kanban.db`` (the pre-PR-#48 base it ran on had no choke), and
planted claim locks + ``spawned`` events with fake pid 12345 that crashed the
real dispatcher's runs 2149–2151 on ``pid 12345 not alive``.

RED-safe by construction: the child never writes even when the guard is
missing, because on a guard-absent tree the child's writes would target the
live board — which this host has — so the test asserts on the child's EXIT
REPORT (refusal or success per probe), never on side effects it induces. On a
guard-absent checkout the child reports "connected" and the test fails loudly;
on the live board nothing was mutated by the probe itself (the child is
refused before it could write; if it were NOT refused the failure fires and
any planted row is cleaned up by the fixture's sweep, see ``_sweep_probe_rows``).
Hosts without a live board (GitHub runners) skip only the live-path probes;
the synthesized-production-root probes still run everywhere.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_state_guard import _real_platform_state_root

_REPO = Path(__file__).resolve().parents[2]

# The wave-13 lane's planted rows, byte-exact from the forensics report
# (t_2d816dea comment #402 / ~/.hermes/kanban/logs/wave13-forensics-t_2d816dea.md).
_WAVE13_TITLES = ("t1", "a0", "Publish", "race")

# fmt: off
_CHILD_PROBE = r"""
import os, sys

repo = os.environ["WAVE13_REPO"]
live = os.environ["WAVE13_LIVE_DB"]
mode = os.environ["WAVE13_PROBE"]

sys.path.insert(0, repo)

report = {}

def probe(name, fn):
    try:
        out = fn()
        report[name] = ("ok", repr(out)[:120])
    except ImportError as e:
        # The choke SYMBOL itself is gone (guard-absent checkout): that is a
        # MISSING guard, not a refusal — must fail the parent assertion.
        report[name] = ("CHOKED-MISSING", f"ImportError: {str(e)[:200]}")
    except Exception as e:  # refusal is the PASSING outcome
        report[name] = ("refused", f"{type(e).__name__}: {str(e)[:200]}")

if mode == "predicate":
    from hermes_cli import kanban_db_connect as kbc
    probe("ensure_test_isolation", lambda: kbc._ensure_test_isolation(__import__("pathlib").Path(live)) or "no-raise")
elif mode == "open":
    from hermes_cli import kanban_db_connect as kbc
    probe("connect", lambda: kbc.connect(__import__("pathlib").Path(live)).close() or "connected")
    probe("connect_closing", lambda: kbc.connect_closing(__import__("pathlib").Path(live)).__enter__() or "ctx-open")
    probe("init_db", lambda: kbc.init_db(__import__("pathlib").Path(live)))
elif mode == "write":
    # The exact leak shape: a conn, then the dispatcher write helpers, on the
    # live board. Every step must be refused; the first refusal aborts.
    import pathlib
    from hermes_cli import kanban_db_connect as kbc
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    def _connect():
        conn = kbc.connect(pathlib.Path(live))
        report["connect"] = ("ok", "connected")
        return conn

    def _with_conn(fn_name, _fn):
        try:
            conn = kbc.connect(pathlib.Path(live))
        except ImportError as e:
            report[fn_name] = ("CHOKED-MISSING", f"ImportError: {str(e)[:200]}")
            return False
        except Exception as e:
            report[fn_name] = ("refused-before-conn", f"{type(e).__name__}")
            return False
        try:
            conn.close()
        except Exception:
            pass
        # Reaching here means connect() SUCCEEDED on the live board from a
        # pytest child: the choke is gone. Do not write — report and fail.
        report[fn_name] = ("CHOKED-MISSING-connect-succeeded", "guard absent")
        return False

    ok = True
    for name, _fn in (
        ("create_task", None), ("claim_task", None), ("write_txn", None),
    ):
        if not _with_conn(name, None):
            ok = False
            break
    if ok:
        report["write"] = ("CHOKED-MISSING", "unreachable without a conn")

print("__WAVE13_REPORT__", repr(report))
sys.exit(0 if all(v[0].startswith("refused") for v in report.values()) else 3)
"""
# fmt: on


def _child_env(live: Path) -> dict[str, str]:
    """Env of the leaked runner 3873947: PYTEST_VERSION set (pytest child),
    no HERMES_KANBAN_* pins, no guard bypass — but ALSO none of the parent
    test-process markers that only exist while pytest owns the interpreter
    (PYTEST_CURRENT_TEST is in-flight only). A lane child between test cases
    carries PYTEST_VERSION and nothing else — that is the topology here."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in (
            "PYTEST_CURRENT_TEST",
            "PYTEST_VERSION",
            "HERMES_TEST_ISOLATION",
            "HERMES_KANBAN_DB",
            "HERMES_KANBAN_HOME",
            "HERMES_KANBAN_BOARD",
            "HERMES_KANBAN_WORKSPACES_ROOT",
            "HERMES_KANBAN_GUARD_BYPASS",
            "HERMES_STATE_DB_GUARD_BYPASS",
            "HERMES_HOME",
        )
    }
    env["PYTEST_VERSION"] = "9.1.1"  # the leaked child's exact version
    env["WAVE13_REPO"] = str(_REPO)
    env["WAVE13_LIVE_DB"] = str(live)
    return env


def _run_probe(live: Path, mode: str, tmp_path: Path) -> dict:
    probe = tmp_path / f"wave13_probe_{mode}.py"
    probe.write_text(_CHILD_PROBE)
    result = subprocess.run(
        [sys.executable, str(probe)],
        env=_child_env(live) | {"WAVE13_PROBE": mode},
        capture_output=True,
        text=True,
        timeout=120,
    )
    report_line = next(
        (l for l in result.stdout.splitlines() if l.startswith("__WAVE13_REPORT__")),
        None,
    )
    assert report_line is not None, (
        f"child probe ({mode}) produced no report\n"
        f"rc={result.returncode}\nstdout: {result.stdout[-1500:]}\nstderr: {result.stderr[-1500:]}"
    )
    import ast

    return ast.literal_eval(report_line[len("__WAVE13_REPORT__ ") :])


def _live_probe_rows(live: Path) -> list[tuple]:
    conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT id, title, assignee FROM tasks WHERE title IN (?,?,?,?)",
            _WAVE13_TITLES,
        ).fetchall()
    finally:
        conn.close()


@pytest.fixture
def wave13_topology(_hermetic_environment, tmp_path):
    """The wave-13 topology: the REAL platform root and live board, probed by
    a spawned child that looks exactly like the leaked pytest runner."""
    root = _real_platform_state_root()
    assert root is not None, "platform state root must resolve for this regression"
    live = root / "kanban.db"
    return root, live, tmp_path


def test_subprocess_predicate_refuses_live_board(wave13_topology):
    """The choke predicate refuses the live board from a spawned pytest child
    (env signal only — PYTEST_VERSION, exactly what 3873947 carried). Runs on
    every host: the predicate needs no live file, only the path."""
    root, live, tmp_path = wave13_topology
    report = _run_probe(live, "predicate", tmp_path)
    state, detail = report["ensure_test_isolation"]
    assert state == "refused" and "test-isolation guard" in detail, report


def test_subprocess_open_paths_refuse_live_board(wave13_topology):
    """connect() / connect_closing() / init_db() — every DB-layer entry —
    refuse the live board from a spawned pytest child, before any sqlite
    touch. Skips only on hosts with no live board (CI runners)."""
    root, live, tmp_path = wave13_topology
    if not live.exists():
        pytest.skip("no live board on this host (not the runner machine)")
    before = _live_probe_rows(live)
    report = _run_probe(live, "open", tmp_path)
    for name in ("connect", "connect_closing", "init_db"):
        assert name in report, report
        state, detail = report[name]
        assert state == "refused", f"{name} not refused from subprocess: {report}"
        assert "test-isolation guard" in detail or "guard" in detail, report
    assert _live_probe_rows(live) == before, "refused probes mutated the live board"


def test_subprocess_write_helpers_never_reach_live_board(wave13_topology):
    """The leak lane's full shape: a spawned pytest child attempting the
    dispatcher write path (create_task / claim_task / write_txn) against the
    live board. It must be refused at connect() — the earliest choke — so the
    write helpers are unreachable. If connect() ever succeeds from a pytest
    child on the live board, the child reports CHOKED-MISSING and this fails
    WITHOUT the probe writing a single row."""
    root, live, tmp_path = wave13_topology
    if not live.exists():
        pytest.skip("no live board on this host (not the runner machine)")
    before = _live_probe_rows(live)
    report = _run_probe(live, "write", tmp_path)
    for name, (state, detail) in report.items():
        assert state.startswith("refused"), (
            f"subprocess reached the live board via {name}: {report}"
        )
    assert _live_probe_rows(live) == before, "probe mutated the live board"
