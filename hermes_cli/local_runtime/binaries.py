"""Binary acquisition for the managed llama.cpp runtime."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


logger = logging.getLogger(__name__)

RELEASE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset}"

# Windows CUDA zips ship per CUDA major; the runtime zip must be paired with its cudart zip so
# end users need no toolkit. 13.3 verified on 13.1 and 13.2 drivers.
_WIN_CUDA_VERSION = "13.3"
# arm64 Windows CUDA prebuilts landed upstream (~b1036x) on CUDA 13.4. Tags at or before b10290
# don't have them; resolution succeeds and the download 404s honestly if a user pins backward.
_WIN_CUDA_VERSION_ARM64 = "13.4"


def default_tag() -> str:
    """Fallback when the config section is missing entirely; DEFAULT_CONFIG owns the shipped tag."""
    from hermes_cli.config_defaults import DEFAULT_CONFIG

    return DEFAULT_CONFIG["local_runtime"]["tag"]


class BinaryResolutionError(RuntimeError):
    """No usable asset combination for this platform/backend."""


@dataclass
class AssetPlan:
    """The exact zips one runtime install needs, in extraction order."""

    tag: str
    backend: str            # cuda | metal | vulkan | hip | cpu
    assets: list[str] = field(default_factory=list)

    @property
    def install_dir(self) -> Path:
        return runtimes_root() / self.tag / self.backend


def runtimes_root() -> Path:
    """Machine-scoped, deliberately NOT profile-scoped: engine binaries, presets and server state
    describe this machine's hardware and its one managed server (stable port) — a second profile
    re-downloading the engine or fighting over the port would be the bug. Profile-scoped things
    (default model, enabled) live in each profile's config.yaml."""
    from hermes_constants import get_default_hermes_root

    return get_default_hermes_root() / "runtimes" / "llamacpp"


def manifest_verified(manifest: Path) -> bool:
    """True when an install manifest records a verified_version (missing/damaged -> False)."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and bool(data.get("verified_version"))


def _release_number(tag: str) -> int:
    digits = "".join(ch for ch in tag if ch.isdigit())
    return int(digits) if digits else 0


def installed_tags() -> list[str]:
    """Tags with a verified install, newest first by release number. The boot ladder and the
    update check both read installed-ness from here — one resolver, every caller."""
    root = runtimes_root()
    if not root.exists():
        return []
    found = {entry.name for entry in root.iterdir()
             if entry.is_dir() and entry.name != "downloads"
             and any(manifest_verified(m) for m in entry.glob("*/manifest.json"))}
    return sorted(found, key=_release_number, reverse=True)


def _host_os_arch() -> tuple[str, str]:
    """(os, arch) normalized to release-asset vocabulary. PITFALL: PROCESSOR_ARCHITECTURE lies
    under x64 emulation on ARM64 Windows, and platform.machine() reads the same env on some
    Pythons — so on Windows prefer PROCESSOR_IDENTIFIER's text when present."""
    system = platform.system().lower()
    os_name = {"windows": "win", "darwin": "macos", "linux": "ubuntu"}.get(system, system)
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if os_name == "win":
        ident = os.environ.get("PROCESSOR_IDENTIFIER", "").lower()
        if "armv8" in ident or "arm " in ident:
            arch = "arm64"
    return os_name, arch


def select_backend(gpu_vendor: str | None, os_name: str | None = None) -> str:
    """CUDA if NVIDIA, Metal on macOS, Vulkan if a non-NVIDIA GPU is present, else CPU.
    ``--list-devices`` validates post-install; the supervisor's touch generation is ground truth."""
    if os_name is None:
        os_name, _ = _host_os_arch()
    if os_name == "macos":
        return "metal"
    vendor = (gpu_vendor or "").lower()
    if "nvidia" in vendor:
        return "cuda"
    if vendor in ("amd", "intel") or "radeon" in vendor or "arc" in vendor:
        return "vulkan"
    return "cpu"


