"""Cron home-target resolution: env mirrors, config fallbacks, platform registry lookups.

Split out of ``cron/scheduler_delivery.py`` (code-health FILE_LINES): these helpers
resolve WHERE a cron delivery goes (the platform's home channel); the delivery flow
itself stays in the parent module. Moved code keeps its lint caps (root AGENTS.md).
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_KNOWN_DELIVERY_PLATFORMS = frozenset({"webhook", "wecom_callback", "api_server"})

_HOME_TARGET_PRIORITY = (
    "matrix", "telegram", "discord", "slack", "signal", "mattermost", "sms", "email", "dingtalk",
    "feishu", "wecom", "weixin", "bluebubbles", "qqbot", "whatsapp", "whatsapp_cloud",
)

# Back-compat: primary env var -> previous name, consulted when the primary is unset.
_LEGACY_HOME_TARGET_ENV_VARS = {"QQBOT_HOME_CHANNEL": "QQ_HOME_CHANNEL"}


def _plugin_cron_env_var(platform_name: str) -> str:
    """Cron home-channel env var registered by a plugin ``PlatformEntry.cron_deliver_env_var``."""
    with contextlib.suppress(Exception):
        from hermes_cli.plugins import discover_plugins
        discover_plugins()  # idempotent
        from gateway.platform_registry import platform_registry
        entry = platform_registry.get(platform_name.lower())
        if entry and entry.cron_deliver_env_var:
            return entry.cron_deliver_env_var
    return ""


def _is_known_delivery_platform(platform_name: str) -> bool:
    """Valid cron delivery platform: built-in, or plugin with a ``cron_deliver_env_var``."""
    name = platform_name.lower()
    return name in _KNOWN_DELIVERY_PLATFORMS or bool(_plugin_cron_env_var(name))


def _resolve_home_env_var(platform_name: str) -> str:
    """Env var name for a platform's cron home channel (``PlatformEntry.cron_deliver_env_var``)."""
    return _plugin_cron_env_var(platform_name.lower())


def _get_config_home_channel(platform_name: str):
    """Persisted ``HomeChannel`` from gateway config — the canonical store ``/sethome`` writes.
    The ``<PLATFORM>_HOME_CHANNEL`` env var is only a best-effort mirror; relay-fronted platforms
    may exist solely in config.yaml, so reading only the env mirror would drop their delivery."""
    try:
        from gateway.config import load_gateway_config, Platform
        return load_gateway_config().get_home_channel(Platform(platform_name.lower()))
    except Exception:
        logger.debug(
            "config home_channel lookup failed for platform %r", platform_name, exc_info=True)
        return None


def _home_env_lookup(env_var: str, suffix: str = "", *, strip: bool = False) -> str:
    """Value of ``<env_var><suffix>``, falling back to the legacy name (same suffix) when unset.
    Reads via ``get_secret``, not ``os.getenv``: in a multiplex gateway the tick runs with the
    job-owning profile's secret scope (run_one_job sets it), so this resolves the OWNING profile's
    value, not the host environ. ``os.getenv`` only if the scope module is missing."""
    try:
        from agent.secret_scope import get_secret
    except Exception:
        get_secret = None  # type: ignore

    def read(name: str) -> str:
        value = (get_secret(name, "") or "") if get_secret is not None else os.getenv(name, "")
        return value.strip() if strip else value

    value = read(env_var + suffix)
    legacy = _LEGACY_HOME_TARGET_ENV_VARS.get(env_var)
    if not value and legacy:
        value = read(legacy + suffix)
    return value


def _env_home_target_chat_id(platform_name: str) -> str:
    """Home chat id from the env mirror only (no config).

    Reads through ``get_secret`` (not raw ``os.getenv``) so a profile-scoped secret scope wins in a
    multiplex gateway. ``DISCORD_HOME_CHANNEL`` lives in each profile's ``.env``; in a multiplex process the
    winning cron tick runs with the job-owning profile's scope installed (run_one_job sets it), so reading
    via ``get_secret`` resolves the OWNING profile's chat id rather than the host process's ``os.environ``
    (#83182, chat-id leg — the token leg was fixed earlier; chat id / thread id resolve through the same
    leak).
    """
    env_var = _resolve_home_env_var(platform_name)
    return _home_env_lookup(env_var) if env_var else ""


def _get_home_target_chat_id(platform_name: str) -> str:
    """Home target chat id: env var (first, so operator overrides win) → legacy env var →
    config.yaml ``home_channel``."""
    value = _env_home_target_chat_id(platform_name)
    if value:
        return value
    home = _get_config_home_channel(platform_name)
    return str(home.chat_id) if home is not None and home.chat_id else ""


def _get_home_target_thread_id(platform_name: str) -> Optional[str]:
    """Optional thread/topic id for a platform home target. Telegram: ``TELEGRAM_CRON_THREAD_ID``
    overrides ``TELEGRAM_HOME_CHANNEL_THREAD_ID`` — in topic mode a root-DM delivery lands in the
    system-only lobby where the user cannot reply.

    When topic mode is enabled, deliveries that land in the root DM (thread_id unset) end up in the
    system-only lobby where the user cannot reply — the gateway returns the lobby reminder and drops
    ``reply_to_message_id`` (#24409). Pointing cron at a dedicated topic via this env var lets replies work
    as expected without changing the lobby invariant.
    """
    if platform_name.lower() == "telegram":
        cron_thread = _home_env_lookup("TELEGRAM_CRON_THREAD_ID", strip=True)
        if cron_thread:
            return cron_thread
    env_var = _resolve_home_env_var(platform_name)
    value = _home_env_lookup(env_var, "_THREAD_ID", strip=True) if env_var else ""
    if value:
        return value
    # config.yaml fallback only when the chat id also came from config (an env-provided chat id
    # keeps its env-provided thread semantics).
    if not _env_home_target_chat_id(platform_name):
        home = _get_config_home_channel(platform_name)
        if home is not None and home.thread_id:
            return str(home.thread_id)
    return None


def _iter_home_target_platforms():
    """Iterate plugin platform names that expose a home channel, ``_HOME_TARGET_PRIORITY`` first."""
    with contextlib.suppress(Exception):
        from hermes_cli.plugins import discover_plugins
        discover_plugins()  # idempotent
        from gateway.platform_registry import platform_registry
        named = [e.name for e in platform_registry.plugin_entries() if e.cron_deliver_env_var]
        yield from (n for n in _HOME_TARGET_PRIORITY if n in named)
        yield from (n for n in named if n not in _HOME_TARGET_PRIORITY)  # registry order, as before


