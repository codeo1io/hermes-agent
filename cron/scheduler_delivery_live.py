"""Cron delivery through a live platform adapter or the standalone sender.

The send-side of scheduler_delivery: transport resolution for a target, live-route
metadata, text/media sends through a connected adapter, the standalone-sender bridge,
and reconnect queueing. Split from scheduler_delivery (FILE_LINES cap; moved code keeps
its cap per the repo split convention — see scheduler_delivery_origin/_room)."""

from __future__ import annotations

from cron import scheduler_delivery_origin as _origin
import asyncio
import threading
import contextvars
import concurrent.futures
import logging

from typing import Any, Optional

from cron import scheduler_preflight as _preflight
from cron import scheduler_delivery as sd
from cron.scheduler_delivery import (  # re-export for the tests' patch targets
    _TargetDelivery,
    _confirm_adapter_delivery,
    _get_standalone_send_timeout,
    _is_channel_dm_topic,
    _maybe_mirror_cron_delivery,
    _note_target_error,
    _result_field,
    _seed_cron_channel_session,
    _seed_cron_thread_session,
)

logger = logging.getLogger("cron.scheduler")  # same channel as scheduler_delivery (tests listen here)


def _resolve_target_transport(
    job: dict, platform, platform_name: str, target: dict, adapters, config):
    """Resolve ``(transport, pconfig, runtime_adapter, target_adapters)`` for one target, or
    ``(None, error)`` when it cannot be served (relay-fronted with no live transport, or not
    configured/enabled)."""
    from gateway.delivery import DeliveryTransport, resolve_delivery_transport
    target_adapters = adapters
    transport = None
    if isinstance(adapters, _preflight.SharedRouteAdapters):
        # Credentialless satellite: the primary adapter serves THIS target only when an exact
        # primary route maps it to this profile; a miss fails closed below.
        # See #101113.
        shared = adapters.get(platform, target)
        target_adapters = {platform: shared} if shared is not None else {}
        if shared is not None:
            # The PRIMARY's route authorized this exact native adapter. The satellite's own
            # ``platforms.<p>`` block describes a connector it never runs (no credential), so
            # neither its absence nor ``enabled: false`` may veto the shared transport; only its
            # non-credential settings (continuable surface, reply mode) are kept (#89302, #103701).
            from dataclasses import replace
            from gateway.config import PlatformConfig
            own = config.platforms.get(platform)
            transport = DeliveryTransport(
                shared, replace(own, enabled=True) if own is not None else PlatformConfig(enabled=True),
                platform)
    if transport is None:
        transport = resolve_delivery_transport(platform, config, target_adapters)
    if transport is not None:
        pconfig = transport.config
        runtime_adapter = transport.adapter
    else:
        # Relay-fronted platforms have NO standalone fallback (the connector owns the credential),
        # so surface that instead of the native configured/enabled gate, which misdiagnoses them.
        from gateway.relay import relay_fronted_platforms
        if platform_name in relay_fronted_platforms():
            return None, (
                f"platform '{platform_name}' is relay-fronted and has no "
                "live gateway transport; start the gateway (its ticker "
                "owns relay-fronted delivery and will fire the job on "
                "schedule)"
            )
        pconfig = config.platforms.get(platform)
        runtime_adapter = None

    if transport is not None and (transport.is_relay or pconfig is None):
        # Relay transport carries the RELAY adapter's config (enablement already checked): the
        # logical platform is deliberately NOT natively enabled. A live NATIVE adapter with no
        # ``platforms.<p>`` block is the same shape — the owning process already authorized the
        # adapter; "no config" is not "disabled" (#89302).
        if pconfig is None:
            from gateway.config import PlatformConfig
            pconfig = PlatformConfig(enabled=True)
    elif not pconfig or not pconfig.enabled:
        return None, f"platform '{platform_name}' not configured/enabled"
    return (transport, pconfig, runtime_adapter, target_adapters), None


