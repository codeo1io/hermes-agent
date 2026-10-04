"""Cgroup-derived default worker bound in scripts/run_tests_parallel.py.

Regression for the 2026-10 conductor fleet incident (finding
c79c00499868, family cognitive-continuity.prevention.037be2ceb13fb32534e92b08;
emergency repair 678dc4e259f96 restored service, this is the structural
fix): many concurrent test sessions run inside one systemd unit sharing a
single pids budget (TasksMax=768). The old default — cpu_count()*2 per
session — let each session plan ~2×cores pytest subprocesses, so a busy
fleet pushed the shared budget past pids.max and every further spawn died
with EAGAIN: tests dispatch but never run, and CPU starvation stalls the
watchers (turns time out, leases expire). The default is now derived from
the same numbers the kernel enforces — min(legacy cpu_count*2, most-binding
cpu.max over the self→root chain, pids.max/32, live (pids.max -
pids.current)/8) — failing open to plain cpu_count*2 when no cgroup truth
is readable.

Every test drives the pure injectable helpers over tmp_path fixture
cgroup trees, never the live /sys/fs/cgroup: the incident only exists
under an ambient cgroup, so the arithmetic must not depend on the host
happening to have one. cpu_count is injected (14 → legacy 28) for the
same reason.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_PATH = REPO_ROOT / "scripts" / "run_tests_parallel.py"

# Injected cpu_count: legacy term = 28 on every host, matching the plan's
# worked examples. Never read the real os.cpu_count() in these tests.
_CPU = 14
_LEGACY = _CPU * 2


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_tests_parallel", _RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _node(
    dirpath: Path,
    cpu_max: Optional[str] = None,
    pids_max: Optional[str] = None,
    pids_current: Optional[str] = None,
    v1_quota: Optional[str] = None,
    v1_period: Optional[str] = None,
) -> None:
    """Materialize one cgroup dir's control files (absent kwarg = absent file)."""
    dirpath.mkdir(parents=True, exist_ok=True)
    if cpu_max is not None:
        (dirpath / "cpu.max").write_text(cpu_max)
    if pids_max is not None:
        (dirpath / "pids.max").write_text(pids_max)
    if pids_current is not None:
        (dirpath / "pids.current").write_text(pids_current)
    if v1_quota is not None:
        (dirpath / "cpu.cfs_quota_us").write_text(v1_quota)
    if v1_period is not None:
        (dirpath / "cpu.cfs_period_us").write_text(v1_period)


def _v2_tree(
    tmp_path: Path,
    name: str,
    unit: Optional[Dict[str, str]] = None,
    ancestor: Optional[Dict[str, str]] = None,
    unit_rel: str = "unit.slice",
) -> Tuple[Path, Path]:
    """A cgroup v2 fixture: a mount root (ancestor files at the root itself)
    with one unit dir below it, plus a /proc/self/cgroup lookalike naming
    the unit. Returns (proc_file, mount_root)."""
    root = tmp_path / name
    _node(root, **(ancestor or {}))
    _node(root / unit_rel, **(unit or {}))
    proc = tmp_path / f"{name}.cgroup"
    proc.write_text(f"0::/{unit_rel}\n")
    return proc, root


def test_no_cgroup_truth_keeps_legacy_default(tmp_path: Path) -> None:
    """Bare metal / exotic sandbox: no readable cgroup at all degrades to
    the legacy cpu_count*2 default — never to an error."""
    runner = _load_runner()
    proc = tmp_path / "absent.cgroup"  # never written
    root = tmp_path / "absent-root"
    assert runner._cgroup_chain_limits(proc, root) == (None, None, None)
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == _LEGACY
    )


def test_cpu_quota_binds(tmp_path: Path) -> None:
    """An ancestor quota of 6 cores caps the fan-out at 6 workers even
    though cpu_count*2 would plan 28."""
    runner = _load_runner()
    proc, root = _v2_tree(tmp_path, "quota", ancestor={"cpu_max": "600000 100000"})
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 6
    )


def test_cpu_max_unlimited_is_skipped(tmp_path: Path) -> None:
    """"max 100000" means no CPU limit — the term must not bind."""
    runner = _load_runner()
    proc, root = _v2_tree(tmp_path, "unlimited", ancestor={"cpu_max": "max 100000"})
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == _LEGACY
    )


def test_most_binding_limit_across_the_chain(tmp_path: Path) -> None:
    """The chain resolves to its most-binding member: an ancestor limit
    beats the unit's own looser one, and a limit only the ancestor carries
    still applies to the unit."""
    runner = _load_runner()
    proc, root = _v2_tree(
        tmp_path,
        "chain",
        unit={"cpu_max": "1200000 100000"},  # unit allows 12
        ancestor={"cpu_max": "600000 100000"},  # ancestor allows 6
    )
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 6
    )
    proc, root = _v2_tree(tmp_path, "chain-ancestor-only", ancestor={"cpu_max": "400000 100000"})
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 4
    )


