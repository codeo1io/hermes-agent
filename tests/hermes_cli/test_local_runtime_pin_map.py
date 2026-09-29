"""Contracts for the shipped llama.cpp asset sha256 pin map.

The managed local runtime downloads and executes third-party binaries at runtime; the
dependency-pinning policy pins them like any other dep. These tests tie the pin map to the
config-pinned release tag (a tag bump without pins fails here) and prove a poisoned
download fails closed with NO caller-supplied pin — the map is applied by default.
"""

import re

import pytest

from hermes_cli.config_defaults import DEFAULT_CONFIG
from hermes_cli.local_runtime import binaries
from hermes_cli.local_runtime.binaries import BinaryResolutionError

# Every (os, arch, backend) combination the installer can ever resolve.
_PLATFORMS = ("ubuntu", "win", "macos")
_ARCHES = ("x64", "arm64")
_BACKENDS = ("cuda", "vulkan", "hip", "cpu", "metal")


def _resolvable_assets(tag: str) -> set[str]:
    assets = set()
    for os_name in _PLATFORMS:
        for arch in _ARCHES:
            for backend in _BACKENDS:
                try:
                    plan = binaries.resolve_assets(tag, backend, os_name=os_name, arch=arch)
                except BinaryResolutionError:
                    continue
                assets.update(plan.assets)
    return assets


def test_configured_tag_pins_every_resolvable_asset():
    tag = DEFAULT_CONFIG["local_runtime"]["tag"]
    pins = binaries.pinned_assets(tag)
    assert pins, f"configured local_runtime tag {tag} ships no sha256 pins"
    missing = _resolvable_assets(tag) - set(pins)
    assert not missing, f"unpinned downloadable assets for {tag}: {sorted(missing)}"


def test_pin_map_entries_are_lowercase_sha256_hex():
    for tag, pins in binaries.RUNTIME_ASSET_SHA256.items():
        for asset, digest in pins.items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest), (tag, asset, digest)


def test_pin_map_only_names_assets_the_release_style_matches():
    for tag, pins in binaries.RUNTIME_ASSET_SHA256.items():
        for asset in pins:
            # Sanity tie to the resolver's naming scheme: llama-<tag>-bin-… or the cudart pair.
            assert asset.startswith((f"llama-{tag}-bin-", "cudart-llama-bin-")), (tag, asset)


def test_unpinned_tag_degrades_to_empty_not_an_error():
    assert binaries.pinned_assets("b0notarealtag") == {}


def test_poisoned_download_fails_closed_by_default(tmp_path, monkeypatch):
    """No expected_sha256 argument: the shipped map must still reject a tampered archive."""
    tag = DEFAULT_CONFIG["local_runtime"]["tag"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    # Resolve the asset name the way the installer will so the poisoned file is the one it
    # verifies, on every host platform.
    plan = binaries.resolve_assets(tag, "cpu")
    asset = plan.assets[0]
    assert asset in binaries.pinned_assets(tag)
    downloads = binaries.runtimes_root() / "downloads"
    downloads.mkdir(parents=True)
    (downloads / asset).write_bytes(b"tampered archive bytes")
    with pytest.raises(BinaryResolutionError, match="sha256 mismatch"):
        binaries.ensure_runtime_installed(tag, "cpu")
    # The poisoned download must not survive for a retry to trust.
    assert not (downloads / asset).exists()


def test_caller_pins_override_the_map(tmp_path, monkeypatch):
    """An explicit expected_sha256 wins over the shipped map (custom/mirror deployments):
    content matching the caller's pin installs even though it matches no map entry."""
    tag = DEFAULT_CONFIG["local_runtime"]["tag"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    plan = binaries.resolve_assets(tag, "cpu")
    asset = plan.assets[0]
    downloads = binaries.runtimes_root() / "downloads"
    downloads.mkdir(parents=True)
    (downloads / asset).write_bytes(b"custom-mirror archive bytes")
    caller_digest = binaries._sha256(downloads / asset)
    assert caller_digest not in binaries.pinned_assets(tag).values()
    monkeypatch.setattr(binaries, "_extract", lambda *a, **k: None)
    monkeypatch.setattr(binaries, "verify_install", lambda *a, **k: "stub")
    install_dir = binaries.ensure_runtime_installed(
        tag, "cpu", expected_sha256={asset: caller_digest})
    assert install_dir.is_dir()