def _inchannel_surface_supported(runtime_adapter, platform_name: str) -> bool:
    """D6 probe: can this adapter deliver a continuable in_channel brief on ``platform_name``?
    Per-platform check first (one RelayAdapter fronts N platforms; the scalar attr only carries
    the PRIMARY identity's bit); native adapters use the class attribute."""
    per_platform_check = getattr(
        runtime_adapter, "supports_inchannel_continuable_for_platform", None)
    if callable(per_platform_check):
        try:
            return bool(per_platform_check(platform_name))
        except Exception:
            return False
    return bool(getattr(runtime_adapter, "supports_inchannel_continuable", False))


def _named_dm_topic(t: sd._TargetDelivery) -> Optional[str]:
    """The topic NAME of a ``telegram:<positive chat id>:<topic name>`` target, else None."""
    from gateway.config import Platform
    from gateway.delivery import _looks_like_int, looks_like_telegram_private_chat_id
    if (t.platform == Platform.TELEGRAM and t.thread_id is not None
            and looks_like_telegram_private_chat_id(str(t.chat_id)) and not _looks_like_int(str(t.thread_id))):
        return str(t.thread_id)
    return None


def _live_route_metadata(t: sd._TargetDelivery) -> tuple[Optional[str], dict, dict]:
    """Compute ``(route_thread_id, route_metadata, media_metadata)`` for a live send, ONCE so text
    and media agree. ``telegram:<positive_chat_id>:<numeric_thread_id>`` is ambiguous (private
    forum topic vs channel DM topic need OPPOSITE routing) — see ``sd._is_channel_dm_topic``.
    ``thread_id`` rides in ``route_metadata`` to bypass the router's private-chat anchor rule."""
    from gateway.config import Platform
    from gateway.delivery import _looks_like_int, looks_like_telegram_private_chat_id
    job = t.job
    thread_id = t.thread_id
    is_ambiguous_telegram_topic = (
        t.platform == Platform.TELEGRAM
        and thread_id is not None
        and looks_like_telegram_private_chat_id(str(t.chat_id))
        and _looks_like_int(str(thread_id))
    )
    if is_ambiguous_telegram_topic and sd._is_channel_dm_topic(
        t.runtime_adapter, t.chat_id, t.loop, job["id"]):
        # Channel DM topic: direct_messages_topic_id, no bare thread_id; media mirrors text.
        # See #22773.
        route_thread_id = None
        route_metadata = {
            "direct_messages_topic_id": str(thread_id), "job_id": job["id"],
            "notify": t.notify_delivery,
        }
        media_metadata = {"direct_messages_topic_id": str(thread_id), "notify": t.notify_delivery}
    else:
        # Forum-style topic or non-topic target: message_thread_id.
        # Put thread_id in *route_metadata* (not just the DeliveryTarget) deliberately — the
        # DeliveryRouter's private-chat topic detection (gateway/delivery.py) demands a reply anchor when
        # thread_id is absent from metadata; cron deliveries have no inbound reply anchor, so the metadata
        # key bypasses that check and lets the adapter route via a plain message_thread_id. See #52060.
        route_thread_id = str(thread_id) if thread_id is not None else None
        route_metadata = {"job_id": job["id"], "notify": t.notify_delivery}
        # A named private-DM topic stays on the target only: the router resolves the name
        # (ensure_dm_topic) and refreshes it on "thread not found" only when metadata carries no
        # thread routing key (#80483).
        if route_thread_id and sd._named_dm_topic(t) is None:
            route_metadata["thread_id"] = route_thread_id
        media_metadata = {"notify": t.notify_delivery}
        if thread_id:
            media_metadata["thread_id"] = thread_id

    # Relay egress discriminators (scope_id / user_id) from the persisted origin: the adapter's caches are cold
    # after a restart. See cron/scheduler_delivery_origin.py.
    _origin.stamp_origin_discriminators(t, route_metadata, media_metadata)
    return route_thread_id, route_metadata, media_metadata


_LIVE_SEND_CONFIRM_TIMEOUT_SECS = 60


