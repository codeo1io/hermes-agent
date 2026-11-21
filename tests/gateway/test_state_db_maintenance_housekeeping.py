"""The state.db maintenance chore retires expired turn leases unconditionally.

Auto-archive/auto-prune are retention settings; lease hygiene is not. The chore used to
return before touching the store at all unless one of them was enabled, so a quiescent
profile (neither enabled, no conversation acquiring a lease) never retired the
``session_turn_leases`` rows of holders killed without releasing — residue that stands
forever on a long-lived host. The sweep predicate itself lives with the lease machinery
(``tests/hermes_state/test_session_turn_lease.py``); these tests pin the wiring: every
maintenance call sweeps, the gated retention chores still gate (after the sweep), and the
60s housekeeping tick still reaches the chore.
"""

from types import SimpleNamespace

import gateway.run as gateway_run


class _Ticks:
    """Stop event that lets the housekeeping loop run exactly ``n`` ticks with no sleeping."""

    def __init__(self, n: int):
        self.n, self.left = 0, n

    def is_set(self):
        return self.n >= self.left

    def wait(self, timeout=None):
        self.n += 1
        return True


def _patch_store_seam(monkeypatch, calls: list):
    """Replace the persistence seam with one recording fake store; returns (store, closed).

    Ported from the pre-0.23.3 registry seam (``hermes_state_registry.acquire`` /
    ``release_or_close``) onto the 0.23.3 assembly: the chore opens the profile's store
    through ``persistence_assembly.open_persistence``, sweeps via
    ``store.coordination.sweep_expired_turn_leases()`` and closes the handle itself."""
    import persistence_assembly as assembly
    import session_retention as retention

    store = SimpleNamespace(
        coordination=SimpleNamespace(
            sweep_expired_turn_leases=lambda: calls.append("sweep") or 0),
        close=lambda: closed.append(store))
    closed = []
    scope = SimpleNamespace(profile_dir="/tmp/fake-profile")
    monkeypatch.setattr(assembly, "profile_scope", lambda *a, **k: scope)
    monkeypatch.setattr(assembly, "open_persistence", lambda scope, *, eager=False: store)
    monkeypatch.setattr(assembly, "open_store_admin",
                        lambda scope, *, read_only=False: SimpleNamespace())
    monkeypatch.setattr(retention, "run_auto_archive", lambda *a, **k: calls.append("archive"))
    monkeypatch.setattr(retention, "run_auto_prune_and_vacuum", lambda *a, **k: calls.append("prune"))
    return store, closed


def test_maintenance_sweeps_turn_leases_with_retention_disabled(monkeypatch):
    """Neither auto_archive nor auto_prune: the chore still opens the store, sweeps expired
    leases and releases the handle. (On the pre-change base this early-returned before the
    acquire at all.)"""
    import hermes_cli.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {"sessions": {}})
    calls: list = []
    store, closed = _patch_store_seam(monkeypatch, calls)

    gateway_run._housekeeping_state_db_maintenance()

    assert calls == ["sweep"]
    assert closed == [store]


def test_maintenance_sweeps_before_the_gated_retention_chores(monkeypatch):
    """With retention enabled the sweep still runs, first, and archive/prune keep their gates."""
    import hermes_cli.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {"sessions": {
        "auto_archive": True, "auto_prune": True, "min_interval_hours": 0}})
    calls: list = []
    store, closed = _patch_store_seam(monkeypatch, calls)

    gateway_run._housekeeping_state_db_maintenance()

    assert calls == ["sweep", "archive", "prune"]
    assert closed == [store]


def test_state_db_maintenance_rides_the_housekeeping_tick(monkeypatch):
    """One full cadence of the housekeeping loop (60 ticks, no sleeping) reaches the state.db
    maintenance chore through the chore table — the wiring that makes the sweep periodic and
    workload-independent."""
    seen = []
    monkeypatch.setattr(
        gateway_run, "_housekeeping_state_db_maintenance", lambda *a, **k: seen.append(a))

    gateway_run._start_gateway_housekeeping(_Ticks(60), interval=0)

    assert len(seen) == 1
