"""Status-class boot skip: ``hermes cron status`` is a fixed-budget liveness probe.

The maestro evaluator runs it with a 30 s timeout; every recorded FAIL of the
``phase2.scheduler.hermes-cron`` contract is this CLI dying at the budget while
the gateway and its ticker heartbeat stayed healthy. So the status-class boot
defers work that cannot change a read-only status answer (the update-debt
recovery, the boot bootstrap, and the passive PM runtime verdict); every other
command boots exactly as before.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    """Temp HERMES_HOME + runtime dir so no test touches a real profile."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    return tmp_path


@pytest.fixture
def boot_calls(monkeypatch):
    """Record every status-class-skippable boot step without running it."""
    import hermes_cli.main as cli_main
    import hermes_cli.boot_bootstrap as bb
    import hermes_cli.venv_sync as vs

    calls: dict[str, list] = {"debts": [], "bootstrap": [], "verdict": []}
    monkeypatch.setattr(
        cli_main, "_recover_update_debts_on_startup", lambda: calls["debts"].append(1)
    )
    monkeypatch.setattr(
        bb, "maybe_run_boot_bootstrap", lambda root: calls["bootstrap"].append(str(root))
    )
    monkeypatch.setattr(
        vs, "check_runtime", lambda root: calls["verdict"].append(str(root)) or None
    )
    return calls


@pytest.fixture
def cron_dispatch(monkeypatch):
    """Stand in for the cron subcommand so dispatch is observable without a real run."""
    import hermes_cli.cron as cron_cli

    seen: list[str] = []
    monkeypatch.setattr(cron_cli, "cron_command", lambda args: seen.append(args.cron_command))
    return seen


def _run_cli_main(argv):
    import sys

    from hermes_cli import main as cli_main

    old_argv = sys.argv
    sys.argv = argv
    try:
        cli_main.main()
    except SystemExit:  # argparse help/usage paths exit cleanly
        pass
    finally:
        sys.argv = old_argv


# ── the skip itself ───────────────────────────────────────────────────


class TestStatusClassDetection:
    """The closed status-class set: exactly ``cron status``, flag-tolerant."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["cron", "status"],
            ["--profile", "work", "cron", "status"],  # global flag + value before the command
            ["--tui", "cron", "status"],
            ["cron", "status", "--json"],  # trailing arguments do not widen the match
            ["--", "cron", "status"],
        ],
    )
    def test_status_shapes_are_status_class(self, argv):
        from hermes_cli.main import _status_class_boot_skip

        assert _status_class_boot_skip(argv) is True

    @pytest.mark.parametrize(
        "argv",
        [
            [],
            ["cron"],
            ["cron", "list"],
            ["cron", "statusing"],  # no prefix-of-word matches
            ["cronstatus"],
            ["status"],
            ["gateway", "status"],
            ["chat", "--message", "cron status"],
            ["--profile", "cron", "status"],  # "cron" is the VALUE of --profile here
        ],
    )
    def test_other_shapes_are_not_status_class(self, argv):
        from hermes_cli.main import _status_class_boot_skip

        assert _status_class_boot_skip(argv) is False

    def test_default_reads_process_argv(self, monkeypatch):
        import sys

        from hermes_cli import main as cli_main

        monkeypatch.setattr(sys, "argv", ["hermes", "cron", "status"])
        assert cli_main._status_class_boot_skip() is True
        monkeypatch.setattr(sys, "argv", ["hermes", "cron", "list"])
        assert cli_main._status_class_boot_skip() is False


# ── main() boot wiring ────────────────────────────────────────────────


def test_cron_status_skips_boot_work(hermes_home, boot_calls, cron_dispatch):
    _run_cli_main(["hermes", "cron", "status"])
    assert cron_dispatch == ["status"]  # the command itself still dispatches
    assert boot_calls == {"debts": [], "bootstrap": [], "verdict": []}


def test_cron_list_keeps_boot_work(hermes_home, boot_calls, cron_dispatch):
    _run_cli_main(["hermes", "cron", "list"])
    assert cron_dispatch == ["list"]
    assert boot_calls["debts"] and boot_calls["bootstrap"] and boot_calls["verdict"]


def test_cron_help_keeps_boot_work(hermes_home, boot_calls, cron_dispatch):
    _run_cli_main(["hermes", "cron", "--help"])  # argparse exits; boot already ran
    assert cron_dispatch == []
    assert boot_calls["debts"] and boot_calls["bootstrap"] and boot_calls["verdict"]