def _live_send_text(
    t: sd._TargetDelivery, text_to_send: str, route_thread_id: Optional[str], route_metadata: dict, *,
    target_errors: list, delivery_errors: list, unverified_targets: list,
) -> tuple[bool, bool, Any]:
    """Schedule the text send on the gateway loop; returns ``(adapter_ok, timed_out, message_id)``.
    Re-raises a real send error so the caller falls through to standalone."""
    from agent.async_utils import safe_schedule_threadsafe
    from gateway.delivery import DeliveryRouter, DeliveryTarget, PartialDeliveryError
    job = t.job
    router = DeliveryRouter(t.config, t.target_adapters)
    route_target = DeliveryTarget(
        platform=t.platform, chat_id=str(t.chat_id), thread_id=route_thread_id, is_explicit=True)
    # Thread routing goes via the target, not a bare metadata "thread_id": the router only applies
    # its Telegram DM-topic detection when thread_id/message_thread_id are absent from metadata.
    # Send through the already-authorized transport: re-resolving from the plain target_adapters
    # dict cannot re-derive the SharedRouteAdapters satellite grant (the satellite owned
    # platforms.<p> block is disabled), yields None, and drops the delivery (#115656).
    # cancel() cannot tell "never started" from "in flight": a run_coroutine_threadsafe future stays
    # PENDING until the coroutine finishes, so cancel() returns True mid-send AND kills it. The send
    # records its own start under a lock; a timeout abandons it only if it never began.
    dispatch_lock = threading.Lock()
    dispatch = {"started": False, "abandoned": False}

    async def _send_once():
        with dispatch_lock:
            if dispatch["abandoned"]:
                return None
            dispatch["started"] = True
        return await router._deliver_to_platform(route_target, text_to_send, route_metadata, transport=t.transport)

    future = safe_schedule_threadsafe(_send_once(), t.loop)
    if future is None:
        target_errors.append("live adapter event loop scheduling failed")
        return False, False, None
    try:
        send_result = future.result(timeout=sd._LIVE_SEND_CONFIRM_TIMEOUT_SECS)
    except TimeoutError:
        # Slow confirmation != failure. Never started (loop wedged): nothing was sent, so fall through
        # to standalone or it is silently dropped. Started: in flight (a paced multi-chunk send can
        # legitimately outlast the wait) — leave it running; a standalone resend would DUPLICATE.
        with dispatch_lock:
            dispatch["abandoned"] = not dispatch["started"]
        if dispatch["abandoned"]:
            future.cancel()
            msg = f"live adapter send to {t.where} timed out before the coroutine was dispatched"
            logger.warning("Job '%s': %s, falling back to standalone", job["id"], msg)
            target_errors.append(msg)
            return False, False, None
        logger.warning(
            "Job '%s': live adapter send to %s:%s timed out "
            "after 60s; already dispatched (in flight), "
            "assuming delivered (skipping standalone fallback "
            "to avoid duplicate)",
            job["id"], t.platform_name, t.chat_id)
        return True, True, None
    except PartialDeliveryError as ex:
        # The head of a split send is already on screen: a standalone resend would duplicate it.
        raw = getattr(ex.result, "raw_response", None) or {}
        sd._note_target_error(
            job, f"live adapter send to {t.where} delivered {raw.get('delivered_chunks', '?')} of "
            f"{raw.get('total_chunks', '?')} chunks, then failed: {ex}", delivery_errors)
        return True, False, None
    except Exception as ex:
        # Real send error (not a slow confirmation): fall through to standalone. The router raises
        # a failed SendResult's error string, so this is where send_path_degraded arrives.
        t.live_error = str(ex)
        target_errors.append(f"live adapter send failed: {ex}")
        raise

    # _deliver_to_platform returns a SendResult, or a plain dict {"success": True, "delivered":
    # False, ...} when the silence-narration filter drops the message.
    send_raw_response = sd._result_field(send_result, "raw_response")
    delivered_message_id = sd._result_field(send_result, "message_id")
    _evidence_gap: list = []
    send_success = sd._confirm_adapter_delivery(send_result, job["id"], _evidence_gap)
    if send_success and _evidence_gap:
        unverified_targets.append(t.where)

    if not send_success:
        if send_result is None:
            err, shape = "no response from adapter", "None"
        elif isinstance(send_result, dict):
            # A filtered drop carries no "error" — name the filter instead of reporting "unknown".
            err = send_result.get("error") or send_result.get("filtered") or "unknown"
            shape = "dict"
        else:
            err, shape = getattr(send_result, "error", None), type(send_result).__name__
        msg = f"live adapter send to {t.where} returned unconfirmed result ({shape}, error={err})"
        t.live_error = str(err) if err else None
        sd._warn_live_lane_failure(job, msg, t.is_relay)
        target_errors.append(msg)
        return False, False, None
    if send_raw_response and t.thread_id and send_raw_response.get("thread_fallback"):
        requested_thread_id = send_raw_response.get("requested_thread_id") or t.thread_id
        sd._note_target_error(
            job,
            f"configured thread_id {requested_thread_id} for "
            f"{t.where} was not found; delivered without thread_id",
            delivery_errors)
    return True, False, delivered_message_id


