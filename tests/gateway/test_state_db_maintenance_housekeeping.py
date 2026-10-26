"""The state.db maintenance chore retires expired turn leases unconditionally.

Auto-archive/auto-prune are retention settings; lease hygiene is not. The chore used to
return before touching the store at all unless one of them was enabled, so a quiescent
profile (neither enabled, no conversation acquiring a lease) never retired the
``session_turn_leases`` rows of holders killed without releasing — residue that stands
forever on a long-lived host. The sweep predicate itself lives with the lease machinery
(``tests/hermes_state/test_session_turn_lease.py``); these tests pin the wiring: every
maintenance call sweeps, prunes stale gateway-heartbeat tombstones with the shared window
policy (``backend_heartbeat_prune_max_age`` — the same residue class, for backends that
died without an orderly exit), the gated retention chores still gate (after both), and the
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
    """Replace the registry seam with one recording fake store; returns (db, released)."""
    import hermes_state_registry as registry

    db = SimpleNamespace(
        sweep_expired_turn_leases=lambda: calls.append("sweep") or 0,
        prune_stale_heartbeats=lambda **kw: calls.append("hb-prune") or [],
        maybe_auto_archive=lambda **kw: calls.append("archive"),
        maybe_auto_prune_and_vacuum=lambda **kw: calls.append("prune"))
    released = []
    monkeypatch.setattr(registry, "acquire", lambda *a, **k: db)
    monkeypatch.setattr(registry, "release_or_close", released.append)
    return db, released


def test_maintenance_sweeps_turn_leases_with_retention_disabled(monkeypatch):
    """Neither auto_archive nor auto_prune: the chore still opens the store, sweeps expired
    leases, prunes stale heartbeat tombstones and releases the handle. (On the pre-change
    base this early-returned before the acquire at all.)"""
    import hermes_cli.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {"sessions": {}})
    calls: list = []
    db, released = _patch_store_seam(monkeypatch, calls)

    gateway_run._housekeeping_state_db_maintenance()

    assert calls == ["sweep", "hb-prune"]
    assert released == [db]


def test_maintenance_sweeps_before_the_gated_retention_chores(monkeypatch):
    """With retention enabled both hygiene calls still run, first, and archive/prune keep their
    gates."""
    import hermes_cli.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {"sessions": {
        "auto_archive": True, "auto_prune": True, "min_interval_hours": 0}})
    calls: list = []
    db, released = _patch_store_seam(monkeypatch, calls)

    gateway_run._housekeeping_state_db_maintenance()

    assert calls == ["sweep", "hb-prune", "archive", "prune"]
    assert released == [db]


def test_maintenance_prunes_stale_heartbeats_with_derived_window(monkeypatch):
    """The tombstone prune derives its window from the same HERMES_GATEWAY_HEARTBEAT_REFRESH_S
    the backend refresher reads: 15 missed refresh beats at a 120 s interval → a 1800 s window
    (the 900 s floor governs at the 60 s default)."""
    import hermes_cli.config as config_mod
    import hermes_state_registry as registry

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {"sessions": {}})
    monkeypatch.setenv("HERMES_GATEWAY_HEARTBEAT_REFRESH_S", "120")
    prune_kwargs: dict = {}
    db = SimpleNamespace(
        sweep_expired_turn_leases=lambda: 0,
        prune_stale_heartbeats=lambda **kw: prune_kwargs.update(kw) or [],
        maybe_auto_archive=lambda **kw: None,
        maybe_auto_prune_and_vacuum=lambda **kw: None)
    released = []
    monkeypatch.setattr(registry, "acquire", lambda *a, **k: db)
    monkeypatch.setattr(registry, "release_or_close", released.append)

    gateway_run._housekeeping_state_db_maintenance()

    assert prune_kwargs == {"max_age_seconds": 1800.0}
    assert released == [db]


def test_maintenance_isolates_prune_failure_from_retention_gates(monkeypatch):
    """Never-raise contract: a heartbeat prune the store refuses (locked db) neither propagates
    out of the chore nor skips the gated retention chores or the release behind it."""
    import hermes_cli.config as config_mod
    import hermes_state_registry as registry

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {"sessions": {
        "auto_archive": True, "auto_prune": True, "min_interval_hours": 0}})
    calls: list = []

    def _refusing_prune(**kw):
        calls.append("hb-prune")
        raise RuntimeError("database is locked")

    db = SimpleNamespace(
        sweep_expired_turn_leases=lambda: calls.append("sweep") or 0,
        prune_stale_heartbeats=_refusing_prune,
        maybe_auto_archive=lambda **kw: calls.append("archive"),
        maybe_auto_prune_and_vacuum=lambda **kw: calls.append("prune"))
    released = []
    monkeypatch.setattr(registry, "acquire", lambda *a, **k: db)
    monkeypatch.setattr(registry, "release_or_close", released.append)

    gateway_run._housekeeping_state_db_maintenance()

    assert calls == ["sweep", "hb-prune", "archive", "prune"]
    assert released == [db]


def test_state_db_maintenance_rides_the_housekeeping_tick(monkeypatch):
    """One full cadence of the housekeeping loop (60 ticks, no sleeping) reaches the state.db
    maintenance chore through the chore table — the wiring that makes the sweep periodic and
    workload-independent."""
    seen = []
    monkeypatch.setattr(
        gateway_run, "_housekeeping_state_db_maintenance", lambda *a, **k: seen.append(a))

    gateway_run._start_gateway_housekeeping(_Ticks(60), interval=0)

    assert len(seen) == 1
