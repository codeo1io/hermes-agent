"""The loopback OAuth callback latches the first terminal result (#116278).

A browser follows the ``/callback`` redirect with queryless fetches (``/favicon.ico``), and the CLI waiter
samples the result only every 500 ms. A handler that wrote every GET into the result lost the stored code
between two polls, so the user saw "Authorization Successful" while ``hermes mcp login`` timed out. These
tests drive the production entry (``_make_callback_waiter`` → ``_start_callback_server`` → handler) with a
browser stand-in that sends its requests back-to-back. Post-latch GETs must not rely on beating the
500 ms poll: on a contended CI runner they can arrive after the waiter already closed its listener,
and a refusal there is by-design (the request never reached the handler, so the latch is safe).
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


def _get(port: int, path: str, *, tolerate_closed: bool = False) -> "int | None":
    """Status of one GET, or ``None`` when the listener is already closed.

    After the first terminal callback the waiter notices the latch within one 0.5 s
    poll and tears its listener down (``finally: server_close()``). On a contended
    CI runner the stand-in's *later* GETs can be scheduled past that close even
    when sent back-to-back; a refused connection there is by-design — the request
    never reached the handler, so it cannot clobber the latched result — not a
    latch failure. Only post-latch GETs pass ``tolerate_closed``; the pre-latch
    GET must find the listener (``_wait_listening`` guaranteed the bind).
    """
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        return resp.status
    except (ConnectionRefusedError, ConnectionResetError):
        # Refused = listener already closed; reset (incl. RemoteDisconnected) = the teardown
        # RST'd a backlog connection mid-response. Both mean "not delivered" post-latch.
        if tolerate_closed:
            return None
        raise
    finally:
        conn.close()


def _wait_listening(port: int) -> None:
    for _ in range(200):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            threading.Event().wait(0.02)
    raise AssertionError("callback listener never bound")


def _drive_waiter(monkeypatch, paths: list[str], *, tolerant_from: int | None = None):
    """Run the real waiter on its own loop; send *paths* back-to-back once the listener is bound.

    GETs at index >= *tolerant_from* happen after the first terminal callback, so they
    tolerate the waiter having already closed its listener (see ``_get``).
    """
    monkeypatch.setattr(mo.sys, "stdin", io.StringIO())  # paste reader sees EOF; the HTTP listener is under test
    port = _free_port()
    out: dict = {}

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
    statuses = [
        _get(port, p, tolerate_closed=tolerant_from is not None and index >= tolerant_from)
        for index, p in enumerate(paths)
    ]
    thread.join(timeout=15)
    assert not thread.is_alive(), "waiter did not finish"
    assert "exc" not in out, f"waiter raised {type(out.get('exc')).__name__}"
    return statuses, out["result"]


def test_favicon_right_after_callback_does_not_clobber_the_code(monkeypatch):
    statuses, result = _drive_waiter(
        monkeypatch,
        ["/callback?code=synthetic&state=s1&iss=https://as.example", "/favicon.ico"],
        tolerant_from=1)
    # The favicon may land before the latch poll (404) or after the waiter closed
    # its listener (None); either way it must not have replaced the stored code.
    assert statuses[0] == 200
    assert statuses[1] in (404, None)
    assert (result.code, result.state, result.iss) == ("synthetic", "s1", "https://as.example")


def test_first_terminal_callback_wins_over_later_ones(monkeypatch):
    statuses, result = _drive_waiter(monkeypatch, [
        "/favicon.ico",
        "/callback?code=first&state=s1",
        "/callback?code=second&state=s2",
        "/callback?error=access_denied&state=s1",
    ], tolerant_from=2)
    # Later GETs see the "already received" page (200) when they beat the 0.5 s
    # latch poll, or a closed listener (None) when they do not — both leave the
    # first terminal result in place.
    assert statuses[0] == 404
    assert statuses[1] == 200
    assert all(status in (200, None) for status in statuses[2:])
    assert (result.code, result.state) == ("first", "s1")
