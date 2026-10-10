"""Relay media download safety — bearer confinement + SSRF vetting (boundary unit I92).

Regression for the cycle-6 finding: ``RelayMediaClient.download`` attached the per-gateway
bearer to ANY URL containing ``/relay/media/`` regardless of host (credential disclosure to
attacker-influenced inbound ``media_urls``), and fetched every URL unvetted (SSRF).

Contracts pinned here:
  - a URL that merely mimics the re-host path on a third-party host is fetched WITHOUT the
    bearer (when fetched at all) — the credential never leaves the configured connector host;
  - non-re-host (public pass-through) fetches are vetted through ``tools.url_safety.is_safe_url``
    — cloud-metadata targets are refused regardless of config, private/loopback targets by policy;
  - genuine re-hosts on OUR connector host keep the bearer and skip the IP-class vetting: the
    connector base URL is operator configuration and may legitimately be a LAN address.
"""

from __future__ import annotations

import threading
import urllib.request

import pytest

import gateway.relay.media as media_mod
from gateway.relay.media import RelayMediaClient


class _Resp:
    headers = {"Content-Type": "image/png", "Content-Length": "4"}

    def read(self, *_a):
        return b"\x89PNG"

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _capture_urlopen(monkeypatch):
    """Fake ``urllib.request.urlopen`` that records request headers; never hits the network."""
    seen: list[dict] = []

    def _fake_urlopen(req, timeout=None):  # noqa: ARG001
        seen.append(dict(req.headers))
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    return seen


@pytest.fixture
def client() -> RelayMediaClient:
    return RelayMediaClient("https://conn.example", "gw1", "sec")


# ── bearer confinement ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_foreign_rehost_path_never_receives_bearer(client, monkeypatch):
    """``/relay/media/`` on a third-party host is NOT our re-host: it must never see the
    per-gateway bearer. is_safe_url is simulated as permissive here so the bearer decision
    is tested in isolation from the SSRF gate."""
    monkeypatch.setattr(media_mod, "is_safe_url", lambda url: True)
    seen = _capture_urlopen(monkeypatch)

    path = await client.download("https://evil.example/relay/media/deadbeef")

    # The URL is attacker-influenced but merely public-class: fetched anonymously.
    assert path, "permissive host, small payload — fetch should succeed anonymously"
    assert seen, "expected exactly the one fetch"
    auth = seen[0].get("Authorization")
    assert not auth, f"bearer leaked to third-party host: Authorization={auth!r}"


@pytest.mark.asyncio
async def test_same_host_rehost_keeps_bearer(client, monkeypatch):
    """Genuine re-host on the configured connector host keeps the auth flow (no regression)."""
    seen = _capture_urlopen(monkeypatch)

    path = await client.download("https://conn.example/relay/media/aa11")

    assert path, "re-host fetch should succeed"
    assert (seen[0].get("Authorization") or "").startswith("Bearer ")


@pytest.mark.asyncio
async def test_private_lan_connector_rehost_is_exempt_from_ssrf_gate(monkeypatch):
    """The connector base is operator configuration: a LAN-hosted connector's re-hosts must
    keep working even though the host resolves private — the SSRF vetting targets
    attacker-influenced URLs, not the configured connector."""
    lan_client = RelayMediaClient("http://192.168.1.10:3000", "gw1", "sec")
    seen = _capture_urlopen(monkeypatch)

    path = await lan_client.download("http://192.168.1.10:3000/relay/media/aa11")

    assert path and seen, "LAN connector re-host must not be blocked by the SSRF gate"
    assert (seen[0].get("Authorization") or "").startswith("Bearer ")


@pytest.mark.asyncio
async def test_default_ports_match_explicit_for_own_host(client, monkeypatch):
    """netloc equality is by (host, effective port): scheme-default ports match their
    explicit spelling, so a connector that emits one form re-hosts authenticated."""
    monkeypatch.setattr(media_mod, "is_safe_url", lambda url: True)
    seen = _capture_urlopen(monkeypatch)

    await client.download("https://conn.example:443/relay/media/aa11")

    assert (seen[0].get("Authorization") or "").startswith("Bearer ")


# ── SSRF vetting of attacker-influenced URLs ────────────────────────────


