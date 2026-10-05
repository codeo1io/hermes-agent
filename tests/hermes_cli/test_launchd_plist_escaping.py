# -*- coding: utf-8 -*-
"""Regression tests: the generated launchd plist must be well-formed XML for hostile inputs.

``generate_launchd_plist`` used to XML-escape only ``ProgramArguments``; Label,
WorkingDirectory, the EnvironmentVariables values (PATH / VIRTUAL_ENV / HERMES_HOME) and the
StandardOut/StandardError log paths were interpolated raw. Any ``& < >`` in the user's PATH,
HERMES_HOME, detected venv or working directory then produced a plist that still wrote to
disk but ``launchctl bootstrap`` rejected as not well-formed — the gateway silently lost
autostart. The systemd twin (``gateway_service_unit``) always escaped; the asymmetry was the
bug.

Pure-function tests, host-independent: plist generation never shells out or touches launchd,
so no ``macos_only`` marker is needed.
"""
import plistlib
from pathlib import Path

import hermes_cli.gateway as gateway_cli

HOSTILE = "R&D <hermes>"  # & and < in one token: breaks both well-formedness classes


def _hostile_home(tmp_path, monkeypatch):
    home = tmp_path / HOSTILE
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gateway_cli, "get_hermes_home", lambda: home)
    return home


def test_plist_round_trips_hostile_interpolations(tmp_path, monkeypatch):
    home = _hostile_home(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", f"/usr/bin:/bin:{tmp_path}/bin/R&D-tools")
    monkeypatch.setattr(gateway_cli, "_service_venv_dir", lambda: str(tmp_path / "venv/R&D"))
    monkeypatch.setattr(gateway_cli, "get_launchd_label", lambda: "ai.hermes.gateway-R&D<profile>")

    plist = gateway_cli.generate_launchd_plist()

    # The contract: whatever the shell/home/venv contain, the plist must parse and round-trip
    # the original values (plistlib unescapes entities, so equality means escaped-once).
    parsed = plistlib.loads(plist.encode("utf-8"))
    env = parsed["EnvironmentVariables"]
    assert env["HERMES_HOME"] == str(home.resolve())
    assert f"{tmp_path}/bin/R&D-tools" in env["PATH"]
    assert env["VIRTUAL_ENV"] == str(tmp_path / "venv/R&D")
    assert parsed["Label"] == "ai.hermes.gateway-R&D<profile>"
    assert parsed["StandardOutPath"] == str(home / "logs" / "gateway.log")
    assert parsed["StandardErrorPath"] == str(home / "logs" / "gateway.error.log")
    assert Path(parsed["WorkingDirectory"]).resolve() == home.resolve()
    # ProgramArguments already escaped its parts — the hostile log paths ride along exactly once.
    command_text = " ".join(parsed["ProgramArguments"])
    assert str(home / "logs" / "gateway.log") in command_text
    assert str(home / "logs" / "gateway.error.log") in command_text
    assert "&amp;amp;" not in plist  # no double-escaping anywhere


def _legacy_unescaped(plist: str) -> str:
    """What the pre-escaping generator wrote: the same template with every interpolation raw
    EXCEPT ProgramArguments, which it already escaped."""
    head, marker, rest = plist.partition("<key>ProgramArguments</key>")
    prog, end, tail = rest.partition("</array>")
    unescape = lambda s: s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return unescape(head) + marker + prog + end + unescape(tail)


def test_is_current_rejects_legacy_unescaped_plist(tmp_path, monkeypatch):
    """A plist written by the pre-escaping generator must read as NOT current so the rewrite
    paths repair it instead of leaving launchd's ill-formed file in place; a byte-identical
    regen still compares current.

    Hostility is confined to Label/VIRTUAL_ENV/PATH — the fields the OLD generator left raw.
    (HERMES_HOME cannot be used here: its log paths flow into ProgramArguments, which the old
    generator already escaped, so unescaping them would fake the delta.)
    """
    home = tmp_path / "clean-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gateway_cli, "get_hermes_home", lambda: home)
    monkeypatch.setattr(gateway_cli, "_service_venv_dir", lambda: str(tmp_path / "venv/R&D"))
    monkeypatch.setattr(gateway_cli, "get_launchd_label", lambda: "ai.hermes.gateway-R&D<profile>")
    monkeypatch.setenv("PATH", f"/usr/bin:/bin:{tmp_path}/bin/R&D-tools")
    plist_path = tmp_path / "ai.hermes.gateway.plist"
    monkeypatch.setattr(gateway_cli, "get_launchd_plist_path", lambda: plist_path)

    fixed = gateway_cli.generate_launchd_plist()
    legacy = _legacy_unescaped(fixed)

    plist_path.write_text(legacy, encoding="utf-8")
    assert gateway_cli.launchd_plist_is_current() is False  # bad plist → rewrite repairs it

    plist_path.write_text(fixed, encoding="utf-8")
    assert gateway_cli.launchd_plist_is_current() is True  # escaped regen is stable
