"""Bounded-timeout contract for `hermes mcp install` bootstrap commands.

Regression: ``_run_bootstrap`` ran each post-install command with
``subprocess.run(..., shell=True)`` and no timeout — a hanging installer
(postrm script waiting on a lock, npm postinstall on a dead registry)
froze ``hermes mcp install`` forever. These tests pin the relationship
between a per-command timeout and the surfaced CatalogError.
"""

import sys
import time

import pytest

from hermes_cli.mcp_catalog import BOOTSTRAP_DEFAULT_TIMEOUT_S, CatalogError, _run_bootstrap


def _cmd(body: str) -> str:
    return f'"{sys.executable}" -c "{body}"'


def test_default_timeout_is_finite():
    # The bug was NO timeout at all: the default must stay a finite wall-clock bound.
    assert 0 < BOOTSTRAP_DEFAULT_TIMEOUT_S < float("inf")


def test_successful_command_passes_through(tmp_path):
    _run_bootstrap(tmp_path, [_cmd("print('ok')")], timeout=30)


def test_failed_command_raises_with_exit_code(tmp_path):
    with pytest.raises(CatalogError) as excinfo:
        _run_bootstrap(tmp_path, [_cmd("raise SystemExit(3)")], timeout=30)
    assert "3" in str(excinfo.value)


def test_hanging_command_is_bounded_not_forever(tmp_path):
    started = time.monotonic()
    with pytest.raises(CatalogError) as excinfo:
        _run_bootstrap(tmp_path, [_cmd("import time; time.sleep(30)")], timeout=0.5)
    elapsed = time.monotonic() - started
    # The wall-clock contract: the hang is cut at ~timeout, not at 30s.
    assert elapsed < 10.0, f"bootstrap hang not bounded (took {elapsed:.1f}s)"
    assert "timed out" in str(excinfo.value).lower()


def test_second_command_runs_after_first_succeeds(tmp_path):
    # A sequence of commands is executed in order; timeout applies per command.
    _run_bootstrap(tmp_path, [_cmd("print(1)"), _cmd("print(2)")], timeout=30)
