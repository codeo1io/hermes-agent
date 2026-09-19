"""Shared helper for the live-DB guard tests.

The guard denies writes under the PASSWD home (``pwd.getpwuid``), not ``$HOME``
— that is the whole point of the passwd pin (a test or CI runner that
redirects ``HOME`` must not be able to move the deny root). But it cuts both
ways: a CI runner may legitimately run the whole pytest process with ``HOME``
pointed at a scratch directory (the second hermes-agent self-hosted runner
runs jobs with ``HOME=/tmp/hermes-ci-home-2``). Children spawned by these
tests must therefore pin ``HOME`` to the real platform home so the child
resolves — and the guard denies — the production root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def real_platform_home() -> Path:
    """The passwd home on POSIX; ``Path.home()`` fallback elsewhere.

    Mirrors ``hermes_state_guard._real_platform_state_root``'s home
    resolution so guard tests and the guard agree on the production root.
    """
    if sys.platform != "win32":
        try:
            import pwd

            return Path(pwd.getpwuid(os.getuid()).pw_dir)
        except Exception:
            pass
    try:
        return Path(os.path.expanduser("~"))
    except Exception:
        return Path.home()
