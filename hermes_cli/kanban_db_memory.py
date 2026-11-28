"""Linux PSI sampling for Kanban admission; no durable scheduler state.

This module deliberately keeps gateway imports late to avoid importing the
gateway during standalone Kanban DB use. The caller supplies the opener and
PSI sampler to preserve the existing test seams.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TextIO

logger = logging.getLogger(__name__)


def read_psi_full_avg60(opener: Callable[..., TextIO]) -> float | None:
    """Return sustained host full-stall percentage, or None when unavailable."""
    try:
        with opener("/proc/pressure/memory", encoding="ascii") as stream:
            for line in stream:
                fields = line.split()
                if fields and fields[0] == "full":
                    for field in fields[1:]:
                        if field.startswith("avg60="):
                            value = float(field.partition("=")[2])
                            return value if 0.0 <= value <= 100.0 else None
    except (OSError, ValueError):
        pass
    return None


def sample_system_memory(psi_sampler: Callable[[], float | None]) -> dict[str, Any]:
    """Best-effort MemAvailable + PSI snapshot, empty on unknown memory."""
    try:
        from gateway.lifecycle_ledger import sample_memory

        sample = sample_memory() or {}
        if sample:
            full_psi = psi_sampler()
            if full_psi is not None:
                sample["memory_full_psi_avg60"] = full_psi
        return sample
    except Exception:
        logger.exception("Kanban memory sample unavailable")
        return {}
