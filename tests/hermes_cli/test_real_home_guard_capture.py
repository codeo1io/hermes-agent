"""A disposable pytest HOME must never replace the real protected Hermes root."""
from pathlib import Path

from hermes_state_guard import _real_platform_state_root
from tests import conftest


def test_file_runner_sandbox_is_not_misclassified_as_real_home(tmp_path, monkeypatch):
    fixture_home = tmp_path / "runner-home"
    fixture_home.mkdir()
    sandbox = fixture_home / ".hermes"
    sandbox.mkdir()
    monkeypatch.setenv("HOME", str(fixture_home))
    monkeypatch.setenv("HERMES_TEST_SANDBOX_HOME", str(sandbox))
    monkeypatch.setattr(conftest, "_PRE_SANDBOX_HERMES_HOME", str(sandbox))

    roots = conftest._capture_real_hermes_root()
    real = _real_platform_state_root()
    assert real is not None
    assert real in roots, "test isolation must still guard the machine's real Hermes state"
    assert sandbox not in roots, "runner-owned temporary home must remain writable"


def test_unmarked_custom_hermes_home_is_still_protected(tmp_path, monkeypatch):
    fixture_home = tmp_path / "runner-home"
    fixture_home.mkdir()
    sandbox = fixture_home / ".hermes"
    sandbox.mkdir()
    custom_root = tmp_path / "custom-production-home"
    monkeypatch.setenv("HOME", str(fixture_home))
    monkeypatch.setenv("HERMES_TEST_SANDBOX_HOME", str(sandbox))
    monkeypatch.setattr(conftest, "_PRE_SANDBOX_HERMES_HOME", str(custom_root))

    roots = conftest._capture_real_hermes_root()
    assert Path(custom_root).resolve() in roots
    assert sandbox not in roots
    assert _real_platform_state_root() in roots
