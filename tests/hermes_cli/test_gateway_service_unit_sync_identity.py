"""Regression: systemd service identity survives real HERMES_HOME unit adoption."""

import os

import pytest

import hermes_constants
import hermes_cli.gateway as gateway_cli


@pytest.mark.platforms("linux")
def test_real_unit_sync_keeps_the_name_it_validated(tmp_path, monkeypatch):
    """A bare system unit must retain its validated name after adopting the unit's home."""
    alice_home = tmp_path / "alice" / ".hermes"
    alice_home.mkdir(parents=True)
    root_home = tmp_path / "root" / ".hermes"
    root_home.mkdir(parents=True)
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    (unit_dir / f"{gateway_cli._SERVICE_BASE}.service").write_text(
        f'[Service]\nEnvironment="HERMES_HOME={alice_home}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(gateway_cli, "_SYSTEM_UNIT_DIR", unit_dir)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(hermes_constants, "_get_platform_default_hermes_home", lambda: root_home)
    # Use the synthetic account home, not the CI runner's real home.
    monkeypatch.setattr(hermes_constants, "_account_home", lambda: root_home.parent)
    monkeypatch.delenv("HERMES_HOME", raising=False)

    pre_sync_name = gateway_cli.get_service_name()
    assert pre_sync_name == gateway_cli._SERVICE_BASE
    gateway_cli._sync_hermes_home_from_systemd_unit(system=True)

    assert os.environ["HERMES_HOME"] == str(alice_home)
    assert gateway_cli.get_service_name() == pre_sync_name