def test_pids_static_ceiling(tmp_path: Path) -> None:
    """pids.max=768 alone caps workers at 768//32 = 24 — one session never
    plans more than ~3% of the shared task budget by itself."""
    runner = _load_runner()
    proc, root = _v2_tree(tmp_path, "static", unit={"pids_max": "768"})
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 24
    )


def test_pids_live_headroom_bounds(tmp_path: Path) -> None:
    """With 640 of 768 tasks already committed, a new session plans at most
    (768-640)//8 = 16 workers — concurrent sessions bound each other
    through the shared pids.current instead of racing past pids.max."""
    runner = _load_runner()
    proc, root = _v2_tree(
        tmp_path, "headroom", unit={"pids_max": "768", "pids_current": "640"}
    )
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 16
    )


def test_headroom_exhausted_clamps_to_one_worker(tmp_path: Path) -> None:
    """765 of 768 used → headroom 0 → floor of 1, not 0: serial, but alive."""
    runner = _load_runner()
    proc, root = _v2_tree(
        tmp_path, "exhausted", unit={"pids_max": "768", "pids_current": "765"}
    )
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 1
    )


def test_explicit_env_is_a_hard_override(tmp_path: Path) -> None:
    """HERMES_TEST_WORKERS escapes every cgroup cap (the documented escape
    hatch) even when the fixture alone would clamp the run to 1."""
    runner = _load_runner()
    proc, root = _v2_tree(
        tmp_path, "override", unit={"pids_max": "16", "pids_current": "16"}
    )
    limits = runner._cgroup_chain_limits(proc, root)
    assert runner._derive_default_workers(cpu_count=_CPU, limits=limits) == 1
    assert (
        runner._default_jobs(
            env={"HERMES_TEST_WORKERS": "3"}, cpu_count=_CPU, limits=limits
        )
        == 3
    )


def test_malformed_files_fail_open(tmp_path: Path) -> None:
    """Garbage control files mean "no truth", not "zero budget": each term
    skips independently and the default falls back to legacy."""
    runner = _load_runner()
    proc, root = _v2_tree(
        tmp_path, "malformed", unit={"cpu_max": "garbage", "pids_max": ""}
    )
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == _LEGACY
    )


def test_v1_fallback_quota(tmp_path: Path) -> None:
    """On a cgroup v1 host the cpu controller mount still binds: quota
    200000/period 100000 → 2 workers (ancestor -1 = unlimited is skipped)."""
    runner = _load_runner()
    root = tmp_path / "v1"
    _node(root / "cpu" / "unit.slice", v1_quota="200000", v1_period="100000")
    _node(root / "cpu", v1_quota="-1", v1_period="100000")
    proc = tmp_path / "v1.cgroup"
    proc.write_text("3:cpu,cpuacct:/unit.slice\n5:pids:/unit.slice\n")
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 2
    )


def test_hybrid_cgroup_walks_v1_controllers(tmp_path: Path) -> None:
    """systemd hybrid host: the unified hierarchy exists (0:: line
    present) but is unlimited, while cpu/pids live on v1 controller
    mounts. Walking only v2 derives no limits and the ceiling silently
    no-ops to cpu_count*2 — the exact fleet incident mode. The v1 cpu
    quota (2.0 cores) must bind through the v2 shadow."""
    runner = _load_runner()
    root = tmp_path / "hybrid"
    _node(root / "unit.slice")  # v2 dir exists, carries no limit files
    _node(root / "cpu" / "unit.slice", v1_quota="200000", v1_period="100000")
    proc = tmp_path / "hybrid.cgroup"
    proc.write_text("0::/unit.slice\n3:cpu,cpuacct:/unit.slice\n5:pids:/unit.slice\n")
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 2
    )


def test_hybrid_v1_pids_max_binds(tmp_path: Path) -> None:
    """Hybrid host, pids side: TasksMax on the v1 pids mount (768) must
    yield the pids.max//32 term (24) even though the v2 chain is present
    and unlimited."""
    runner = _load_runner()
    root = tmp_path / "hybrid-pids"
    _node(root / "unit.slice")
    _node(root / "pids" / "unit.slice", pids_max="768")
    proc = tmp_path / "hybrid-pids.cgroup"
    proc.write_text("0::/unit.slice\n3:cpu,cpuacct:/unit.slice\n5:pids:/unit.slice\n")
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 24
    )


