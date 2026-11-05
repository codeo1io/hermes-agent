"""The vault key against the host's REAL OS keychain (macOS Keychain, Windows Credential Manager).

Everything else in the vault suite uses an in-memory keyring, which proves Hermes' plumbing but not
that the platform store accepts, returns and deletes an entry the way ``agent.vault_keychain``
expects. These run only on the macOS and Windows CI lanes (never on Linux, so a developer's Secret
Service is never touched), use uniquely named dummy entries, and delete them in teardown.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from agent import vault_keychain as kc
from agent.vault_store import VaultStore

_LOGIN = {
    "identifier_type": "email",
    "identifier": "ci@example.com",
    "password": "dummy-pw-not-real-42",
}

# A locked login keychain (headless macOS CI runner, no UI to answer the access prompt) blocks the
# native Security.framework call FOREVER — it is a ctypes call, so it cannot be timed out in-process.
# The liveness probe runs in a killable subprocess instead; anything slower than this is a hang.
_PROBE_TIMEOUT_S = 30.0


@pytest.fixture
def os_keychain():
    """The real backend keyring resolves to; skip where the host has none (not a failure).

    Also skip — rather than hang to the per-file time budget — where the OS keychain cannot
    answer a bounded liveness probe: GitHub's macOS runners hold a locked login keychain for
    the runner session, and the first write blocks on an access prompt nothing can answer
    (upstream 9d0ab03ed34's smoke test flaps red the same way on NousResearch/hermes-agent).
    The blocking call is native (ctypes), so the probe runs as a killable subprocess."""
    try:
        kc.os_keyring()
    except kc.KeychainUnavailable as exc:
        pytest.skip(f"no OS keychain on this host: {exc}")
    probe: subprocess.CompletedProcess | None = None
    try:
        # PYTHONPATH pins the repo root ahead of any editable-install path when the
        # test venv belongs to a different checkout (dev boxes running cross-tree).
        import os as _os

        _repo_root = str(Path(__file__).resolve().parents[2])
        _env = {
            **_os.environ,
            "PYTHONPATH": _repo_root + _os.pathsep + _os.environ.get("PYTHONPATH", ""),
        }
        probe = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--keychain-liveness-probe",
            ],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            stdin=subprocess.DEVNULL,
            env=_env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip(
            f"OS keychain did not answer a {_PROBE_TIMEOUT_S:.0f}s liveness probe "
            "(locked keychain on this runner; not a vault regression)"
        )
    if probe is None or probe.returncode != 0:
        reason = (
            (probe.stderr if probe else "")
            or (probe.stdout if probe else "")
            or f"exit {probe.returncode if probe else '?'}"
        ).strip()
        pytest.skip(f"OS keychain liveness probe failed: {reason}")
    made: list[dict] = []
    yield made
    for ref in made:
        kc.delete_key(ref)


@pytest.mark.platforms("macos", "windows")
def test_real_keychain_stores_reads_and_deletes_a_dummy_entry(os_keychain):
    ref = {
        "storage": "keychain",
        "service": kc.SERVICE,
        "account": f"hermes-ci-smoke-{uuid.uuid4().hex}",
    }
    os_keychain.append(ref)
    key = Fernet.generate_key()
    kc.store_key(ref, key)  # raises unless the store hands the same bytes back
    assert kc.load_key(ref) == key
    assert kc.delete_key(ref)
    assert kc.load_key(ref) is None


@pytest.mark.platforms("macos", "windows")
def test_keychain_mode_vault_round_trips_through_the_real_keychain(
    os_keychain, tmp_path, monkeypatch
):
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "vault:\n  key_storage: keychain\n", encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    vault = home / "vault"

    item = (
        VaultStore()
        .add_item("login", "Example", dict(_LOGIN), origin="https://example.com")
        .id
    )
    ref = kc.read_ref(vault / "vault.keyref")
    assert ref is not None, (
        "keychain mode must keep only a pointer beside the ciphertext"
    )
    os_keychain.append(ref)
    assert not (vault / "vault.key").exists()
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]

    assert VaultStore().migrate_key("file") == "file"
    assert (vault / "vault.key").exists() and not (vault / "vault.keyref").exists()
    assert kc.load_key(ref) is None, (
        "moving to the file deletes the vault's own keychain entry"
    )

    assert VaultStore().migrate_key("keychain") == "keychain"
    back = kc.read_ref(vault / "vault.keyref")
    os_keychain.append(back)
    assert not (vault / "vault.key").exists()
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]


if (
    __name__ == "__main__"
):  # pragma: no cover - subprocess probe entrypoint (see os_keychain)
    import sys as _sys
    from pathlib import Path as _Path

    if "--keychain-liveness-probe" not in _sys.argv:
        _sys.exit(
            "internal error: this file is a pytest module; only --keychain-liveness-probe runs"
        )
    # Running the file directly puts tests/agent (not the repo root) on sys.path.
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from agent import vault_keychain as _kc

    try:
        ref = {
            "storage": "keychain",
            "service": _kc.SERVICE,
            "account": f"hermes-ci-probe-{uuid.uuid4().hex}",
        }
        _kc.store_key(
            ref, Fernet.generate_key()
        )  # raises unless the store hands the same bytes back
        _kc.delete_key(ref)
    except (
        Exception
    ) as exc:  # health: allow BLE001 -- the probe reports any failure as its exit
        print(f"{type(exc).__name__}: {exc}", file=_sys.stderr)
        _sys.exit(1)
