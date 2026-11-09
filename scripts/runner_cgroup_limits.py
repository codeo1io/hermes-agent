"""Worker-bound derivation for ``run_tests_parallel``: cgroup cpu/pids limits,
the HERMES_TEST_WORKERS override and the default-workers computation.

Split out of ``scripts/run_tests_parallel.py`` (code-health FILE_LINES); moved
code keeps its lint caps (root AGENTS.md). Pure helpers over injectable paths.

The tests drive these against fixture cgroup trees instead of the live host;
every read fail-opens to "no limit" (missing file, wrong shape, "max", no
cgroups).
"""

from __future__ import annotations

import math
import os
import warnings
from pathlib import Path
from typing import Optional

# no config knob. Systemd TasksMax sizing itself stays the ops lane.
_CGROUP_V2_MOUNT_ROOT = "/sys/fs/cgroup"  # monkeypatch/inject in tests
_PROC_SELF_CGROUP = "/proc/self/cgroup"

# Static pids ceiling: never plan more than 1/32 of pids.max in workers
# alone (16 concurrent sessions × 768/32 = 384 planned processes — an
# order below a TasksMax of 768).
_PIDS_STATIC_DIVISOR = 32

# Live headroom: a starting runner claims at most 1/8 of the pids budget
# still free, so a fleet already nearing pids.max progressively starves
# new fan-outs instead of tripping EAGAIN mid-suite. Read once at start.
_PIDS_HEADROOM_DIVISOR = 8


# All helpers below are pure over injectable paths so tests can drive them
# against fixture cgroup trees instead of the live host; every read
# fail-opens to "no limit" (missing file, wrong shape, "max", no cgroups).


