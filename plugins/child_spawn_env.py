"""Minimal environment for non-Hermes child processes spawned by plugins.

Long-lived children (node sidecars, vendored servers) outlive the turn that
started them and their environment is readable back via /proc/<pid>/environ for
their whole lifetime: a full ``os.environ.copy()`` hands them every Tier-1
secret the gateway carries (model keys, scoped .env values, platform tokens).
These children need none of it — they are configured through their own project
variables, added by the caller on top of the base built here.

Allowlist, never a blocklist: a blocklist answers "what do we already know is
bad", so every future secret name would silently re-leak; the allowlist answers
the question that actually matters — "what does a node/python child need".
"""
from __future__ import annotations

import os
import sys

# Resolution + behavior a non-Hermes child genuinely depends on: PATH/HOME for
# binaries, per-user config and module resolution; TEMP/TMP for transpilers and
# native builds; LANG/LC_ALL/TZ so logs, sorting and timestamps behave like the
# parent's. None of these are credentials.
_BASE = (
    "PATH",
    "HOME",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "TZ",
    # TLS trust: behind a corporate proxy a child without these cannot verify
    # upstream certificates at all.
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
    # Operator-set node runtime tuning (e.g. --max-old-space-size) for sidecars.
    "NODE_OPTIONS",
)

# Windows CRT essentials — without these socket.socket() and subprocess
# resolution fail outright (same set execute_code admits; see
# tools/code_execution_env.py). Only consulted when the child host is Windows.
_WINDOWS_ONLY = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "PUBLIC",
    "ALLUSERSPROFILE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "USERDOMAIN",
    "USERNAME",
    "HOMEDRIVE",
    "HOMEPATH",
    "COMPUTERNAME",
)


def minimal_child_env(source_env=None, *, is_windows=None) -> dict:
    """Base env for a non-Hermes child process: curated names only.

    Callers layer their own project variables on top. ``source_env`` defaults to
    ``os.environ`` and is injectable so tests can plant values; ``is_windows``
    defaults to the current platform and is injectable so the Windows arm can be
    exercised as data on any host.
    """
    if source_env is None:
        source_env = os.environ
    if is_windows is None:
        is_windows = sys.platform == "win32"
    names = _BASE + _WINDOWS_ONLY if is_windows else _BASE
    return {name: source_env[name] for name in names if source_env.get(name)}