def _resolve_named_dm_topic(t: sd._TargetDelivery, topic_name: str, metadata: dict, delivery_errors: list,
                            n_media: int, *, refresh: bool) -> bool:
    """Resolve a named DM topic to its thread id through the router's resolver (cached by the
    adapter, so after a text send this is the id that send used), writing it to ``t.thread_id``
    (mirroring/seeding key on the numeric id) and ``metadata``. False = media dropped, never General."""
    from agent.async_utils import safe_schedule_threadsafe
    from gateway.delivery import _ensure_named_dm_topic
    future = safe_schedule_threadsafe(
        _ensure_named_dm_topic(t.runtime_adapter, str(t.chat_id), topic_name, refresh=refresh), t.loop)
    try:
        if future is None:
            raise RuntimeError("gateway loop unavailable")
        t.thread_id = future.result(timeout=30)
    except Exception as e:  # any resolver/adapter failure drops the media for this target
        logger.warning("Job '%s': named DM topic %r unresolved", t.job["id"], topic_name, exc_info=True)
        if n_media:
            delivery_errors.append(f"{n_media} media attachment(s) not delivered to {t.where}: {e}")
        return False
    metadata.update(thread_id=t.thread_id, telegram_dm_topic_created_for_send=True)
    return True


def _live_send_media(
    t: sd._TargetDelivery, media_metadata: dict, media_files: list, delivery_errors: list,
    unverified_targets: list, topic_name: Optional[str] = None) -> None:
    """Send extracted media as native attachments with the same routing as the text send."""
    routed_media_metadata = dict(media_metadata or {})
    if t.is_relay:
        routed_media_metadata["_relay_logical_platform"] = t.platform.value
        logical_home = t.config.get_home_channel(t.platform)
        if logical_home is not None and logical_home.chat_id == t.chat_id:
            if logical_home.user_id:
                routed_media_metadata["user_id"] = logical_home.user_id
            if logical_home.scope_id:
                routed_media_metadata["scope_id"] = logical_home.scope_id
    _media_errors = sd._send_media_via_adapter(
        t.runtime_adapter, t.chat_id, media_files, routed_media_metadata or None, t.loop, t.job,
        platform=t.platform,
    )
    if (topic_name and len(media_files) == sum("thread not found" in e.lower() for e in _media_errors)
            and sd._resolve_named_dm_topic(t, topic_name, routed_media_metadata, delivery_errors,
                                        len(media_files), refresh=True)):
        # The named topic vanished (a media-only job never runs the router's text refresh): recreate once.
        _media_errors = sd._send_media_via_adapter(
            t.runtime_adapter, t.chat_id, media_files, routed_media_metadata, t.loop, t.job,
            platform=t.platform)
    if t.job.pop("_media_ack_lost", False) and t.where not in unverified_targets:
        unverified_targets.append(t.where)
    # Surface per-file failures into run status: text delivered but attachment lost is not ok.
    for _me in _media_errors:
        delivery_errors.append(f"{_me} (target {t.where})")


