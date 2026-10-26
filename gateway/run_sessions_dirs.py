"""Launch/profile transcript-dir resolution for state.db maintenance.

``gateway.sessions_dir`` overrides the LAUNCH profile's transcript dir only; every other served
profile keeps ``<home>/sessions``. Split out of ``gateway/run.py`` (pure path policy, no state);
consumed by the state.db maintenance chore and runtime init.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from hermes_constants import get_hermes_home


def _launch_sessions_dir(config) -> Optional[tuple[Path, Path]]:
    """``(launch home, its configured transcript dir)``, or ``None`` when the gateway carries none.

    MUST be called outside any profile scope — ``get_hermes_home()`` is what identifies the launch
    home. Consumed by :func:`_profile_sessions_dir`.
    """
    sessions_dir = getattr(config, "sessions_dir", None)
    if sessions_dir is None:
        return None
    return get_hermes_home(), Path(sessions_dir)


def _profile_sessions_dir(launch: Optional[tuple[Path, Path]]) -> Path:
    """Transcript dir of the profile currently in scope.

    ``gateway.sessions_dir`` overrides the LAUNCH profile's transcript dir only; every other served
    profile keeps ``<home>/sessions``. Hardcoding ``<home>/sessions`` for the launch home too wrote
    transcripts to the configured dir while the prune unlinked under the default one, orphaning
    every pruned session's ``.json``/``.jsonl``/``request_dump_*`` forever.
    """
    home = get_hermes_home()
    if launch is not None and Path(launch[0]) == home:
        return Path(launch[1])
    return home / "sessions"
