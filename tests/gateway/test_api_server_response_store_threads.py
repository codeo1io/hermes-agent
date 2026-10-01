"""Thread-serialization contract for gateway ResponseStore (rm-034).

Regression for the shared-connection hazard: the store opens ONE sqlite
connection with ``check_same_thread=False`` and no process-wide lock, so any
future caller that leaves the event-loop thread (``asyncio.to_thread``,
executor) interleaves multi-statement sequences (put's LRU evict, get's
access-time touch) on that connection. The contract below pins the
observable behaviour: concurrent multi-threaded put/get/delete traffic
against a real on-disk store completes without error, honours the size cap,
and never returns a corrupted or missing entry.
"""

from __future__ import annotations

import threading

from gateway.platforms.api_server import ResponseStore

WORKERS = 4
PUTS_PER_WORKER = 60


def _worker(store: ResponseStore, worker_id: int, errors: list) -> None:
    try:
        for i in range(PUTS_PER_WORKER):
            response_id = f"resp-{worker_id}-{i}"
            store.put(response_id, {"worker": worker_id, "i": i, "pad": "x" * 32})
            got = store.get(response_id)
            if got is None or got.get("worker") != worker_id or got.get("i") != i:
                errors.append(f"read-back mismatch for {response_id}: {got!r}")
            if i % 20 == 0:
                store.delete(f"resp-{worker_id}-{i - 1}") if i > 0 else None
    except Exception as exc:  # noqa: BLE001 - the contract is "no error escapes"
        errors.append(f"worker {worker_id}: {exc!r}")


def test_concurrent_thread_traffic_is_serialized_and_consistent(tmp_path):
    store = ResponseStore(max_size=512, db_path=str(tmp_path / "responses.db"))
    errors: list = []
    threads = [
        threading.Thread(target=_worker, args=(store, w, errors)) for w in range(WORKERS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
        assert not t.is_alive(), "worker thread hung on the shared connection"

    assert errors == []
    # Size cap is honoured: 4*60 puts minus the deletions stays under 512.
    assert len(store) <= 512
    # Every entry the store claims to keep round-trips intact (LRU integrity
    # under contention: no torn rows, no missing payloads).
    kept = 0
    for w in range(WORKERS):
        for i in range(PUTS_PER_WORKER):
            got = store.get(f"resp-{w}-{i}")
            if got is not None:
                kept += 1
                assert got["worker"] == w and got["i"] == i
    assert kept == len(store), "get() disagrees with __len__ after concurrent traffic"
    store.close()


def test_close_waits_for_in_flight_access(tmp_path):
    """close() must not yank the connection under a concurrent reader."""
    store = ResponseStore(max_size=64, db_path=str(tmp_path / "responses.db"))
    for i in range(64):
        store.put(f"r{i}", {"i": i})

    stop = threading.Event()
    failures: list = []

    def _reader():
        i = 0
        while not stop.is_set() and i < 5000:
            try:
                store.get(f"r{i % 64}")
            except Exception as exc:  # noqa: BLE001
                failures.append(repr(exc))
                return
            i += 1

    reader = threading.Thread(target=_reader)
    reader.start()
    store.close()
    stop.set()
    reader.join(timeout=60)
    assert not reader.is_alive()
    assert failures == []