def _seed_live_delivery_sessions(t: sd._TargetDelivery, delivered_message_id) -> None:
    """After a confirmed live send, seed continuation session(s) and run the generic mirror.
    Thread seeding is deferred here so open-succeeds/deliver-fails never seeds an unseen brief."""
    job = t.job
    origin = t.origin
    seed_kwargs = dict(
        chat_name=origin.get("chat_name"), is_dm=t.is_dm_target, scope_id=origin.get("scope_id"))
    thread_seeded = False
    inchannel_seeded = False
    if t.opened_thread_id:
        sd._seed_cron_thread_session(
            job, t.runtime_adapter, t.platform_name, t.chat_id, t.opened_thread_id, t.mirror_text,
            **seed_kwargs,
        )
        thread_seeded = True
    # in_channel: CREATE + seed the flat session (the mirror only APPENDS to an existing one). Same
    # `inchannel_continuable` gate as the flatten in _deliver_result (must not drift). Origin
    # seed without mirror opt-in; others only via _inchannel_seed_allowed (user-less seed = orphan).
    if t.in_channel_surface and t.inchannel_continuable and not thread_seeded:
        inchannel_seeded = sd._seed_cron_channel_session(
            job, t.runtime_adapter, t.platform_name, t.chat_id, t.mirror_text,
            user_id=t.origin_user_id, **seed_kwargs)
        if not inchannel_seeded:
            logger.warning(
                "Job '%s': in_channel seed did NOT land on %s:%s "
                "— a plain reply will not see this brief",
                job["id"], t.platform_name, t.chat_id)
        # Companion THREAD seed: a reply in the brief's own thread keys to (chat, thread=<ts>),
        # which the flat seed never touches. Seed it too so BOTH reply surfaces continue the job.
        if delivered_message_id:
            sd._seed_cron_thread_session(
                job, t.runtime_adapter, t.platform_name, t.chat_id, str(delivered_message_id),
                t.mirror_text,
                **seed_kwargs)
    elif t.in_channel_surface and not t.inchannel_continuable:
        logger.warning(
            "Job '%s': in_channel delivery to %s:%s is not a "
            "continuable target (origin=%s:%s thread=%s; not the "
            "origin conversation, and not a mirror-eligible "
            "fallback/opted-in target the seed can key) — seed "
            "skipped; the plain mirror below may still apply",
            job["id"], t.platform_name, t.chat_id,
            origin.get("platform"), origin.get("chat_id"), origin.get("thread_id"))
    sd._maybe_mirror_cron_delivery(
        job, t.platform_name, t.chat_id, t.mirror_text, thread_id=t.thread_id,
        user_id=t.origin_user_id,
        enabled=t.mirror_this_target and not thread_seeded and not inchannel_seeded)


def _deliver_via_live_adapter(
    t: sd._TargetDelivery, cleaned_text: str, media_files: list, *, target_errors: list,
    delivery_errors: list, unverified_targets: list,
) -> bool:
    """Deliver one target via the live gateway adapter; True once delivered. ``target_errors`` =
    this lane's soft failures (surfaced only if standalone also fails); ``delivery_errors`` =
    partial failures (media, thread fallback) that surface even on success."""
    job = t.job
    route_thread_id, route_metadata, media_metadata = sd._live_route_metadata(t)
    delivered = False
    try:
        # Send cleaned text (MEDIA tags stripped) through the gateway's DeliveryRouter so it gets
        # the same platform routing as live messages (Telegram's three-mode topic routing).
        text_to_send = cleaned_text.strip()
        adapter_ok, timed_out, delivered_message_id = True, False, None
        if not text_to_send and not media_files:
            # Fail closed so the run reports the empty payload.
            sd._note_target_error(
                job, f"live adapter send skipped (empty text and no media) for {t.where}",
                target_errors)
            adapter_ok = False
        elif text_to_send:
            adapter_ok, timed_out, delivered_message_id = sd._live_send_text(
                t, text_to_send, route_thread_id, route_metadata,
                target_errors=target_errors, delivery_errors=delivery_errors,
                unverified_targets=unverified_targets,
            )

        # Media rides the same DM-topic-aware routing as text. Skipped after a confirmation
        # timeout (loop contended, text already assumed delivered) — record the drop instead.
        # Send extracted media files as native attachments via the live adapter, using the same
        # DM-topic-aware routing as the text send (#22773 — media previously used a bare thread_id and
        # landed in the General lane for private DM topics). Skip on an in-flight confirmation timeout: the
        # gateway loop is contended, so each media send would also block its 30s budget, and the text
        # payload is already assumed delivered (#38922). Record the skipped attachments so the drop is
        # visible rather than silently lost.
        if (topic_name := sd._named_dm_topic(t)) is not None and adapter_ok and not timed_out:
            adapter_ok = sd._resolve_named_dm_topic(
                t, topic_name, media_metadata, delivery_errors, len(media_files), refresh=False) or bool(text_to_send)
        if adapter_ok and not timed_out and media_files:
            sd._live_send_media(t, media_metadata, media_files, delivery_errors, unverified_targets, topic_name)
        elif timed_out and media_files:
            sd._note_target_error(
                job,
                f"{len(media_files)} media attachment(s) not delivered to "
                f"{t.where} (live adapter confirmation timed out)",
                delivery_errors)

        if adapter_ok:
            # Log WHERE it went: a ghost delivery in the wrong lane is otherwise indistinguishable.
            logger.info(
                # Log WHERE it went, not just that it went: a ghost delivery that landed in the wrong lane
                # (General topic instead of the routed thread) is indistinguishable from a real one without
                # the routing identity (#77763).
                "Job '%s': delivered to %s:%s via live adapter thread=%s message_id=%s",
                job["id"], t.platform_name, t.chat_id,
                route_thread_id if route_thread_id is not None else "-",
                delivered_message_id if delivered_message_id is not None else "-")
            delivered = True
            sd._seed_live_delivery_sessions(t, delivered_message_id)
    except Exception as e:
        err_msg = f"live adapter delivery to {t.where} failed: {e}"
        if not any(err_msg in err for err in target_errors):
            target_errors.append(err_msg)
        sd._warn_live_lane_failure(job, err_msg, t.is_relay)
    return delivered


