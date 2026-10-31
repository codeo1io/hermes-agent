"""Regression test for #97905 / carrier PR #92489.

A multiplex ticker (desktop dashboard backend, multiplex gateway) resolves
``hermes_time`` under the process's own startup profile, then ticks OTHER
profiles' cron stores via ``set_hermes_home_override()`` + ``use_cron_store()``.
Before the profile-keyed timezone cache, the first profile's resolved zone
was process-global, so ``compute_next_run`` / ``create_job`` / ``mark_job_run``
persisted ``next_run_at`` into the ticked profile's jobs.json with the FOREIGN
process's UTC offset — e.g. ``0 14 * * *`` for an America/New_York profile
stored as ``14:00+00:00``, which becomes due at 10:00 ET and fires four hours
early (#97905; single-profile sibling report #88220).

The invariant pinned here: ``next_run_at`` written during a foreign-process
tick carries the JOB-OWNING profile's configured UTC offset.
"""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import hermes_time


@pytest.fixture(autouse=True)
def _fresh_tz_cache(monkeypatch):
    monkeypatch.delenv("HERMES_TIMEZONE", raising=False)
    hermes_time.reset_cache()
    yield
    hermes_time.reset_cache()


def test_foreign_process_tick_persists_owning_profile_offset(
    tmp_path, monkeypatch
):
    """next_run_at persisted during a multiplex tick uses the ticked
    profile's timezone, not the backend process's."""
    backend_home = tmp_path / "backend"  # desktop backend's own profile: UTC
    profile_a = tmp_path / "north-caribbean"  # job-owning profile: Eastern
    backend_home.mkdir()
    profile_a.mkdir()
    (backend_home / "config.yaml").write_text(
        "timezone: UTC\n", encoding="utf-8"
    )
    (profile_a / "config.yaml").write_text(
        "timezone: America/New_York\n", encoding="utf-8"
    )

    monkeypatch.setenv("HERMES_HOME", str(backend_home))

    # Backend process resolves its own timezone first (process startup).
    assert hermes_time.now().utcoffset() == datetime.now(
        ZoneInfo("UTC")
    ).utcoffset()

    from hermes_constants import (
        reset_hermes_home_override,
        set_hermes_home_override,
    )
    from cron.jobs import create_job, load_jobs, use_cron_store

    # Exactly the scoping the multiplex ticker applies per profile
    # (cron/scheduler_provider.py::_tick_profiles).
    token = set_hermes_home_override(str(profile_a))
    try:
        with use_cron_store(profile_a):
            create_job(name="daily-2pm", prompt="x", schedule="0 14 * * *")
            job = load_jobs()[0]
    finally:
        reset_hermes_home_override(token)

    next_run = datetime.fromisoformat(job["next_run_at"])
    # Anchor the offset check to the OCCURRENCE, never to wall-clock "now":
    # near a DST transition the next occurrence legitimately carries a
    # different offset than the current instant (2026-11-01 America/New_York
    # fall-back: a tick on 2026-10-31 evening EDT resolves the next 14:00 to
    # EST −05:00 while "now" is still EDT −04:00), so comparing against
    # ``datetime.now(zone).utcoffset()`` fails spuriously — and would redden
    # every CI run inside transition windows. The real #97905 invariant is
    # that the persisted offset is the one the OWNING profile's zone assigns
    # to that exact instant (a foreign backend offset shifts the instant).
    ny = ZoneInfo("America/New_York")
    assert next_run.utcoffset() == next_run.astimezone(ny).utcoffset(), (
        f"next_run_at {job['next_run_at']} persisted with foreign offset "
        f"{next_run.utcoffset()} instead of the owning profile's "
        f"{next_run.astimezone(ny).utcoffset()} for that instant — fires "
        "(offset delta) early (#97905)"
    )
    # And the wall clock honors the cron expression in the profile's zone:
    # the stored INSTANT must land on 14:00 New York wall time. A foreign
    # offset baked into the wall clock (14:00+00:00) shifts this to 10:00 ET.
    assert (next_run.astimezone(ny).hour, next_run.astimezone(ny).minute) == (
        14,
        0,
    ), f"stored instant {job['next_run_at']} is not 14:00 America/New_York wall time"
    assert (next_run.hour, next_run.minute) == (14, 0)


def test_foreign_process_tick_across_dst_fallback(tmp_path, monkeypatch):
    """Permanent freeze-frame of the 2026-11-01 America/New_York fall-back.

    A multiplex tick running on 2026-10-31 evening (still EDT, −04:00) must
    resolve the profile's next ``0 14 * * *`` occurrence to the first 14:00
    AFTER the transition — 2026-11-01T14:00:00−05:00 (EST) — not to an
    occurrence re-annotated with the tick instant's stale EDT offset. Pins
    the transition hermetically so it stays covered on any future host date
    (the live-clock test above is occurrence-anchored and DST-safe, but this
    records the exact expected instant for the 2026 fall-back).
    """
    backend_home = tmp_path / "backend"  # desktop backend's own profile: UTC
    profile_a = tmp_path / "north-caribbean"  # job-owning profile: Eastern
    backend_home.mkdir()
    profile_a.mkdir()
    (backend_home / "config.yaml").write_text("timezone: UTC\n", encoding="utf-8")
    (profile_a / "config.yaml").write_text(
        "timezone: America/New_York\n", encoding="utf-8"
    )

    monkeypatch.setenv("HERMES_HOME", str(backend_home))
    assert hermes_time.now().utcoffset() == datetime.now(
        ZoneInfo("UTC")
    ).utcoffset()

    from hermes_constants import (
        reset_hermes_home_override,
        set_hermes_home_override,
    )
    from cron.jobs import create_job, load_jobs, use_cron_store

    # Freeze only the scheduling clock: 2026-10-31T21:30Z == 17:30 EDT, i.e.
    # after that day's 14:00 EDT fires and ~8.5h before the 06:00Z fall-back.
    # Zone resolution (get_timezone under the profile override) stays REAL —
    # that profile-keyed resolution is the #97905 machinery under test.
    frozen_tick = datetime(2026, 10, 31, 17, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr("cron.jobs._hermes_now", lambda: frozen_tick)

    token = set_hermes_home_override(str(profile_a))
    try:
        with use_cron_store(profile_a):
            create_job(name="daily-2pm", prompt="x", schedule="0 14 * * *")
            job = load_jobs()[0]
    finally:
        reset_hermes_home_override(token)

    ny = ZoneInfo("America/New_York")
    expected = datetime(2026, 11, 1, 14, 0, 0, tzinfo=ny)  # first EST occurrence
    next_run = datetime.fromisoformat(job["next_run_at"])
    assert next_run == expected, (
        f"next_run_at {job['next_run_at']} != {expected.isoformat()}: the "
        "tick's pre-fall-back EDT offset leaked into the post-transition "
        "occurrence (#97905 class)"
    )
    assert next_run.utcoffset() == timedelta(hours=-5)