# Per-OS (human label, {backend: asset-name templates}). Windows CUDA pairs the runtime zip with
# its cudart zip; ubuntu ships tarballs, win ships zips.
_ASSET_TEMPLATES = {
    "ubuntu": ("linux", {
        "vulkan": ["llama-{tag}-bin-ubuntu-vulkan-{arch}.tar.gz"],
        "hip": ["llama-{tag}-bin-ubuntu-rocm-7.2-{arch}.tar.gz"],
        "cpu": ["llama-{tag}-bin-ubuntu-{arch}.tar.gz"],
    }),
    "win": ("windows", {
        "cuda": ["llama-{tag}-bin-win-cuda-{cuda_ver}-{arch}.zip",
                 "cudart-llama-bin-win-cuda-{cuda_ver}-{arch}.zip"],
        "vulkan": ["llama-{tag}-bin-win-vulkan-x64.zip"],
        "hip": ["llama-{tag}-bin-win-hip-radeon-x64.zip"],
        "cpu": ["llama-{tag}-bin-win-cpu-{arch}.zip"],
    }),
}


# sha256 pins for the llama.cpp release assets Hermes downloads and executes at runtime —
# third-party binaries get the same pinning policy as any other dependency. Digests are the
# release's own published digests (GitHub release assets[].digest); fetch them with
#   gh api repos/ggml-org/llama.cpp/releases/tags/<tag> --jq '.assets[]."name digest"'
# Bump this map together with config_defaults.local_runtime.tag — a tag with no entry here
# installs unpinned (trust-on-first-download), and the pin-map contract test fails the bump.
RUNTIME_ASSET_SHA256: dict[str, dict[str, str]] = {
    "b10964": {
        "cudart-llama-bin-win-cuda-13.3-x64.zip":
            "1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e",
        "cudart-llama-bin-win-cuda-13.4-arm64.zip":
            "642dcde8805b3e3165ca710a5443b3b4044b27d96bd3ee3132473988c9bcb774",
        "llama-b10964-bin-macos-arm64.tar.gz":
            "033c845c1df9bf945ff37bb193238b40910b2244be3e1e637b2ceb5878f1a6f5",
        "llama-b10964-bin-macos-x64.tar.gz":
            "03430a394d0a169a5e6d8f01c09f48cf58eb026af6fc95940a4a528e2e50cf38",
        "llama-b10964-bin-ubuntu-arm64.tar.gz":
            "5f0e9c95d970892e43380f82ebcab960edfd20a1cd0f7abffa13b29fdb924949",
        "llama-b10964-bin-ubuntu-rocm-10.0-x64.tar.gz":
            "162b9645b84fa0a354767ccb5379b1457701134dc1ff4cd8b0ecc5ccec248455",
        "llama-b10964-bin-ubuntu-vulkan-arm64.tar.gz":
            "f7864baa0edf5a059fb42c5efb5aceb96075aa1f41e6c3142b71ca69286cb0bb",
        "llama-b10964-bin-ubuntu-vulkan-x64.tar.gz":
            "55d1e58e14c11eedea090bf088fdeefbfe7b4b09ee03bf6dba9834651769afcf",
        "llama-b10964-bin-ubuntu-x64.tar.gz":
            "9abf88aea48a55d0f80edb1ee20220b186848cca0b4e919d71518cfd7ca67443",
        "llama-b10964-bin-win-cpu-arm64.zip":
            "4b6a004b076eea47c318bea35cf1db2ff2bf037738b04645646ae8d7c3159478",
        "llama-b10964-bin-win-cpu-x64.zip":
            "917f39c076402c421224824607397af20f53625a60defc20e8dd22446bf4c5d7",
        "llama-b10964-bin-win-cuda-13.3-x64.zip":
            "cd63ae76ad78a1540aa0f30f6c6284bab14c146d99a58f70c3f0a38cb9c62351",
        "llama-b10964-bin-win-cuda-13.4-arm64.zip":
            "93590d8c74fb2e729b06160b524ee06ebed2aed5619b8c8fbd52a431e453831c",
        "llama-b10964-bin-win-rocm-10.0-x64.zip":
            "1f75c2a7cc64b7d4ee30f1e5a65ebec3681e4a67be788fc7251abc898f98748e",
        "llama-b10964-bin-win-vulkan-x64.zip":
            "1ee3ad952f4ba71f438bd6d7bebef19e1c7af04adcaa35d08b4ddabb27d4c642",
    },
}


def pinned_assets(tag: str) -> dict[str, str]:
    """Shipped sha256 pins for ``tag``'s release assets (empty for unpinned tags)."""
    return RUNTIME_ASSET_SHA256.get(tag, {})