def _standalone_send(
    t: sd._TargetDelivery, content: str, media_files: list) -> tuple[Any, Optional[str]]:
    """Run the standalone sender for one target: ``(result, None)`` or ``(None, error)`` (already
    logged — WARNING for a shutdown race, ERROR with traceback otherwise)."""
    from tools.send_message_tool import _send_to_platform
    job = t.job
    shutdown_msg = f"delivery to {t.where} skipped — interpreter is shutting down"

    send_timeout = sd._get_standalone_send_timeout()

    async def _send():
        # The bound lives inside the coroutine: the running-loop fallback below closes ``coro``
        # unstarted, and a wait_for wrapper created out here would be left never awaited.
        # notify: the live lane's metadata["notify"] (cron.delivery.notify), so a brief rings either way.
        return await asyncio.wait_for(_send_to_platform(
            t.platform, t.pconfig, t.chat_id, content, thread_id=t.thread_id,
            media_files=media_files, notify=t.notify_delivery), timeout=send_timeout)

    def _warned(msg: str) -> tuple[None, str]:
        logger.warning("Job '%s': %s", job["id"], msg)
        return None, msg

    def _failed(e) -> tuple[None, str]:
        msg = f"delivery to {t.where} failed: {e}"
        logger.error("Job '%s': %s", job["id"], msg, exc_info=True)
        return None, msg

    # Interpreter finalizing (SIGTERM/restart/OOM): asyncio.run and a fresh ThreadPoolExecutor both
    # raise "cannot schedule new futures after interpreter shutdown" — warn, not ERROR traceback.
    if sd._sched._interpreter_shutting_down():
        return _warned(shutdown_msg)
    # The live lane failed closed on an empty payload; standalone senders don't (Telegram returns
    # success=True for empty content WITHOUT an API call) — a phantom delivery would result.
    if not content.strip() and not media_files:
        return _warned(f"standalone send skipped (empty text and no media) for {t.where}")
    coro = _send()
    try:
        return asyncio.run(coro), None
    except TimeoutError:
        # The send may still complete on the gateway loop (the dispatch shield keeps an in-flight
        # send un-cancelled); the run is released instead of waiting on it unbounded (#115469).
        msg = (f"standalone send to {t.where} timed out after {send_timeout}s "
               "(the send may still be in flight)")
        logger.error("Job '%s': %s", job["id"], msg)
        return None, msg
    except RuntimeError as run_err:
        # asyncio.run() refuses inside a running loop; close the unstarted coro, retry in a thread.
        coro.close()
        if sd._sched._interpreter_shutting_down(run_err):
            return _warned(shutdown_msg)
        # The fallback can itself raise (SMTP, result timeout); catch it or remaining targets skip.
        try:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                # A fresh thread does NOT inherit the profile ContextVars (home override + secret
                # scope); run in the active context or the sender reads the default bot token.
                return pool.submit(contextvars.copy_context().run, asyncio.run, _send()).result(
                    timeout=30), None
            finally:
                pool.shutdown(wait=False)
        except Exception as e:
            if sd._sched._interpreter_shutting_down(e):
                return _warned(shutdown_msg)
            return _failed(e)
    except Exception as e:
        return _failed(e)