def _read_text(path) -> Optional[str]:
    """File content, or None — an unreadable file means "no truth", never
    an error: each term of the worker bound is independently optional."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _read_int_file(path) -> Optional[int]:
    """A single-int cgroup file ("768\n") as an int; "max", empty or
    malformed content → None (treated as no limit)."""
    text = _read_text(path)
    if text is None:
        return None
    value = text.strip()
    if not value or value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_cpu_max(content: str) -> Optional[float]:
    """A cgroup v2 ``cpu.max`` value ("<quota> <period>") as CPU cores
    ("600000 100000" → 6.0). "max <period>", malformed, or non-positive
    numbers → None (no limit)."""
    parts = content.split()
    if len(parts) != 2:
        return None
    quota_str, period_str = parts
    if quota_str == "max":
        return None
    try:
        quota, period = int(quota_str), int(period_str)
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return quota / period


def _scan_cgroup_node(node: Path) -> tuple[Optional[float], Optional[int], Optional[int]]:
    """One cgroup dir's (cpu cores, pids.max, pids.current), each fail-open.

    v1 quota files are read alongside v2 ``cpu.max`` because a node only
    ever carries one shape — the absent one reads as None and is skipped.
    pids.current is only meaningful at a level that has pids.max (v2
    accounts the whole subtree there), so it is None when pids.max is.
    """
    cores = _parse_cpu_max(_read_text(node / "cpu.max") or "")
    quota = _read_int_file(node / "cpu.cfs_quota_us")  # v1: -1 = unlimited
    period = _read_int_file(node / "cpu.cfs_period_us")
    if quota is not None and quota > 0 and period is not None and period > 0:
        v1 = quota / period
        cores = v1 if cores is None else min(cores, v1)
    pids_max = _read_int_file(node / "pids.max")
    pids_current = _read_int_file(node / "pids.current") if pids_max is not None else None
    return cores, pids_max, pids_current


def _resolve_self_cgroup_dir(
    proc_self_cgroup: Optional[str] = None,
    mount_root: Optional[str] = None,
) -> Optional[Path]:
    """This process's cgroup v2 dir (the "0::<rel>" line of
    /proc/self/cgroup) under mount_root; a "/" relpath resolves to the
    mount root itself. None when the file is absent or the host has no
    unified hierarchy (cgroup v1) — callers fall back to per-controller
    mounts or skip the axis entirely."""
    if proc_self_cgroup is None:
        proc_self_cgroup = _PROC_SELF_CGROUP
    if mount_root is None:
        mount_root = _CGROUP_V2_MOUNT_ROOT
    for line in (_read_text(proc_self_cgroup) or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            rel = parts[2].strip("/")
            return Path(mount_root) if not rel else Path(mount_root) / rel
    return None


def _cgroup_chain_limits(
    proc_self_cgroup: Optional[str] = None,
    mount_root: Optional[str] = None,
) -> tuple[Optional[float], Optional[int], Optional[int]]:
    """The most-binding (cpu cores, pids.max, pids.current) over this
    process's cgroup dir and every ancestor up to the mount root.

    v2 primary (unified hierarchy); on a v1 host, best-effort walk of the
    ``cpu``/``pids`` controller mounts named in /proc/self/cgroup. An
    axis that cannot be resolved is None — the derivation fail-opens to
    the remaining terms. pids.current is taken from the deepest level
    that carries pids.max."""
    if proc_self_cgroup is None:
        proc_self_cgroup = _PROC_SELF_CGROUP
    if mount_root is None:
        mount_root = _CGROUP_V2_MOUNT_ROOT
    mount = Path(mount_root)
    chains = []  # (deepest dir, chain root) pairs to walk upward through
    v2_dir = _resolve_self_cgroup_dir(proc_self_cgroup, mount_root)
    if v2_dir is not None:
        chains.append((v2_dir, mount))
    else:
        for line in (_read_text(proc_self_cgroup) or "").splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3 or not parts[1]:
                continue
            for controller in parts[1].split(","):
                if controller in ("cpu", "pids"):
                    base = mount / controller
                    rel = parts[2].strip("/")
                    chains.append((base if not rel else base / rel, base))
    cpu_ceiling: Optional[float] = None
    pids_max: Optional[int] = None
    pids_current: Optional[int] = None
    for deepest, chain_root in chains:
        node = deepest
        while True:
            cores, node_pids_max, node_pids_current = _scan_cgroup_node(node)
            if cores is not None:
                cpu_ceiling = cores if cpu_ceiling is None else min(cpu_ceiling, cores)
            if node_pids_max is not None:
                pids_max = node_pids_max if pids_max is None else min(pids_max, node_pids_max)
                if pids_current is None and node_pids_current is not None:
                    pids_current = node_pids_current
            if node == chain_root or node.parent == node:
                break
            node = node.parent
    return cpu_ceiling, pids_max, pids_current


def _derive_default_workers(
    cpu_count: Optional[int] = None,
    limits: Optional[tuple[Optional[float], Optional[int], Optional[int]]] = None,
    proc_self_cgroup: Optional[str] = None,
    mount_root: Optional[str] = None,
) -> int:
    """The default worker bound: min of legacy cpu_count*2, the cgroup cpu
    ceiling (ceil of cores), pids.max/_PIDS_STATIC_DIVISOR, and live
    (pids_max - pids_current)/_PIDS_HEADROOM_DIVISOR — floored at 1. Terms
    with no readable truth are skipped (fail-open)."""
    if cpu_count is None:
        cpu_count = os.cpu_count() or 4
    if limits is None:
        limits = _cgroup_chain_limits(proc_self_cgroup, mount_root)
    cpu_ceiling, pids_max, pids_current = limits
    candidates = [cpu_count * 2]
    if cpu_ceiling is not None and cpu_ceiling > 0:
        candidates.append(math.ceil(cpu_ceiling))
    if pids_max is not None and pids_max > 0:
        candidates.append(pids_max // _PIDS_STATIC_DIVISOR)
        if pids_current is not None:
            candidates.append(max(0, pids_max - pids_current) // _PIDS_HEADROOM_DIVISOR)
    return max(1, min(candidates))


def _env_workers_override(env: Optional[dict[str, str]] = None) -> Optional[int]:
    """HERMES_TEST_WORKERS as a positive int, or None (unset, malformed, or
    non-positive — tolerant so one bad value can't crash main() at
    argparse-default time; mirrors agent/pi_rpc_client._env_float)."""
    source = os.environ if env is None else env
    raw = str(source.get("HERMES_TEST_WORKERS", "")).strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        warnings.warn(
            f"Ignoring malformed HERMES_TEST_WORKERS={raw!r}; using the derived default",
            stacklevel=2,
        )
        return None
    if value <= 0:
        warnings.warn(
            f"Ignoring non-positive HERMES_TEST_WORKERS={raw!r}; using the derived default",
            stacklevel=2,
        )
        return None
    return value
