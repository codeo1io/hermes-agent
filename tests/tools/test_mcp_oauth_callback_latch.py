"""The loopback OAuth callback latches the first terminal result (#116278).

A browser follows the ``/callback`` redirect with queryless fetches (``/favicon.ico``), and the CLI waiter
samples the result only every 500 ms. A handler that wrote every GET into the result lost the stored code
between two polls, so the user saw "Authorization Successful" while ``hermes mcp login`` timed out. These
tests drive the production entry (``_make_callback_waiter`` → ``_start_callback_server`` → handler) with a
browser stand-in that sends its requests back-to-back; the waiter's poll is parked on an Event so the
listener cannot be torn down between the requests on a loaded runner (see ``_drive_waiter``).
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


# How long one parked waiter poll may sleep before re-checking on its own (a
# safety ceiling, not the expected wait: the test releases the park as soon as
# its requests are done). Small enough that a clobbered result still fails fast.
_PARK_CEILING = 10.0


def _drive_waiter(monkeypatch, paths: list[str]):
    """Run the real waiter on its own loop; send *paths* back-to-back once the listener is bound.

    The waiter's 0.5 s poll loop calls ``server.shutdown()`` once a terminal result is latched, so on
    anything but a quiet runner the "back-to-back" second request can arrive after the listener is
    closed and die with ECONNREFUSED — a property of the poll cadence, not of the handler under test
    (#116278 is about the handler clobbering the latched code). The waiter's ``asyncio.sleep`` is
    therefore parked on an Event the test releases after every request has been answered; the handler,
    server, and result plumbing stay 100% production code.
    """
    monkeypatch.setattr(
        mo.sys, "stdin", io.StringIO()
    )  # paste reader sees EOF; the HTTP listener is under test
    port = _free_port()
    out: dict = {}
    release = threading.Event()

    class _ParkedAsyncio:
        """Forwards to the real asyncio; ``sleep`` parks (bounded) until the test releases it."""

        def __getattr__(self, name: str):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(seconds: float, *args, **kwargs) -> None:
            await asyncio.get_running_loop().run_in_executor(
                None, release.wait, _PARK_CEILING
            )

    monkeypatch.setattr(mo, "asyncio", _ParkedAsyncio())

    def run():
        async def main():
            with mo.force_interactive_oauth():
                return await mo._make_callback_waiter(port, timeout=4)()

        try:
            out["result"] = asyncio.run(main())
        except Exception as exc:  # noqa: BLE001 — the timeout is the failure under test
            out["exc"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    _wait_listening(port)
    try:
        statuses = [_get(port, p) for p in paths]
    finally:
        release.set()
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