def _queue_for_live_reconnect(t: sd._TargetDelivery, content: str, media_files: list, delivery_errors: list) -> None:
    """Hand a payload the live lane rejected as reconnect-only (``send_path_degraded``) and the
    standalone lane then failed to send to the delivery ledger, as a failed reconnect-only row
    owned by the adapter that rejected it: the post-reconnect sweep redelivers it (#125363). Only
    reached after standalone failed, so nothing was sent and a replay cannot duplicate. The ledger
    carries text only; dropped attachments are reported."""
    try:
        from gateway.delivery_ledger import (
            compute_obligation_id, is_reconnect_only, ledger_enabled, mark_failed, record_obligation)
        if not is_reconnect_only(t.live_error) or not ledger_enabled():
            return
        session_key = f"cron:{t.platform_name}:{t.chat_id}" + (f":{t.thread_id}" if t.thread_id else "")
        obligation_id = compute_obligation_id(session_key, f"job:{t.job.get('id', '?')}", content)
        record_obligation(
            obligation_id=obligation_id, session_key=session_key, platform=t.platform_name,
            chat_id=str(t.chat_id), thread_id=t.thread_id, content=content,
            adapter_profile=getattr(getattr(t.transport, "adapter", None), "_owner_profile", None))
        mark_failed(obligation_id, str(t.live_error))
    except Exception:
        logger.warning("Job '%s': could not queue %s for post-reconnect redelivery",
                       t.job.get("id"), t.where, exc_info=True)
        return
    note = f"queued text for {t.where} for redelivery once the live adapter reconnects"
    if media_files:
        note += f" ({len(media_files)} attachment(s) not queued)"
    logger.warning("Job '%s': %s", t.job.get("id"), note)
    delivery_errors.append(note)


def _deliver_standalone(
    t: sd._TargetDelivery, content: str, media_files: list, target_errors: list, delivery_errors: list,
) -> None:
    """Standalone fallback for a target the live lane did not deliver."""
    job = t.job
    if t.is_relay:
        # Relay owns the destination and credential; a native retry could duplicate — fail closed.
        if not target_errors:
            target_errors.append(f"relay delivery to {t.where} failed")
        delivery_errors.extend(target_errors)
        return
    result, err = sd._standalone_send(t, content, media_files)
    if err is None and result and result.get("error"):
        # Not inside an except block — the error comes from the result dict, no traceback.
        err = f"delivery error: {result['error']} (target {t.where})"
        logger.error("Job '%s': %s", job["id"], err)
    if err is not None:
        target_errors.append(err)
        delivery_errors.extend(target_errors)
        # A satellite profile's worker has no platform token, so standalone cannot stand in for a
        # live adapter that is only waiting to reconnect: keep the payload for that adapter.
        sd._queue_for_live_reconnect(t, content, media_files, delivery_errors)
        return
    # Standalone senders report per-file attachment failures in ``warnings`` while returning
    # success; surface them so a vanished attachment doesn't mark the run ok.
    for _w in (result.get("warnings") if isinstance(result, dict) else None) or []:
        msg = f"delivery warning: {_w} (target {t.where})"
        logger.error("Job '%s': %s", job["id"], msg)
        delivery_errors.append(msg)
    logger.info("Job '%s': delivered to %s:%s", job["id"], t.platform_name, t.chat_id)
    # Thread seeding only happens on the live lane, so no thread_seeded gate applies here.
    sd._maybe_mirror_cron_delivery(
        job, t.platform_name, t.chat_id, t.mirror_text, thread_id=t.thread_id,
        user_id=t.origin_user_id,
        enabled=t.mirror_this_target)


