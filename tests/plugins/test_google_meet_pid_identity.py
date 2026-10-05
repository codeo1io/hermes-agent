"""Regression tests: google_meet ``.active.json`` pid identity + exit hygiene.

``process_manager`` used to trust the bare pid in ``.active.json``: the pointer can outlive
its bot (crash without cleanup), the OS recycles pids, and the next ``meet_join`` /
``meet_leave`` then SIGTERMs an unrelated victim while ``status()`` reported the meeting
alive. The record now carries a spawn-time fingerprint (``pid_start_time``), a pid is acted
on only when pid + start-time both match (canonical matcher:
``hermes_cli.process_identity._pid_alive_matches``; a pointer with no fingerprint is
unverifiable, not trusted), and the bot clears the pointer on every exit path it controls —
but only while the pointer still names its own process.

Real subprocesses as stand-in victims (same approach as the kanban pid-fingerprint tests);
no Playwright needed.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time

import pytest


MEET_URL = "https://meet.google.com/abc-defg-hij"


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    yield hermes_home


@pytest.fixture
def victims():
    """Track spawned stand-in processes so a failing assertion can't leak them."""
    procs = []
    yield procs
    for p in procs:
        with contextlib.suppress(Exception):
            p.kill()
        with contextlib.suppress(Exception):
            p.wait(timeout=5)


def _spawn_victim() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def _write_pointer(pm, pid, *, start_time=...):
    record = {"pid": pid, "meeting_id": "abc-defg-hij", "out_dir": str(pm._root() / "abc-defg-hij"),
              "url": MEET_URL, "started_at": time.time(), "log_path": "bot.log", "mode": "transcribe"}
    if start_time is not ...:
        record["pid_start_time"] = start_time
    pm._write_active(record)


def _fake_popen_result(pid):
    """Popen stub for pm.start(): reports the given (real, pre-spawned) pid."""
    class _Proc:
        pass
    proc = _Proc()
    proc.pid = pid
    return proc


def test_status_recycled_pid_is_not_alive(victims):
    from plugins.google_meet import process_manager as pm

    victim = _spawn_victim(); victims.append(victim)
    # The OS handed the dead bot's pid to an unrelated process; the stale pointer either
    # carries a fingerprint for the OLD incarnation or none at all (pre-fingerprint record).
    _write_pointer(pm, victim.pid, start_time=pm._pid_start_time(victim.pid) - 3600.0)
    assert pm.status()["alive"] is False

    _write_pointer(pm, victim.pid)  # legacy pointer: no fingerprint recorded
    assert pm.status()["alive"] is False


def test_status_matching_fingerprint_is_alive(victims):
    from plugins.google_meet import process_manager as pm

    victim = _spawn_victim(); victims.append(victim)
    _write_pointer(pm, victim.pid, start_time=pm._pid_start_time(victim.pid))
    st = pm.status()
    assert st["ok"] is True and st["alive"] is True


def test_stop_refuses_to_signal_recycled_pid(victims):
    from plugins.google_meet import process_manager as pm

    victim = _spawn_victim(); victims.append(victim)
    _write_pointer(pm, victim.pid)  # legacy stale pointer; pid now names the victim

    res = pm.stop()

    assert res["ok"] is True
    assert victim.poll() is None, "stop() must not signal a pid it cannot prove is ours"
    assert pm._read_active() is None  # pointer still cleared (hygiene)


def test_start_leaves_recycled_victim_running_and_records_fingerprint(victims, monkeypatch):
    from plugins.google_meet import process_manager as pm

    stale = _spawn_victim(); victims.append(stale)
    replacement = _spawn_victim(); victims.append(replacement)
    _write_pointer(pm, stale.pid)  # stale legacy pointer naming the victim

    monkeypatch.setattr(pm.subprocess, "Popen", lambda *a, **k: _fake_popen_result(replacement.pid))
    res = pm.start(MEET_URL)

    assert res["ok"] is True
    assert stale.poll() is None, "meet_join must not signal a pid it cannot prove is ours"
    record = pm._read_active()
    assert record["pid"] == replacement.pid
    assert record["pid_start_time"] == pm._pid_start_time(replacement.pid)  # fingerprint recorded
    assert pm.status()["alive"] is True


def test_start_signals_verified_predecessor(victims, monkeypatch):
    from plugins.google_meet import process_manager as pm

    running_bot = _spawn_victim(); victims.append(running_bot)
    successor = _spawn_victim(); victims.append(successor)
    _write_pointer(pm, running_bot.pid, start_time=pm._pid_start_time(running_bot.pid))

    monkeypatch.setattr(pm.subprocess, "Popen", lambda *a, **k: _fake_popen_result(successor.pid))
    res = pm.start(MEET_URL)

    assert res["ok"] is True
    assert pm._read_active()["pid"] == successor.pid
    deadline = time.time() + 15
    while running_bot.poll() is None and time.time() < deadline:
        time.sleep(0.2)
    assert running_bot.poll() is not None, "a VERIFIED running bot must be stopped on replacement"


def test_release_active_if_mine_scopes_to_own_incarnation():
    from plugins.google_meet import process_manager as pm

    mine = pm._pid_start_time(os.getpid())
    _write_pointer(pm, os.getpid(), start_time=mine)
    pm.release_active_if_mine()
    assert pm._read_active() is None  # own pointer: cleared

    _write_pointer(pm, os.getpid(), start_time=mine - 3600.0)
    pm.release_active_if_mine()
    assert pm._read_active() is not None  # same pid, different incarnation: preserved

    _write_pointer(pm, os.getpid() + 1, start_time=mine)
    pm.release_active_if_mine()
    assert pm._read_active() is not None  # someone else's pointer: preserved


def test_run_bot_clears_pointer_on_early_exit(monkeypatch):
    """Every run_bot exit path releases the pointer — including config-refusal returns,
    no Playwright required."""
    from plugins.google_meet import meet_bot, process_manager as pm

    _write_pointer(pm, os.getpid(), start_time=pm._pid_start_time(os.getpid()))
    monkeypatch.setenv("HERMES_MEET_URL", "https://evil.example.com/nope")
    monkeypatch.setenv("HERMES_MEET_OUT_DIR", str(pm._root() / "evil"))

    rc = meet_bot.run_bot()

    assert rc == 2
    assert pm._read_active() is None

    # And it never clobbers a pointer naming a different process.
    _write_pointer(pm, os.getpid() + 1, start_time=pm._pid_start_time(os.getpid()))
    assert meet_bot.run_bot() == 2
    assert pm._read_active() is not None