def resolve_assets(tag: str, backend: str, os_name: str | None = None,
                   arch: str | None = None) -> AssetPlan:
    """Compose the asset list for (tag, backend, platform). Raises BinaryResolutionError for pairs
    the release ships no artifact for; callers fall back down the ladder cuda -> vulkan -> cpu."""
    host_os, host_arch = _host_os_arch()
    os_name = os_name or host_os
    arch = arch or host_arch
    if os_name == "macos":
        # macOS tarballs are unified (Metal built in).
        return AssetPlan(tag, backend, [f"llama-{tag}-bin-macos-{arch}.tar.gz"])
    if os_name not in _ASSET_TEMPLATES:
        raise BinaryResolutionError(f"unsupported platform {os_name}-{arch}")
    if os_name == "ubuntu" and backend == "cuda":
        # No prebuilt Linux CUDA zips at current tags — Linux CUDA users build from source or
        # use vulkan; the resolver is honest about it.
        raise BinaryResolutionError(
            f"no prebuilt linux CUDA asset at {tag}; use vulkan/cpu or a source build")
    if os_name == "win" and backend == "vulkan" and arch == "arm64":
        raise BinaryResolutionError(f"no win-vulkan-arm64 asset at {tag}")
    label, templates = _ASSET_TEMPLATES[os_name]
    if backend not in templates:
        raise BinaryResolutionError(f"unsupported {label} backend {backend}")
    # release.yml switched both HIP names at b10356 (0666ad2b2b), then
    # ROCm 7.14 -> 10.0 at b10767 (cff184438e). Keep older explicit pins.
    if backend == "hip" and tag.startswith("b") and tag[1:].isascii() and tag[1:].isdigit():
        build = int(tag[1:])
        if build >= 10356:
            if arch != "x64":
                raise BinaryResolutionError(f"no {label} HIP {arch} asset at {tag}")
            rocm_ver = "10.0" if build >= 10767 else "7.14"
            extension = "zip" if os_name == "win" else "tar.gz"
            return AssetPlan(tag, backend, [
                f"llama-{tag}-bin-{os_name}-rocm-{rocm_ver}-{arch}.{extension}"])
    cuda_ver = _WIN_CUDA_VERSION_ARM64 if arch == "arm64" else _WIN_CUDA_VERSION
    return AssetPlan(tag, backend, [t.format(tag=tag, arch=arch, cuda_ver=cuda_ver)
                                    for t in templates[backend]])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path,
              progress: "Callable[[int, int], None] | None" = None) -> None:
    """Stream url -> dest. ``progress(done_bytes, total_bytes)`` ticks per chunk (total 0 when
    the server sends no Content-Length) — a several-hundred-MB archive must never look hung."""
    logger.info("downloading %s", url)
    staging = tempfile.NamedTemporaryFile(
        mode="wb", dir=dest.parent, prefix=f"{dest.name}.", suffix=".part", delete=False)
    tmp = Path(staging.name)
    try:
        with staging as f, urllib.request.urlopen(url, timeout=120) as r:
            length = r.headers.get("Content-Length")
            total = int(length) if length is not None else 0
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
            # Chunked reads can return EOF without raising IncompleteRead.
            if length is not None and done != total:
                raise BinaryResolutionError(
                    f"incomplete download for {dest.name}: expected {total} bytes, got {done}")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _extract(archive: Path, dest: Path,
             progress: "Callable[[int, int], None] | None" = None) -> None:
    """Extract member by member so ``progress(done, total)`` can tick in uncompressed bytes."""
    if archive.name.endswith(".zip"):
        opener, list_members, size = zipfile.ZipFile, "infolist", "file_size"
        kwargs = {}
    else:
        import tarfile
        opener, list_members, size = tarfile.open, "getmembers", "size"
        kwargs = {"filter": "data"}
    with opener(archive) as ar:
        members = getattr(ar, list_members)()
        total = sum(getattr(m, size) for m in members)
        done = 0
        for m in members:
            ar.extract(m, dest, **kwargs)
            done += getattr(m, size)
            if progress is not None:
                progress(done, total)


def server_binary(install_dir: Path) -> Path:
    """Locate llama-server within an extracted runtime (zips differ in whether they nest a
    build/bin directory)."""
    names = ("llama-server.exe", "llama-server")
    for name in names:
        direct = install_dir / name
        if direct.exists():
            return direct
    for name in names:
        hits = sorted(install_dir.rglob(name))
        if hits:
            return hits[0]
    raise BinaryResolutionError(f"llama-server not found under {install_dir}")


