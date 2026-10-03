"""Locale-independence of token minting subprocesses (cycle-3 c3-u4).

``_run_mint_command`` captures a user-configured command's output in text
mode. On base it decoded with the process locale, so a ``LANG=C`` host
crashed with ``UnicodeDecodeError`` the moment a mint command emitted a
non-ASCII byte. The contract: minting decodes independently of the ambient
locale and never raises on undecodable bytes.
"""

import locale

import pytest

from agent import command_token_source


def _monkeypatch_ascii_locale(monkeypatch):
    # Simulate the C/POSIX locale that breaks locale-keyed text mode.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "ascii")


@pytest.mark.asyncio
async def test_mint_command_output_decodes_under_ascii_locale(monkeypatch):
    _monkeypatch_ascii_locale(monkeypatch)
    command = "python3 -c \"import sys; sys.stdout.buffer.write(b'\\xffsecret\\n')\""
    token = await command_token_source._run_mint_command(command)
    assert token is not None
    assert "secret" in token


@pytest.mark.asyncio
async def test_mint_command_error_output_never_crashes_decode(monkeypatch):
    _monkeypatch_ascii_locale(monkeypatch)
    command = "python3 -c \"import sys; sys.stderr.buffer.write(b'\\xffboom\\n'); raise SystemExit(1)\""
    token = await command_token_source._run_mint_command(command)
    # The command failed: no token is fine, but the call itself must not raise.
    assert token is None or isinstance(token, str)
