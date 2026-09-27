"""Regression for the naive-utcnow tempGuid epoch shift.

BlueBubbles tempGuids embed an epoch via ``datetime.utcnow().timestamp()``.
The naive datetime makes ``.timestamp()`` reinterpret UTC in the host's local
zone, shifting every tempGuid by the local UTC offset (e.g. +4h on
America/New_York). The contract: the embedded epoch tracks real elapsed time
regardless of the host zone.
"""

from __future__ import annotations

import time

import pytest

from gateway.platforms.bluebubbles import _temp_guid


@pytest.mark.linux_only  # time.tzset() is POSIX-only; the Windows lane fakes nothing
def test_temp_guid_epoch_tracks_wall_clock_under_non_utc_local_zone(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    before = time.time()
    guid = _temp_guid()
    after = time.time()
    assert guid.startswith("temp-")
    embedded = float(guid[len("temp-"):])
    # Invariant: the embedded epoch is real elapsed time (within the call
    # window), not local-shifted wall time. The old naive implementation is
    # off by the zone offset (+4h EDT), far outside this window.
    assert before - 5 <= embedded <= after + 5
    # And the value must not drift when the local zone changes.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    before2 = time.time()
    embedded2 = float(_temp_guid()[len("temp-"):])
    assert before2 - 5 <= embedded2 <= time.time() + 5


def test_temp_guid_is_parseable_epoch():
    embedded = float(_temp_guid()[len("temp-"):])
    assert embedded > 1_600_000_000  # sane 21st-century epoch, not a shifted one