def verify_install(install_dir: Path, tag: str) -> str:
    """Run --version; require the tag's build number in the output (printed WITHOUT the 'b')."""
    exe = server_binary(install_dir)
    out = subprocess.run([str(exe), "--version"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         timeout=60, cwd=str(exe.parent))
    text = (out.stdout + out.stderr).strip()
    if tag.lstrip("b") not in text:
        raise BinaryResolutionError(
            f"version check failed for {exe}: expected {tag}, got: {text[:120]}")
    return text.splitlines()[0] if text else ""


def prune_old_tags(keep: list[str]) -> None:
    """Retain only the tags in ``keep`` (current + previous — N-1 rollback). The shared
    ``downloads/`` archive cache is not a tag and always survives."""
    root = runtimes_root()
    if not root.exists():
        return
    for entry in root.iterdir():
        if entry.is_dir() and entry.name != "downloads" and entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)
            logger.info("pruned old runtime %s", entry.name)


def ensure_runtime_installed(tag: str, backend: str,
                             expected_sha256: dict[str, str] | None = None,
                             progress: "Callable[[str, int, int, str], None] | None" = None) -> Path:
    """Idempotent: resolve, download, verify, extract, version-check; returns the install dir.
    ``expected_sha256`` pins hashes per asset and OVERRIDES the shipped pin map
    (``RUNTIME_ASSET_SHA256``); by default the map pins the release Hermes ships, so no
    call site can forget. For a tag with no pins at all the computed hash is recorded in the
    manifest (trust on first download, verified on every reinstall). ``progress(stage, done,
    total, label)`` ticks through download/extract/verify."""
    plan = resolve_assets(tag, backend)
    install_dir = plan.install_dir
    manifest_path = install_dir / "manifest.json"
    if manifest_verified(manifest_path):
        return install_dir

    install_dir.mkdir(parents=True, exist_ok=True)
    downloads = runtimes_root() / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    def stage_progress(stage: str, label: str):
        if progress is None:
            return None
        tick = progress
        return lambda d, t: tick(stage, d, t, label)

    pins = expected_sha256 if expected_sha256 is not None else pinned_assets(tag)
    recorded: dict[str, str] = {}
    n_assets = len(plan.assets)
    for i, asset in enumerate(plan.assets, 1):
        label = f"{i}/{n_assets}" if n_assets > 1 else ""
        archive = downloads / asset
        if not archive.exists():
            _download(RELEASE_URL.format(tag=tag, asset=asset), archive,
                      progress=stage_progress("download", label))
        if progress is not None:
            progress("verify", 0, 0, label)
        digest = _sha256(archive)
        expected = pins.get(asset)
        if expected and digest != expected:
            archive.unlink(missing_ok=True)
            raise BinaryResolutionError(
                f"sha256 mismatch for {asset}: expected {expected}, got {digest}")
        recorded[asset] = digest
        _extract(archive, install_dir, progress=stage_progress("extract", label))

    if progress is not None:
        progress("verify", 0, 0, "")
    version = verify_install(install_dir, tag)
    manifest_path.write_text(json.dumps({"tag": tag, "backend": plan.backend, "assets": recorded,
                                         "verified_version": version}, indent=2), encoding="utf-8")
    logger.info("installed llama.cpp %s (%s): %s", tag, backend, version)
    return install_dir


# ---- BEGIN PLUGIN-COMPAT (revert-scheduled; see COMPAT_MANIFEST.md) ----
# Names external plugins imported from this module before the Sep 2026 decomposition.
# Internal code MUST NOT use these (scripts/check_compat_pointers.py fails CI if it does).
# The whole block is removed by reverting the commit that added it.


_PLUGIN_COMPAT_LAZY = {
    'get_hermes_home': ('hermes_constants', 'get_hermes_home'),
}


def __getattr__(name):  # PEP 562 — lazy so no import cycles
    target = _PLUGIN_COMPAT_LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    from hermes_cli.plugin_compat import warn_once
    warn_once(__name__, name, *target)
    return getattr(importlib.import_module(target[0]), target[1])
# ---- END PLUGIN-COMPAT ----
