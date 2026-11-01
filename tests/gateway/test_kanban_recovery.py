"""Real dispatch preserves custom board identity and unknown attempts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_disposable_recovery_probe_sets_admission_age_before_dispatch_import():
    """A freshly created fixture task must not be blocked by production anti-churn."""
    probe = Path(__file__).parent / 'fixtures/kanban_recovery_probe.py'
    source = probe.read_text()
    override = "os.environ['HERMES_KANBAN_DISPATCH_MIN_AGE'] = '0'"
    assert source.count(override) == 1
    assert source.index(override) < source.index('from hermes_cli import kanban_db')
    # The override must not be propagated into the independently started owner.
    assert "if key.startswith('HERMES_KANBAN_'):" in source


# The probe traces the transport client's opens with strace (Linux-only tool, Linux openat
# flags); without it the probe cannot prove the client never opens state.db writable.
@pytest.mark.platforms('linux')
@pytest.mark.skipif(shutil.which('strace') is None, reason='requires strace on PATH')
@pytest.mark.parametrize('mode', ['custom', 'cross_profile', 'restart'])
def test_owner_board_recovery(tmp_path, mode):
    repo = Path(__file__).resolve().parents[2]
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'TIRITH_ENABLED') if k in os.environ}
    # This probe creates and dispatches a task in the same process. The production
    # 300-second min-age gate must remain intact; only this isolated probe bypasses it.
    env.update(HOME=str(tmp_path / 'user'), HERMES_HOME=str(tmp_path / 'state'),
               PYTHONPATH=str(repo), KANBAN_RECOVERY_MODE=mode,
               HERMES_KANBAN_DISPATCH_MIN_AGE='0')
    result = subprocess.run([sys.executable, str(repo / 'tests/gateway/fixtures/kanban_recovery_probe.py')],
                            cwd=repo, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    print(json.dumps(json.loads((tmp_path / 'state/receipt.json').read_text())))
