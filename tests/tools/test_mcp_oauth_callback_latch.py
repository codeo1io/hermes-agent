"""The loopback OAuth callback latches the first terminal result (#116278).

A browser follows the ``/callback`` redirect with queryless fetches (``/favicon.ico``), and the CLI waiter
samples the result only every 500 ms. A handler that wrote every GET into the result lost the stored code
between two polls, so the user saw "Authorization Successful" while ``hermes mcp login`` timed out. These
tests drive the production entry (``_make_callback_waiter`` → ``_start_callback_server`` → handler) with a
browser stand-in that sends its requests back-to-back; the waiter's result poll is held open until
every stand-in request has been answered, so the listener cannot be torn down between the requests
on a loaded runner (see ``_drive_waiter``).
"""

import asyncio
import io
import socket
import threading
from http.client import HTTPConnection

import pytest

pytest.importorskip("mcp.client.auth.oauth2", reason="MCP SDK 1.26.0+ required")

import tools.mcp_oauth as mo


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str, _retries: int = 60) -> int:
    for attempt in range(_retries):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            return resp.status
        except (ConnectionResetError, ConnectionRefusedError):
            # The listener socket can accept (kernel backlog) a hair before the
            # server thread is ready and reset or refuse the first request; retry
            # briefly. Bounds are generous: on a loaded CI runner the waiter
            # thread may not reach bind() for seconds after the test starts.
            if attempt == _retries - 1:
                raise
            threading.Event().wait(0.05)
        finally:
            conn.close()
    raise AssertionError("unreachable")


def _wait_listening(port: int) -> None:
    for _ in range(500):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            threading.Event().wait(0.02)
    raise AssertionError("callback listener never bound")


def _drive_waiter(monkeypatch, paths: list[str]):
    """Run the real waiter on its own loop; send *paths* back-to-back once the listener is bound.

    The waiter polls ``_result_taken`` every 500 ms and closes the listener as soon as the first
    terminal callback lands, so on a loaded runner the stand-in's later requests raced a dead port
    (``ConnectionRefusedError`` / ``ConnectionResetError``). The waiter's poll is held open until
    every request has been answered; the handler's own ``_result_taken`` reads are untouched, which
    is what the latch under test relies on."""
    monkeypatch.setattr(mo.sys, "stdin", io.StringIO())  # paste reader sees EOF; the HTTP listener is under test
    port = _free_port()
    out: dict = {}
    requests_sent = threading.Event()
    real_taken = mo._result_taken

    def run():
        async def main():
            with mo.force_interactive_oauth():
                return await mo._make_callback_waiter(port, timeout=30)()
        try:
            out["result"] = asyncio.run(main())
        except Exception as exc:  # noqa: BLE001 — the timeout is the failure under test
            out["exc"] = exc

    thread = threading.Thread(target=run)

    def gated_taken(result):
        if threading.current_thread() is thread and not requests_sent.is_set():
            return False  # the waiter's poll: keep the listener up until the browser stand-in is done
        return real_taken(result)

    monkeypatch.setattr(mo, "_result_taken", gated_taken)
    thread.start()
    _wait_listening(port)
    try:
        statuses = [_get(port, p) for p in paths]
    finally:
        requests_sent.set()
    # 30s covers the harness ceilings above (bind wait + per-request connect retries) on a loaded
    # runner; the waiter itself finishes one poll (~0.5 s) after requests_sent is set.
    thread.join(timeout=30)
    assert not thread.is_alive(), "waiter did not finish"
    assert "exc" not in out, f"waiter raised {type(out.get('exc')).__name__}"
    return statuses, out["result"]


def test_favicon_right_after_callback_does_not_clobber_the_code(monkeypatch):
    statuses, result = _drive_waiter(
        monkeypatch,
        ["/callback?code=synthetic&state=s1&iss=https://as.example", "/favicon.ico"],
    )
    assert statuses == [200, 404]
    assert (result.code, result.state, result.iss) == (
        "synthetic",
        "s1",
        "https://as.example",
    )


def test_first_terminal_callback_wins_over_later_ones(monkeypatch):
    statuses, result = _drive_waiter(
        monkeypatch,
        [
            "/favicon.ico",
            "/callback?code=first&state=s1",
            "/callback?code=second&state=s2",
            "/callback?error=access_denied&state=s1",
        ],
    )
    assert statuses == [404, 200, 200, 200]
    assert (result.code, result.state) == ("first", "s1")