@pytest.mark.asyncio
async def test_public_url_targeting_cloud_metadata_is_blocked(client, monkeypatch):
    """169.254.169.254 is the #1 SSRF target; a public-class inbound URL pointing at it must
    be refused before any network call (literal IP — no DNS, fully deterministic)."""
    seen = _capture_urlopen(monkeypatch)

    assert await client.download("http://169.254.169.254/latest/meta-data/") is None
    assert seen == [], "metadata endpoint must not be fetched"


@pytest.mark.asyncio
async def test_foreign_rehost_targeting_metadata_gets_neither_bearer_nor_fetch(client, monkeypatch):
    """The credential-leak and SSRF halves of the same finding combined: a metadata IP
    wearing our re-host path must be refused outright, not fetched with the bearer."""
    seen = _capture_urlopen(monkeypatch)

    assert await client.download("http://169.254.169.254/relay/media/aa11") is None
    assert seen == [], "metadata endpoint must not be fetched even with a re-host path"


@pytest.mark.asyncio
async def test_file_scheme_url_is_never_fetched(client, monkeypatch):
    """urllib would happily open ``file://`` — the scheme floor must refuse it pre-fetch."""
    seen = _capture_urlopen(monkeypatch)

    assert await client.download("file:///etc/hostname") is None
    assert seen == [], "file:// URL must not reach urlopen"


@pytest.mark.asyncio
async def test_public_urls_are_vetted_through_is_safe_url(client, monkeypatch):
    """The vetting must route through tools.url_safety (one policy for every fetch site):
    an unsafe public URL yields None with no network attempt."""
    monkeypatch.setattr(media_mod, "is_safe_url", lambda url: False)
    seen = _capture_urlopen(monkeypatch)

    assert await client.download("https://cdn.discordapp.com/attachments/1/2/i.png") is None
    assert seen == [], "is_safe_url=False must short-circuit before urlopen"

# ── upload: cap-before-read + off-loop file read ─────────────────────────


class _UploadResp:
    def __init__(self, body: bytes = b'{"id": "m1"}'):
        self._body = body

    def read(self, *_a):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.mark.asyncio
async def test_upload_reads_file_off_loop(client, tmp_path, monkeypatch):
    """The local-file read in upload() runs on a worker thread (was an on-loop read_bytes)."""
    media = tmp_path / "shot.png"
    media.write_bytes(b"\x89PNG")

    seen = {}
    real_read = media_mod.Path.read_bytes

    def _record_read(self):
        seen["thread"] = threading.get_ident()
        return real_read(self)

    monkeypatch.setattr(media_mod.Path, "read_bytes", _record_read)

    def _fake_urlopen(req, timeout=None):  # noqa: ARG001
        return _UploadResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    url = await client.upload(str(media))

    assert url == "https://conn.example/relay/media/m1"
    assert seen["thread"] != threading.get_ident(), "file read must be dispatched off-loop"


@pytest.mark.asyncio
async def test_upload_refuses_oversized_file_before_reading(client, tmp_path, monkeypatch):
    """An over-cap file is refused on stat, before any byte is read or POSTed.

    Regression (cycle-2 assess, media.py:103-110): the size verdict used to come
    from the fully-read buffer, so an attacker-sized file was read whole first.
    """
    monkeypatch.setattr(media_mod, "MEDIA_MAX_BYTES", 8)
    media = tmp_path / "huge.bin"
    media.write_bytes(b"x" * 16)
    seen = _capture_urlopen(monkeypatch)

    def _must_not_read(self):
        raise AssertionError("oversized file must be refused before any read")

    monkeypatch.setattr(media_mod.Path, "read_bytes", _must_not_read)

    assert await client.upload(str(media)) is None
    assert seen == [], "no network attempt for an over-cap file"


@pytest.mark.asyncio
async def test_upload_rechecks_size_after_read(client, tmp_path, monkeypatch):
    """A file that grows between stat and read is still refused before the POST."""
    monkeypatch.setattr(media_mod, "MEDIA_MAX_BYTES", 8)
    media = tmp_path / "growing.bin"
    media.write_bytes(b"small")  # stat sees 5 bytes — inside the cap
    seen = _capture_urlopen(monkeypatch)
    monkeypatch.setattr(media_mod.Path, "read_bytes", lambda self: b"x" * 16)

    assert await client.upload(str(media)) is None
    assert seen == []
