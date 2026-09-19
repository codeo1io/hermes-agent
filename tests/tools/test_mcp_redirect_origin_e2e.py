"""E2E redirect-origin boundary on the pinned MCP HTTP stack.

Security invariant (Agent Plugins v1 ``strict_redirect_headers``): configured
auth/identity headers must NEVER arrive at a redirect target outside the
endpoint's origin — either because the redirect is refused outright or
because it is followed with the headers stripped.

These tests drive the REAL stack end to end against local HTTP servers on
two different origins (127.0.0.1 ports differ): the production
``_streamable_http_transport`` client construction (owned ``httpx2``
AsyncClient + body-cap transport + redirect-header-stripper event hook)
and the real SDK handshake from ``mcp.client.streamable_http``. The pinned
SDK's origin-bound redirect handling (mcp 2.2.0) sits under the same path,
so whichever layer enforces the boundary first, the contract is asserted on
the wire — on what the other origin actually receives — not on mocks or
SDK exception types.

Observed behavior this pins (mcp 2.2.0): a cross-origin 307 is REFUSED
(``Redirect to <url> not followed``) and the other origin receives no
request at all; a same-origin 307 is followed WITH the configured headers.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

AUTH_HEADER = "authorization"
PLUGIN_HEADER = "x-plugin-secret"
CONFIGURED_HEADERS = {AUTH_HEADER, PLUGIN_HEADER}
INIT_TIMEOUT = 8.0


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.lock = threading.Lock()

    def add(self, path: str, headers: dict[str, str]) -> None:
        with self.lock:
            self.requests.append((path, {k.lower(): v for k, v in headers.items()}))

    def hits(self, path: str | None = None) -> list[dict[str, str]]:
        with self.lock:
            return [h for p, h in self.requests if path is None or p == path]


def _start(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _sink_handler(recorder: _Recorder):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            recorder.add(self.path, dict(self.headers))
            self.send_response(404)  # not an MCP server: the handshake must fail
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = _respond
        do_POST = _respond

        def log_message(self, *args):  # silence
            pass

    return Handler


class _RedirectEveryHandler(BaseHTTPRequestHandler):
    """Every request gets a 307 to ``self.server.redirect_target``."""

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(307)
        self.send_header("Location", self.server.redirect_target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = _respond
    do_POST = _respond

    def log_message(self, *args):  # silence
        pass


def _path_routing_handler(recorder: _Recorder, redirect_paths: tuple[str, ...]):
    """One server, two roles: ``redirect_paths`` get a 307 to
    ``self.server.redirect_target`` (same origin by construction); every
    other path is a recording 404 sink."""

    class Handler(BaseHTTPRequestHandler):
        def _respond(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if self.path in redirect_paths:
                self.send_response(307)
                self.send_header("Location", self.server.redirect_target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            recorder.add(self.path, dict(self.headers))
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = _respond
        do_POST = _respond

        def log_message(self, *args):  # silence
            pass

    return Handler


@pytest.fixture()
def redirect_origins():
    """A redirector on its own origin (cross target = different port) and a
    same-origin server that re-routes /mcp → /sink on its own port."""
    cross_recorder = _Recorder()
    same_recorder = _Recorder()
    sink_b = _start(_sink_handler(cross_recorder))
    cross_redirector = _start(_RedirectEveryHandler)
    cross_redirector.redirect_target = f"http://127.0.0.1:{sink_b.server_address[1]}/mcp"
    same_server = _start(_path_routing_handler(same_recorder, redirect_paths=("/mcp",)))
    same_server.redirect_target = f"http://127.0.0.1:{same_server.server_address[1]}/sink"
    try:
        yield SimpleNamespace(
            cross_url=f"http://127.0.0.1:{cross_redirector.server_address[1]}/mcp",
            same_url=f"http://127.0.0.1:{same_server.server_address[1]}/mcp",
            cross_recorder=cross_recorder,
            same_recorder=same_recorder,
        )
    finally:
        for server in (cross_redirector, sink_b, same_server):
            server.shutdown()
            server.server_close()


def _make_transport(url: str):
    """Production client construction — the same method ``_run_http`` uses,
    with the SDK import gate ``_run_http`` performs."""
    from tools.mcp_tool import MCPServerTask, _ensure_mcp_sdk

    _ensure_mcp_sdk()
    task = MCPServerTask("e2e-redirect")
    return task._streamable_http_transport(
        url,
        headers={AUTH_HEADER: "Bearer leak-me", PLUGIN_HEADER: "s3cret"},
        connect_timeout=5.0,
        ssl_verify=True,
        client_cert=None,
        oauth_auth=None,
        strict_cfg_headers=False,
        configured_header_names=set(CONFIGURED_HEADERS),
    )


async def _drive_handshake(url: str) -> None:
    """Enter the production transport and run the real SDK initialize
    handshake through it. Errors are expected (the sinks are not MCP
    servers) and are not the assertion target — the wire is."""
    from mcp.client.session import ClientSession
    from mcp.types import Implementation

    async with _make_transport(url) as streams:
        read_stream, write_stream = streams
        async with ClientSession(
            read_stream, write_stream, client_info=Implementation(name="redirect-e2e", version="0")
        ) as session:
            try:
                await asyncio.wait_for(session.initialize(), timeout=INIT_TIMEOUT)
            except BaseException:  # 404 sink / refused redirect: both fine here
                pass


@pytest.mark.asyncio
async def test_cross_origin_redirect_never_receives_configured_headers(redirect_origins):
    """A 307 to a different origin must never deliver the configured
    auth/identity headers there — refused outright (mcp 2.2.0 behavior) or
    followed with them stripped (the header-stripper hook). Either is
    secure; what must never happen is the header arriving."""
    await _drive_handshake(redirect_origins.cross_url)
    observed = redirect_origins.cross_recorder.hits()
    leaked = [h for h in observed if AUTH_HEADER in h or PLUGIN_HEADER in h]
    assert not leaked, f"configured headers followed a cross-origin redirect: {leaked}"


@pytest.mark.asyncio
async def test_same_origin_redirect_keeps_configured_headers(redirect_origins):
    """The feature the follow-redirects client exists for: a redirect that
    stays inside the endpoint's origin (scheme+host+port) is followed WITH
    the configured headers (e.g. a gateway re-routing /mcp → /sink)."""
    await _drive_handshake(redirect_origins.same_url)
    observed = redirect_origins.same_recorder.hits("/sink")
    assert observed, "same-origin redirect was not followed at all"
    assert any(AUTH_HEADER in h for h in observed), (
        f"same-origin follow must preserve configured headers: {observed}"
    )
