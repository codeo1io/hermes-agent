"""Fd-monitor evidence must survive a clean reap: forget only what dying explains.

The chamber's fd monitor records a hit whenever a live child holds a sidecar that has been
deleted (``/proc/<pid>/fd`` " (deleted)"). ``reap()`` used to drop EVERY hit for the reaped
pid — right for the SIGTERM teardown race it was built for (settle noise must not poison
later episodes of a shared chamber), but it also erased whole-life leak evidence: a worker
that held a deleted sidecar for its entire run and then exited cleanly counted for nothing.
The forget is now bounded by the dying mark (when a stop request / signal began teardown);
rows first seen while the worker was simply ALIVE are real evidence and must survive.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.linux_only

from tests.e2e.core.sqlite._helpers import Chamber  # noqa: E402


def _hits_within(ch, deadline_s=10.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if any(name == "leaker" for name, _pid, _link in ch.deleted_hits_snapshot()):
            return True
        time.sleep(0.05)
    return False


def test_clean_exit_still_reports_a_whole_life_leaked_sidecar(tmp_path):
    ch = Chamber(tmp_path, journal="wal")
    try:
        ch.db.write_bytes(b"leak-target")
        ch.spawn("fd_leaker", "leaker", hold=1.0)

        assert _hits_within(ch), "monitor never recorded the leak while the worker was alive"

        rc = ch.reap("leaker")  # the leaker exits on its own: no stop request, no signal
        assert rc == 0

        hits = ch.deleted_hits_snapshot()
        assert any(name == "leaker" for name, _pid, _link in hits), (
            f"reap() erased real whole-life leak evidence: {hits}")
    finally:
        ch.shutdown()


def test_forget_keeps_rows_first_seen_while_alive(tmp_path):
    """Unit contract of the bounded forget: only rows that FIRST appeared after the dying
    mark (stop request / signal) are teardown settle-noise; rows first seen before it are
    evidence, even if the same fd keeps sampling through teardown."""
    ch = Chamber(tmp_path, journal="wal")
    try:
        t0 = time.monotonic()
        ch.db.write_bytes(b"x")
        evidence = ("w", 4242, f"{ch.db} (deleted)")
        noise = ("w", 4242, f"{ch.db}-shm (deleted)")
        ch.deleted_hits += [evidence, evidence, noise]
        ch._first_seen[evidence] = t0            # held since before teardown: real leak
        ch._first_seen[noise] = t0 + 2.0         # only appeared during teardown: settle race
        ch._dying_at[4242] = t0 + 1.0            # stop requested a second after t0

        ch.forget_deleted_hits_for_pid(4242)

        assert ch.deleted_hits_snapshot() == [evidence]

        # A pid nobody began tearing down (clean self-exit) keeps everything: reap() of a
        # process that exited by itself must not read as "teardown noise".
        other = ("r", 4243, f"{ch.db} (deleted)")
        ch.deleted_hits.append(other)
        ch._first_seen[other] = t0 + 3.0
        ch.forget_deleted_hits_for_pid(4243)
        assert set(ch.deleted_hits_snapshot()) == {evidence, other}
    finally:
        ch.shutdown()
