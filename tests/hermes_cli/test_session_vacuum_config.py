from pathlib import Path
from unittest.mock import MagicMock








def test_explicit_auto_prune_false_is_respected(monkeypatch, tmp_path: Path):
    """Migration guard: an install that explicitly opted out keeps its choice."""
    import cli
    import hermes_cli.config
    import hermes_constants

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    monkeypatch.setattr(
        hermes_cli.config,
        "load_config",
        lambda: {"sessions": {"auto_prune": False, "retention_days": 90}},
    )
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.maybe_auto_prune_and_vacuum.assert_not_called()






def test_negative_retention_days_in_config_deletes_nothing(monkeypatch, tmp_path: Path):
    """E2E through the real startup path: ``sessions.retention_days: -1`` reaches
    ``maybe_auto_prune_and_vacuum`` from this config loader; without validation it
    builds a future cutoff and deletes every ended session."""
    import cli
    import hermes_cli.config
    import hermes_constants
    from hermes_state import SessionDB

    session_db = SessionDB(db_path=tmp_path / "state.db")
    try:
        session_db.create_session(session_id="ended", source="cli")
        session_db.end_session("ended", "done")
        monkeypatch.setattr(
            hermes_cli.config,
            "load_config",
            lambda: {"sessions": {"auto_prune": True, "retention_days": -1}},
        )
        monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

        cli._run_state_db_auto_maintenance(session_db)

        assert session_db.get_session("ended") is not None
    finally:
        session_db.close()


def test_cli_auto_maintenance_forwards_vacuum_interval(monkeypatch, tmp_path: Path):
    import cli
    import hermes_cli.config
    import hermes_constants

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    monkeypatch.setattr(
        hermes_cli.config,
        "load_config",
        lambda: {
            "sessions": {
                "auto_prune": True,
                "retention_days": 90,
                "vacuum_after_prune": True,
                "min_interval_hours": 24,
                "min_vacuum_interval_days": 17,
            }
        },
    )
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.maybe_auto_prune_and_vacuum.assert_called_once_with(
        retention_days=90,
        min_interval_hours=24,
        min_vacuum_interval_days=17,
        vacuum=True,
        sessions_dir=tmp_path / "sessions",
    )


def test_state_db_auto_maintenance_sweeps_turn_leases_before_retention_gates(
    monkeypatch, tmp_path: Path
):
    """Expired turn leases of dead holders retire at every CLI startup: with both repair latches
    already set and auto_archive/auto_prune off — the config that returned before touching the DB
    on the pre-sweep tree — the sweep still runs. Lease hygiene is not retention config."""
    import cli
    import hermes_cli.config
    import hermes_constants

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    monkeypatch.setattr(hermes_cli.config, "load_config", lambda: {"sessions": {}})
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.sweep_expired_turn_leases.assert_called_once_with()
    session_db.maybe_auto_archive.assert_not_called()
    session_db.maybe_auto_prune_and_vacuum.assert_not_called()


def test_state_db_auto_maintenance_isolates_sweep_failure_from_retention_gates(
    monkeypatch, tmp_path: Path
):
    """Never-raise contract: a failing sweep neither propagates out of startup maintenance nor
    skips the heartbeat prune or the retention gates behind it."""
    import cli
    import hermes_cli.config
    import hermes_constants
    from hermes_state_gateway import _GATEWAY_HEARTBEAT_PRUNE_WINDOW_S

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    session_db.sweep_expired_turn_leases.side_effect = RuntimeError("database is locked")
    monkeypatch.setattr(
        hermes_cli.config,
        "load_config",
        lambda: {"sessions": {"auto_archive": True, "auto_prune": True, "retention_days": 90}},
    )
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.prune_stale_heartbeats.assert_called_once_with(
        max_age_seconds=_GATEWAY_HEARTBEAT_PRUNE_WINDOW_S)
    session_db.maybe_auto_archive.assert_called_once()
    session_db.maybe_auto_prune_and_vacuum.assert_called_once()


def test_state_db_auto_maintenance_prunes_stale_heartbeats_beside_lease_sweep(
    monkeypatch, tmp_path: Path
):
    """Gateway-heartbeat residue — a backend killed without running atexit — is reclaimed at
    every CLI startup: the prune rides beside the unconditional turn-lease sweep, before the
    retention gates, with the shared window constant (lease-and-heartbeat hygiene is not
    retention config)."""
    import cli
    import hermes_cli.config
    import hermes_constants
    from hermes_state_gateway import _GATEWAY_HEARTBEAT_PRUNE_WINDOW_S

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    monkeypatch.setattr(
        hermes_cli.config, "load_config", lambda: {"sessions": {"auto_archive": True}}
    )
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.prune_stale_heartbeats.assert_called_once_with(
        max_age_seconds=_GATEWAY_HEARTBEAT_PRUNE_WINDOW_S)
    names = [name for name, _args, _kwargs in session_db.method_calls]
    assert names.index("sweep_expired_turn_leases") < names.index("prune_stale_heartbeats")
    assert names.index("prune_stale_heartbeats") < names.index("maybe_auto_archive")


def test_state_db_auto_maintenance_isolates_prune_failure_from_sweep_and_gates(
    monkeypatch, tmp_path: Path
):
    """Never-raise contract, prune leg: a failing heartbeat prune neither skips the lease
    sweep nor the retention gates — the two hygiene blocks are independent try/excepts."""
    import cli
    import hermes_cli.config
    import hermes_constants

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    session_db.prune_stale_heartbeats.side_effect = RuntimeError("database is locked")
    monkeypatch.setattr(
        hermes_cli.config,
        "load_config",
        lambda: {"sessions": {"auto_archive": True, "auto_prune": True, "retention_days": 90}},
    )
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.sweep_expired_turn_leases.assert_called_once_with()
    session_db.maybe_auto_archive.assert_called_once()
    session_db.maybe_auto_prune_and_vacuum.assert_called_once()


def test_state_db_auto_maintenance_none_store_returns_without_raising():
    import cli

    cli._run_state_db_auto_maintenance(None)