def test_hybrid_most_binding_across_both_hierarchies(tmp_path: Path) -> None:
    """When BOTH hierarchies carry a cpu limit, the tighter one wins
    (v2 2.0 cores vs v1 4.0 → 2): the hybrid fix widens the chain set,
    never loosens the binding."""
    runner = _load_runner()
    root = tmp_path / "hybrid-both"
    _node(root / "unit.slice", cpu_max="200000 100000")
    _node(root / "cpu" / "unit.slice", v1_quota="400000", v1_period="100000")
    proc = tmp_path / "hybrid-both.cgroup"
    proc.write_text("0::/unit.slice\n3:cpu,cpuacct:/unit.slice\n5:pids:/unit.slice\n")
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == 2
    )


def test_env_garbage_falls_through_to_derivation(tmp_path: Path) -> None:
    """One malformed env value costs its override, not the run: base
    crashed with ValueError at argparse-default time."""
    runner = _load_runner()
    proc, root = _v2_tree(tmp_path, "garbage", unit={"pids_max": "768"})
    limits = runner._cgroup_chain_limits(proc, root)
    with pytest.warns(UserWarning, match="HERMES_TEST_WORKERS"):
        jobs = runner._default_jobs(
            env={"HERMES_TEST_WORKERS": "abc"}, cpu_count=_CPU, limits=limits
        )
    assert jobs == 24  # the pids.max//32 term, override ignored


def test_pids_current_without_max_is_ignored(tmp_path: Path) -> None:
    """Headroom is only defined against a readable pids.max; a lone
    pids.current must not manufacture a bound."""
    runner = _load_runner()
    proc, root = _v2_tree(tmp_path, "orphan-current", unit={"pids_current": "700"})
    assert (
        runner._derive_default_workers(
            cpu_count=_CPU, proc_self_cgroup=proc, mount_root=root
        )
        == _LEGACY
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3", 3),
        ("  8  ", 8),  # tolerant of surrounding whitespace
        ("", None),
        ("abc", None),
        ("0", None),
        ("-4", None),
        ("2.5", None),
    ],
)
def test_env_workers_override_tolerant_parse(raw: str, expected: Optional[int]) -> None:
    """The override parses tolerantly (mirrors agent/pi_rpc_client._env_float):
    unset/malformed/non-positive → None (warn + derive), never a crash."""
    runner = _load_runner()
    env = {"HERMES_TEST_WORKERS": raw}
    if expected is None and raw:
        with pytest.warns(UserWarning, match="HERMES_TEST_WORKERS"):
            got = runner._env_workers_override(env)
    else:
        got = runner._env_workers_override(env)
    assert got == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("600000 100000", 6.0),
        ("150000 100000", 1.5),
        ("max 100000", None),  # unlimited
        ("garbage", None),  # not two tokens
        ("600000", None),  # missing period
        ("-600000 100000", None),  # non-positive quota
        ("600000 0", None),  # non-positive period
    ],
)
def test_parse_cpu_max_shapes(content: str, expected: Optional[float]) -> None:
    runner = _load_runner()
    assert runner._parse_cpu_max(content) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("768\n", 768),
        ("  64  ", 64),
        ("max", None),
        ("", None),
        ("7.5", None),
    ],
)
def test_read_int_file_shapes(tmp_path: Path, content: str, expected: Optional[int]) -> None:
    runner = _load_runner()
    f = tmp_path / "control"
    f.write_text(content)
    assert runner._read_int_file(f) == expected
    assert runner._read_int_file(tmp_path / "missing") is None  # fail-open on absent


def test_main_wires_derived_default_into_jobs_and_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end through main() against a fixture cgroup: the argparse
    --jobs DEFAULT (no -j, no env) is the cgroup-derived bound, the run
    completes, and the reduction is announced on stderr with the numbers
    that caused it — a silently smaller fan-out would read as a runner
    regression. min(legacy 28, 768//32=24, (768-640)//8=16) = 16."""
    runner = _load_runner()
    suite = tmp_path / "tiny-suite"
    suite.mkdir()
    (suite / "test_smoke.py").write_text(
        "def test_ok() -> None:\n    assert True\n"
    )
    proc, root = _v2_tree(
        tmp_path, "wiring", unit={"pids_max": "768", "pids_current": "640"}
    )
    monkeypatch.setattr(runner, "_PROC_SELF_CGROUP", str(proc))
    monkeypatch.setattr(runner, "_CGROUP_V2_MOUNT_ROOT", str(root))
    monkeypatch.setattr("os.cpu_count", lambda: _CPU)
    monkeypatch.delenv("HERMES_TEST_WORKERS", raising=False)
    monkeypatch.setattr(sys, "argv", [str(_RUNNER_PATH), "--paths", str(suite)])

    assert runner.main() == 0

    out, err = capsys.readouterr()
    assert "running with -j 16" in out
    assert "cgroup bounds: 28 → 16 workers" in err
    assert "pids.max=768 pids.current=640" in err
    assert "override: -j or HERMES_TEST_WORKERS" in err
