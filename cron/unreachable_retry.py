"""Automatic bounded re-runs for scheduled fires that never reached the model.

Inspired by Claude Cowork (desktop changelog v1.46388.1, 2026-09-04): "automatic re-runs
(after 5, 15, and 30 minutes) for a scheduled task that could not reach the model at all,
for example right after the computer wakes behind a VPN."

The class is deliberately narrow: the run must have FAILED with a transient network /
DNS error (``cron.scheduler_preflight._is_transient_provider_resolve_error``) AND the
agent must have completed zero API calls. Nothing was executed and nothing was spent, so
re-running cannot double a side effect — unlike a generic failure retry (see PR #16512),
which has to answer for one-shot dispatch accounting and mid-run side effects. Recurring
jobs only: finite one-shots are pre-claimed by ``claim_dispatch`` (at-most-times, #38758)
and must not regain a consumed dispatch here.

While a retry is pending the failure notice is suppressed (Cowork re-runs silently); a
run that reaches the model — success or not — resets the ladder. Disable with
``cron.retry_unreachable: false`` in config.yaml.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from hermes_time import now as _hermes_now

logger = logging.getLogger("cron.scheduler")

# Cowork's ladder: re-run after 5, 15, then 30 minutes; then give up until the
# schedule's own next occurrence.
RETRY_DELAYS_SECONDS: tuple[int, ...] = (300, 900, 1800)

# Persisted on the job while a retry cycle is active: {"attempt": <1-based count of
# retries already scheduled>}. Cleared by any run that reached the model.
STATE_KEY = "unreachable_retry"


def retry_enabled(cfg: Optional[dict] = None) -> bool:
    """``cron.retry_unreachable`` — default ON (spend-neutral: only fires when zero
    model calls were made)."""
    if cfg is None:
        try:
            from hermes_cli.config import load_config

            cfg = load_config() or {}
        except Exception:  # config unreadable — keep the reliability default
            return True
    cron_cfg = (cfg or {}).get("cron")
    if not isinstance(cron_cfg, dict):
        return True
    return cron_cfg.get("retry_unreachable") is not False


# The provider answered HTTP 200 but closed the SSE stream before any event
# (glmplus: "SSE headers sent before upstream recovery" + upstream timeout). The
# agent dies with this RuntimeError text after its own stream retries; zero
# responses were folded, so a re-run is spend-neutral exactly like DNS loss.
# All three raise sites use the same "Provider returned an empty stream" prefix
# (agent/chat_completion_helpers.py) — one needle covers them.
_EMPTY_STREAM_NEEDLE = "provider returned an empty stream"


def is_model_unreachable_failure(exc: BaseException, agent: Any = None) -> bool:
    """True when *exc* is a transient network/DNS failure and *agent* (may be ``None``)
    never completed a model call — the run consumed nothing and executed nothing."""
    if int(getattr(agent, "session_api_calls", 0) or 0) > 0:
        return False
    from cron.scheduler_preflight import _is_transient_provider_resolve_error

    if _is_transient_provider_resolve_error(exc):
        return True
    # Empty-stream deaths (HTTP 200, zero events): the scheduler wraps the agent's
    # EmptyStreamError in a plain RuntimeError, so match the canonical message text
    # across the cause chain. Spend-neutrality is guaranteed by the session_api_calls
    # guard above — a stream that folded even one response is not in this class.
    seen: set = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if _EMPTY_STREAM_NEEDLE in str(cur).lower():
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _is_recurring(job: Dict[str, Any]) -> bool:
    return job.get("schedule", {}).get("kind") in {"cron", "interval"}


def will_retry(job: Dict[str, Any]) -> bool:
    """Predict whether ``plan_retry`` will schedule a re-run for this flagged failure —
    used by the scheduler to suppress the interim failure notice."""
    if not _is_recurring(job) or job.get("state") == "paused":
        return False
    state = job.get(STATE_KEY) or {}
    if int(state.get("attempt") or 0) >= len(RETRY_DELAYS_SECONDS):
        return False
    return retry_enabled()


def clear_state(job: Dict[str, Any]) -> None:
    """A run reached the model (any outcome): the ladder resets."""
    job.pop(STATE_KEY, None)


def plan_retry(job: Dict[str, Any]) -> bool:
    """Called under the jobs lock AFTER ``_advance_after_run`` computed the schedule's
    natural ``next_run_at`` for a failed, flagged run. Pulls ``next_run_at`` earlier to
    the ladder instant when that is sooner than the natural occurrence; exhausted or
    inapplicable cycles clear state and leave the schedule untouched. Returns True when
    a retry was scheduled."""
    if not _is_recurring(job) or job.get("state") == "paused" or not retry_enabled():
        clear_state(job)
        return False
    state = job.get(STATE_KEY) or {}
    attempt = int(state.get("attempt") or 0)
    if attempt >= len(RETRY_DELAYS_SECONDS):
        # Ladder exhausted: fall back to the natural schedule and reset so the NEXT
        # occurrence gets a fresh ladder if the network is still down.
        clear_state(job)
        logger.warning(
            "Job '%s': model unreachable after %d automatic re-runs — waiting for the "
            "scheduled occurrence at %s",
            job.get("name", job.get("id", "?")), attempt, job.get("next_run_at"))
        return False
    delay = RETRY_DELAYS_SECONDS[attempt]
    retry_dt = _hermes_now() + timedelta(seconds=delay)
    from cron.jobs import _parse_aware  # late: jobs imports this module's helpers

    natural_next = _parse_aware(job.get("next_run_at"))
    if natural_next is not None and natural_next <= retry_dt:
        # The schedule fires again sooner than the ladder would — no point consuming an
        # attempt; the natural occurrence IS the retry.
        clear_state(job)
        return False
    retry_at = retry_dt.isoformat()
    job[STATE_KEY] = {"attempt": attempt + 1}
    job["next_run_at"] = retry_at
    if job.get("state") != "paused":
        job["state"] = "scheduled"
    logger.info(
        "Job '%s': model unreachable with zero API calls — automatic re-run %d/%d in %ds "
        "(at %s)",
        job.get("name", job.get("id", "?")), attempt + 1, len(RETRY_DELAYS_SECONDS),
        delay, retry_at)
    return True
