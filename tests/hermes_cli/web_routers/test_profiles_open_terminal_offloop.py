"""POST /api/profiles/{name}/open-terminal must keep its terminal probe/spawn off
the event loop: the Linux branch scans for an emulator with blocking `which` calls
before spawning Popen, and the route is served from the dashboard's event loop."""

import asyncio
import subprocess

import pytest

from hermes_cli.web_routers import profiles


@pytest.mark.linux_only
def test_linux_terminal_probe_and_spawn_run_off_the_event_loop(monkeypatch):
    monkeypatch.setattr(profiles, "_profile_setup_command", lambda name: "echo hi")

    seen = {}

    def _probe_call(cmd, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            seen["off_loop"] = True
        else:
            seen["on_loop"] = True
        return 0

    def _record_popen(args, *more, **kwargs):
        seen["popen_args"] = args
        return object()

    monkeypatch.setattr(subprocess, "call", _probe_call)
    monkeypatch.setattr(subprocess, "Popen", _record_popen)

    result = asyncio.run(profiles.open_profile_terminal_endpoint("default"))

    assert result == {"ok": True, "command": "echo hi"}
    assert seen["popen_args"][0] == "x-terminal-emulator"
    assert "on_loop" not in seen  # the `which` scan never ran on the event loop
