"""Regression: a sleeping Windows update child must not count as progress."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
JOB_HELPER = ROOT / "scripts" / "desktop-update" / "update-job.ps1"
WINDOWS_HANDOFF = ROOT / "scripts" / "desktop-update" / "windows.ps1"


def _powershell() -> str:
    shell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if not shell:
        pytest.skip("PowerShell is unavailable on this platform")
    return shell


def test_job_activity_requires_meaningful_cpu_or_io() -> None:
    helper = str(JOB_HELPER).replace("\u0027", "\u0027\u0027")
    script = (
        f". '{helper}'; Initialize-HermesUpdateJob; "
        "$baseline = [long[]]@(0,0); "
        "$cases = @("
        "@([long[]]@(100000,4096),$false),"
        "@([long[]]@(2499999,65535),$false),"
        "@([long[]]@(2500000,0),$true),"
        "@([long[]]@(0,65536),$true),"
        "@([long[]]@(-1,-1),$false) "
        "); "
        "foreach ($case in $cases) { "
        "if ([HermesUpdateJob]::HasMeaningfulActivity($baseline,$case[0]) -ne $case[1]) "
        "{ throw 'incorrect job activity verdict' } }; "
        "'threshold PASS'"
    )
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "threshold PASS" in result.stdout


def test_windows_handoff_powershell_syntax() -> None:
    handoff = str(WINDOWS_HANDOFF).replace("\u0027", "\u0027\u0027")
    script = (
        "$issues = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{handoff}', "
        "[ref]$null, [ref]$issues) | Out-Null; "
        "if ($issues.Count -gt 0) { $issues; exit 1 }; 'syntax PASS'"
    )
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "syntax PASS" in result.stdout
