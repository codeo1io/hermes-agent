"""Keep the required Windows OS lane bounded under nested PowerShell load.

The OS workflow selected all platform-marked tests correctly, but 16
simultaneous per-file subprocess trees starved the hosted runner and tripped
fixture startup / 300-second file deadlines. This regression pins the worker
budget while preserving actual test selection.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]

def test_windows_only_lane_caps_concurrent_file_processes():
    workflow = (ROOT / ".github/workflows/tests-os.yml").read_text(encoding="utf-8")
    matched = re.search(r"^\s*HERMES_TEST_WORKERS:\s*\$\{\{\s*matrix\.marker == 'windows'\s*&&\s*'([0-9]+)'", workflow, re.MULTILINE)
    assert matched, "Windows OS lane must declare a bounded file-worker count"
    assert 1 <= int(matched.group(1)) <= 4

def test_os_lane_still_requires_full_platform_selection_and_original_timeouts():
    workflow = (ROOT / ".github/workflows/tests-os.yml").read_text(encoding="utf-8")
    assert 'scripts/run_tests.sh --files "$FILES"' in workflow
    assert '-m "platforms and not integration and not live"' in workflow
    assert "timeout-minutes: ${{ matrix.timeout || 30 }}" in workflow
