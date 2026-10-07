"""Data-URL upload guard: an oversized payload must be rejected on its encoded
length, BEFORE base64.b64decode allocates ~3/4 of that length in memory.

On the old order (decode -> validate -> cap) an oversized-but-invalid payload was
answered 400 "not valid base64" only after paying the full decode cost, and any
oversized payload allocated before the size verdict. The contract: the size verdict
depends only on the payload length, never on decode validity.
"""

import base64

import pytest
from fastapi import HTTPException

from hermes_cli.web_routers.files import _decode_data_url


@pytest.fixture
def capped_uploads(monkeypatch):
    """Shrink the 100 MiB cap so length-boundary behavior is cheap to exercise.

    _decode_data_url imports the constant lazily from hermes_cli.web_server, so
    patching it there is the seam production reads.
    """
    from hermes_cli import web_server

    monkeypatch.setattr(web_server, "_MANAGED_FILE_MAX_BYTES", 300)
    return 300


def _payload(alphabet: str, repeats: int) -> str:
    return f"data:application/octet-stream;base64,{alphabet * repeats}"


def test_oversized_payload_is_rejected_by_length_not_decode_validity(capped_uploads):
    # 404 encoded chars would decode to ~303 bytes (over the 300-byte cap), but
    # "!" is outside the alphabet: the length verdict must win — 413, never
    # "not valid base64" (400).
    with pytest.raises(HTTPException) as exc:
        _decode_data_url(_payload("!", 404))
    assert exc.value.status_code == 413


def test_oversized_valid_base64_is_still_rejected(capped_uploads):
    # 404 encoded chars -> 303 decoded bytes, over the 300-byte cap.
    with pytest.raises(HTTPException) as exc:
        _decode_data_url(_payload("A", 404))
    assert exc.value.status_code == 413


def test_boundary_encoded_length_still_decodes(capped_uploads):
    # 400 encoded chars -> exactly 300 decoded bytes: at the cap, not over it.
    data, mime = _decode_data_url(_payload("A", 400))
    assert len(data) == 300
    assert mime == "application/octet-stream"


def test_small_payload_round_trips(capped_uploads):
    encoded = base64.b64encode(b"hello").decode()
    data, mime = _decode_data_url(f"data:text/plain;base64,{encoded}")
    assert data == b"hello"
    assert mime == "text/plain"
